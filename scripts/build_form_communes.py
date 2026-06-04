#!/usr/bin/env python3
"""build_form_communes.py — embed the commune datalist into the onboarding forms.

BUILD-TIME tool (not invoked at runtime). Reads the public Belgian commune list
(`data/communes.json`, REFNIS) and injects a `<datalist>` of communes into each
`onboarding.<locale>.html` form, so the Section-1 "Which commune?" field becomes
a type-to-filter picker over the official list instead of free text.

Each option's value is `"<Name> · <NIS5>"` — so when the user picks their commune
the form submits the authoritative NIS5 code directly (e.g. Saint-Gilles → 21013),
killing the wrong-commune risk without an API call, a JS map, or any agent-side
name→NIS5 resolution. Communes are public reference data, so they ship in the
plugin (not behind the corpus API).

Re-run this whenever `data/communes.json` changes. Idempotent: it strips any
prior embed first, then re-injects.

  python3 scripts/build_form_communes.py            # uses ./data + ./skills/...
  python3 scripts/build_form_communes.py --root <plugin-root>

Runtime: Python 3 stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Shell file → which commune-name locale to display. Belgian commune names are
# only official in fr/nl/de; uk/ar fall back to the French name.
SHELL_LOCALE = {
    "onboarding.html": "en",        # the EN fallback shell — English commune names
    "onboarding.en.html": "en",
    "onboarding.fr.html": "fr",
    "onboarding.nl.html": "nl",
    "onboarding.de.html": "de",
    "onboarding.uk.html": "fr",
    "onboarding.ar.html": "fr",
}

DATALIST_ID = "bc-communes"
# Matches the commune input tag (the only `>` is the tag close — no `>` inside
# the quoted style), and an already-injected datalist (for idempotent re-runs).
_INPUT_RE = re.compile(r'<input id="bc-commune"[^>]*>')
_DATALIST_RE = re.compile(
    r'\s*<datalist id="' + re.escape(DATALIST_ID) + r'">.*?</datalist>',
    re.DOTALL,
)


def _display_name(entry: dict, locale: str) -> str:
    name = entry.get("name", {})
    return name.get(locale) or name.get("fr") or name.get("en") or ""


def _build_datalist(communes: list[dict], locale: str) -> tuple[str, int]:
    opts = []
    for c in communes:
        nis5 = c.get("nis5")
        disp = _display_name(c, locale)
        if not nis5 or not disp:
            continue
        # value carries the NIS5 so the existing submit collector captures it
        # verbatim (commune: <Name> · <NIS5>). HTML-escape the few specials.
        val = f"{disp} · {nis5}".replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        opts.append(f'<option value="{val}">')
    opts.sort()
    inner = "".join(opts)
    return (
        f'\n      <datalist id="{DATALIST_ID}">{inner}</datalist>',
        len(opts),
    )


def _inject(html: str, datalist: str) -> tuple[str, str]:
    """Return (new_html, status). Idempotent: strips any prior embed first."""
    # 1. Remove a previously injected datalist.
    html = _DATALIST_RE.sub("", html)
    # 2. Find the commune input.
    m = _INPUT_RE.search(html)
    if not m:
        return html, "no_commune_input"
    tag = m.group(0)
    # 3. Ensure list="bc-communes" on the input (idempotent).
    if f'list="{DATALIST_ID}"' not in tag:
        new_tag = tag.replace(
            '<input id="bc-commune"',
            f'<input id="bc-commune" list="{DATALIST_ID}"',
            1,
        )
    else:
        new_tag = tag
    # 4. Replace the input with input + datalist right after it.
    html = html[: m.start()] + new_tag + datalist + html[m.end():]
    return html, "ok"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Embed the commune datalist into the onboarding forms.")
    p.add_argument("--root", default=None, help="plugin root (default: the script's parent dir)")
    args = p.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    communes_path = root / "data" / "communes.json"
    refs = root / "skills" / "bc-onboarding" / "references"

    try:
        communes = json.loads(communes_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"ERROR: cannot read {communes_path}: {exc}", file=sys.stderr)
        return 1
    print(f"communes source: {communes_path} ({len(communes)} entries)")

    rc = 0
    for fname, locale in SHELL_LOCALE.items():
        path = refs / fname
        if not path.exists():
            print(f"  skip {fname} (absent)")
            continue
        datalist, n = _build_datalist(communes, locale)
        html = path.read_text(encoding="utf-8")
        new_html, status = _inject(html, datalist)
        if status != "ok":
            print(f"  FAIL {fname}: {status}")
            rc = 1
            continue
        path.write_text(new_html, encoding="utf-8", newline="\n")
        print(f"  ok   {fname} (locale={locale}, {n} options)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
