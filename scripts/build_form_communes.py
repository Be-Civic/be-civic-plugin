#!/usr/bin/env python3
"""build_form_communes.py — embed the commune name+postcode picker into the forms.

BUILD-TIME tool (not invoked at runtime). Reads the public Belgian commune list
(`data/communes.json`: name + postcodes, REFNIS + reconciled postcodes) and
injects, into each `onboarding.<locale>.html`, a type-to-filter picker for the
Section-1 "Which commune?" field that matches on BOTH the commune NAME and the
POSTCODE — because nobody knows their NIS5 code, but everyone knows their commune
name and their postcode.

The field stays a plain text input (so free text still works) backed by a
`<datalist>`. A tiny embedded script builds the datalist options ("Name (postcode)")
from a compact index and, on every change, resolves whatever the user typed/picked
(name, "Name (postcode)", or a bare postcode) to the authoritative NIS5, writing it
to a HIDDEN `commune_nis5` field. So the visible value the user sees is their
commune name + postcode; the NIS5 is captured invisibly and submitted alongside.
No API call, no name→code guessing by the agent.

Communes are public reference data, so this ships in the plugin (not behind the
corpus API). Re-run whenever `data/communes.json` changes. Idempotent.

  python3 scripts/build_form_communes.py [--root <plugin-root>]

Runtime: Python 3 stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Shell file → which commune-name locale to display. Belgian commune names are
# official only in fr/nl/de; uk/ar fall back to French.
SHELL_LOCALE = {
    "onboarding.html": "en",        # the EN fallback shell
    "onboarding.en.html": "en",
    "onboarding.fr.html": "fr",
    "onboarding.nl.html": "nl",
    "onboarding.de.html": "de",
    "onboarding.uk.html": "fr",
    "onboarding.ar.html": "fr",
}

START = "<!--BC_COMMUNE_PICKER_START-->"
END = "<!--BC_COMMUNE_PICKER_END-->"
_INPUT_RE = re.compile(r'<input id="bc-commune"[^>]*>')
_BLOCK_RE = re.compile(r"\s*" + re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
# Also clears the earlier bare-datalist embed (no markers) on first re-run.
_BARE_DATALIST_RE = re.compile(r'\s*<datalist id="bc-communes">.*?</datalist>', re.DOTALL)
_BARE_HIDDEN_RE = re.compile(r'\s*<input id="bc-commune-nis5"[^>]*>')

# The picker script. {DATA} is replaced with the compact index literal. Pure
# vanilla JS, no deps; builds the datalist + a normalized lookup, resolves on
# input/change to the hidden NIS5 field. Kept terse to stay within the widget
# payload budget.
_SCRIPT = """
      <datalist id="bc-communes"></datalist>
      <input id="bc-commune-nis5" data-name="commune_nis5" type="hidden">
      <script>
      /* Be Civic commune picker: match on name OR postcode, capture NIS5 invisibly. */
      (function(){
        var DATA=%s;
        var dl=document.getElementById('bc-communes');
        var inp=document.getElementById('bc-commune');
        var hid=document.getElementById('bc-commune-nis5');
        if(!dl||!inp||!hid) return;
        function norm(s){return (s||'').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase().replace(/[\\s\\-'.()]+/g,' ').trim();}
        var idx={}, frag=document.createDocumentFragment();
        /* Resolution is keyed ONLY on the full "Name (postcode)" option, so a bare
           name or postcode never auto-resolves — the user must pick a specific combo.
           That makes shared postcodes (1348) and shared names (Saint-Nicolas) safe by
           construction. Defensive null on any duplicate key just in case. */
        function put(k,rec){ if(k in idx){ if(idx[k]&&idx[k].nis5!==rec.nis5) idx[k]=null; } else idx[k]=rec; }
        DATA.forEach(function(row){
          var p=row.split('|'), nis=p[0], name=p[1], pcs=p[2]?p[2].split(','):[], rec={name:name,nis5:nis};
          if(pcs.length){ pcs.forEach(function(pc){
            var label=name+' ('+pc+')', o=document.createElement('option');
            o.value=label; frag.appendChild(o); put(norm(label),rec);
          }); } else { var o=document.createElement('option'); o.value=name; frag.appendChild(o); put(norm(name),rec); }
        });
        dl.appendChild(frag);
        function resolve(){ var hit=idx[norm(inp.value.trim())]; hid.value=(hit&&hit.nis5)?hit.nis5:''; }
        inp.addEventListener('input',resolve); inp.addEventListener('change',resolve);
      })();
      </script>
"""


def _display_name(entry: dict, locale: str) -> str:
    n = entry.get("name", {})
    return n.get(locale) or n.get("fr") or n.get("en") or ""


def _index_literal(communes: list[dict], locale: str) -> tuple[str, int]:
    rows = []
    for c in communes:
        nis = c.get("nis5")
        name = _display_name(c, locale)
        if not nis or not name:
            continue
        # pipe/comma compact form: "nis5|name|pc,pc". Names have no '|'; postcodes are digits.
        pcs = ",".join(c.get("postcodes", []))
        rows.append(f"{nis}|{name}|{pcs}")
    rows.sort(key=lambda r: r.split("|")[1])
    return json.dumps(rows, ensure_ascii=False), len(rows)


def _inject(html: str, communes: list[dict], locale: str) -> tuple[str, str, int]:
    html = _BLOCK_RE.sub("", html)                       # idempotent: drop prior marked block
    html = _BARE_DATALIST_RE.sub("", html)               # migrate: drop the old bare datalist
    html = _BARE_HIDDEN_RE.sub("", html)                 # and any stray hidden field
    html = html.replace(' list="bc-communes"', "")       # and the list attr
    m = _INPUT_RE.search(html)
    if not m:
        return html, "no_commune_input", 0
    tag = m.group(0).replace('<input id="bc-commune"', '<input id="bc-commune" list="bc-communes"', 1)
    literal, n = _index_literal(communes, locale)
    block = START + (_SCRIPT % literal) + "      " + END
    html = html[: m.start()] + tag + "\n" + block + html[m.end():]
    return html, "ok", n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Embed the commune name+postcode picker into the onboarding forms.")
    p.add_argument("--root", default=None)
    args = p.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    try:
        doc = json.loads((root / "data" / "communes.json").read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"ERROR: cannot read communes.json: {exc}", file=sys.stderr)
        return 1
    communes = doc["communes"] if isinstance(doc, dict) else doc
    refs = root / "skills" / "bc-onboarding" / "references"
    print(f"communes: {len(communes)}")
    rc = 0
    for fname, locale in SHELL_LOCALE.items():
        path = refs / fname
        if not path.exists():
            print(f"  skip {fname} (absent)")
            continue
        new_html, status, n = _inject(path.read_text(encoding="utf-8"), communes, locale)
        if status != "ok":
            print(f"  FAIL {fname}: {status}")
            rc = 1
            continue
        path.write_text(new_html, encoding="utf-8", newline="\n")
        print(f"  ok   {fname} (locale={locale}, {n} communes indexed)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
