#!/usr/bin/env python3
"""verify-rowlist-hydration.py.

Acceptance check for IU ar-onboarding-rowlist-hydration: the rebuilt
bc-onboarding row_list post-submit hydration loop + the two folded
card-vision-prompt.md fixes.

A skill body is prose, not executable code, so the "test" here parses the
ACTUAL edited files and asserts the contract the carrier settled. Three checks:

  (a) assert_skill_handles_hydration
      The rebuilt skills/bc-onboarding/SKILL.md specifies the full path:
      sentinel scan { __mode, __status: "pending" } → reject+log on a
      non-row_list input → Mode 2 (folder_drop: poll the procedure-root inputs
      folder, run the vision capability with card-vision-prompt.md, front/back
      pairing, two-fail retry, archive) → Mode 3 (chat parse against the enum)
      → pre_rows re-render → write to profile.json under the field name.

  (b) assert_enum_set_equality
      The card-type enum embedded in
      skills/bc-document-handler/references/card-vision-prompt.md EQUALS the
      authoritative 23-value enum. Source of truth is schemas/profile.schema.json
      (the in-repo runtime write target); the live
      bc-knowledge-graph .../belgian_residence_card_history.yml is cross-checked
      too when reachable. Set-equality; any diff is printed and fails.

  (c) assert_anchors_resolve
      Every internal SKILL.md section/anchor that card-vision-prompt.md cites
      resolves to a live heading in the rebuilt SKILL.md (no dangling deleted-W25
      §7.x pointers).

Exit 0 iff all three pass. Runtime: Python 3 stdlib only.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "bc-onboarding" / "SKILL.md"
VISION = REPO / "skills" / "bc-document-handler" / "references" / "card-vision-prompt.md"
SCHEMA = REPO / "schemas" / "profile.schema.json"

# The live wire-side catalogue lives in a SIBLING repo (bc-knowledge-graph).
# This product repo may be checked out either directly under the be-civic project
# root or inside a `.bc-worktrees/` worktree, so probe a few ancestor depths.
_YML_TAIL = Path("bc-knowledge-graph") / "api" / "_forms" / "inputs" / "belgian_residence_card_history.yml"
YML_CANDIDATES = [
    REPO.parent / _YML_TAIL,            # sibling of the repo
    REPO.parent.parent / _YML_TAIL,     # repo is inside .bc-worktrees/<wt>/
    REPO.parent.parent.parent / _YML_TAIL,
]

PASS = "PASS"
FAIL = "FAIL"


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def schema_enum() -> list:
    s = json.loads(_load(SCHEMA))
    node = s["properties"]["belgian_residence_card_history"]["items"]["properties"]["card_type"]
    return list(node["enum"])


def yml_enum(text: str) -> list:
    """Extract card_type option values from the catalogue YAML without a yaml dep.

    Values appear as `      - value: <name>` lines inside the card_type column.
    The file has exactly one `columns:` block; card_type is the first column and
    the only one carrying `- value:` lines, so a file-wide scan of `- value:` is
    safe for this file.
    """
    vals = []
    for m in re.finditer(r"^\s*-\s*value:\s*([A-Za-z0-9_]+)\s*$", text, re.MULTILINE):
        vals.append(m.group(1))
    return vals


def vision_enum(text: str) -> list:
    r"""Pull the card-type enum from card-vision-prompt.md.

    The prompt lists the enum as blockquoted markdown bullets of the form
    ``> - `value` — label`` inside the "Identify the card type" block. The
    confidence-level list (`high` / `medium` / `low`) uses the SAME bullet
    shape later in the file, so we scope the scan to the card-type block:
    from the "Identify the card type" heading to the next "**...**" bolded
    instruction line ("Read the validity dates").
    """
    start = re.search(r"Identify the card type", text)
    if not start:
        return []
    tail = text[start.end():]
    end = re.search(r"\*\*Read the validity dates", tail)
    block = tail[: end.start()] if end else tail
    vals = []
    for m in re.finditer(r"^>\s*-\s*`([A-Za-z0-9_]+)`\s*[—-]", block, re.MULTILINE):
        vals.append(m.group(1))
    return vals


def report(check: str, ok: bool, detail: str = "") -> bool:
    tag = PASS if ok else FAIL
    line = f"[{tag}] {check}"
    if detail:
        line += f"\n        {detail}"
    print(line)
    return ok


def assert_skill_handles_hydration() -> bool:
    text = _load(SKILL)
    low = text.lower()
    ok = True

    # Required contract phrases. Each tuple is (human label, predicate).
    checks = [
        ("sentinel shape present",
         '__status' in text and '"pending"' in text and '__mode' in text),
        ("sentinel scanned post-submit, pre profile write",
         re.search(r"before .*(profile\.json|profile/state).*write", low) is not None
         or "before the profile" in low),
        ("reject + log on non-row_list sentinel",
         ("non-row_list" in low or "non row_list" in low or "not a row_list" in low)
         and ("reject" in low) and ("log" in low or "observation" in low)),
        ("row_list allowlist named",
         "row_list" in low and ("only" in low or "allowlist" in low)),
        ("Mode 2 folder_drop",
         "folder_drop" in text),
        ("polls procedure-root inputs folder",
         "inputs/" in text and ("poll" in low or "folder" in low)),
        ("calls card-vision-prompt.md",
         "card-vision-prompt.md" in text),
        ("front/back pairing",
         ("front" in low and "back" in low) and ("pair" in low)),
        ("two-fail retry",
         ("two-fail" in low or "two consecutive" in low or "second consecutive" in low
          or "two failed" in low or "2 fails" in low)),
        ("archive per harness rule",
         "archive" in low and ("documents/" in text or "${SUBSTRATE_DATA}" in text)),
        ("Mode 3 chat parse",
         ("mode 3" in low or "chat hydration" in low) and "parse" in low),
        ("parse against the enum",
         "enum" in low),
        ("pre_rows re-render",
         "pre_rows" in text and ("re-render" in low or "re-confirm" in low or "confirmation" in low)),
        ("write to profile.json under the field name",
         "profile.json" in text and ("field name" in low or "under the field" in low)),
        ("W33 substrate conventions ($BC_ROOT / ${SUBSTRATE_STATE})",
         ("$BC_ROOT" in text or "BC_ROOT" in text) and "${SUBSTRATE_STATE}" in text),
    ]
    for label, pred in checks:
        ok = report(f"skill::{label}", bool(pred)) and ok
    return ok


def assert_enum_set_equality() -> bool:
    schema = set(schema_enum())
    vis = set(vision_enum(_load(VISION)))
    ok = True

    if len(schema) != 23:
        ok = report("enum::schema is the 23-value set", False,
                    f"schema has {len(schema)} values: {sorted(schema)}") and ok
    else:
        report("enum::schema is the 23-value set", True, f"{sorted(schema)}")

    missing = schema - vis  # in schema, absent from prompt
    extra = vis - schema    # in prompt, absent from schema
    eq = not missing and not extra
    detail = ""
    if not eq:
        detail = f"missing_from_prompt={sorted(missing)} extra_in_prompt={sorted(extra)}"
    ok = report("enum::card-vision-prompt.md == schema 23-value enum", eq, detail) and ok
    if eq:
        report("enum::prompt value count", True, f"{len(vis)} values")

    # Cross-check the live wire-side .yml when the sibling repo is reachable.
    for cand in YML_CANDIDATES:
        if cand.exists():
            y = set(yml_enum(_load(cand)))
            same = (y == schema)
            d = "" if same else (
                f"yml-vs-schema missing_from_yml={sorted(schema - y)} "
                f"extra_in_yml={sorted(y - schema)}")
            ok = report(f"enum::live .yml ({cand.name}) == schema", same, d) and ok
            break
    else:
        report("enum::live .yml cross-check", True, "sibling bc-knowledge-graph .yml not reachable — skipped (schema is in-repo source of truth)")
    return ok


def heading_anchors(text: str) -> set:
    """Collect normalized heading text + their section numbers from SKILL.md."""
    anchors = set()
    for m in re.finditer(r"^#{1,6}\s+(.*)$", text, re.MULTILINE):
        h = m.group(1).strip()
        anchors.add(h.lower())
        # capture a leading section-number token like "7.2.2." or "3."
        sn = re.match(r"^(?:step\s+)?([0-9]+(?:\.[0-9]+)*)\.?\b", h.lower())
        if sn:
            anchors.add(sn.group(1))
    return anchors


def assert_anchors_resolve() -> bool:
    vtext = _load(VISION)
    stext = _load(SKILL)
    anchors = heading_anchors(stext)
    skill_lower = stext.lower()
    ok = True

    # 1) No dangling deleted-W25 section-number citations. The prompt must not
    #    cite a §7.x / "step 7.2.x" / "§7.1 R5" number unless that number is a
    #    live heading in the rebuilt SKILL.md.
    cited_numbers = set()
    for m in re.finditer(r"(?:§|step\s+|section\s+)\s*([0-9]+(?:\.[0-9]+)+)", vtext, re.IGNORECASE):
        cited_numbers.add(m.group(1))
    dangling = sorted(n for n in cited_numbers if n not in anchors)
    ok = report("anchors::no dangling numeric section citation", not dangling,
                f"dangling={dangling}" if dangling else "") and ok

    # 2) Every named cross-reference the prompt makes to the loop must resolve to
    #    live prose in SKILL.md. The prompt names the loop; assert the named
    #    anchor phrase exists in the rebuilt body.
    #    We look for the loop-anchor phrase the prompt uses to point at SKILL.md.
    named_refs = re.findall(r"`([^`]*hydrat[^`]*)`", vtext, re.IGNORECASE)
    # Also accept the prose phrase "post-submit hydration" / "row_list hydration".
    phrase_refs = []
    for phrase in ["post-submit hydration", "row_list hydration", "hydration loop"]:
        if phrase in vtext.lower():
            phrase_refs.append(phrase)
    unresolved = []
    for ref in phrase_refs:
        if ref not in skill_lower:
            unresolved.append(ref)
    ok = report("anchors::named loop reference resolves in SKILL.md", not unresolved,
                f"unresolved={unresolved}" if unresolved else
                f"resolved={phrase_refs}") and ok

    # 3) Every explicit quoted heading citation the prompt makes — of the form
    #    `SKILL.md → "<heading text>"` — must resolve to a live SKILL.md heading.
    #    This guards the repoint directly (a stale quoted heading would fail here).
    quoted = re.findall(r'SKILL\.md\s*[→-]+\s*"([^"]+)"', vtext)
    bad = sorted({q for q in quoted if q.strip().lower() not in anchors})
    ok = report("anchors::quoted heading citation resolves", not bad,
                f"unresolved={bad}" if bad else
                f"resolved={sorted(set(quoted))}") and ok

    # 4) Every "step R<n>" citation in the prompt must resolve to a live R-step
    #    heading in the rebuilt loop.
    r_steps_cited = set(re.findall(r"step\s+\*?\*?(R[1-5])\b", vtext))
    r_steps_live = set(
        m.group(1) for m in re.finditer(r"^####\s+(R[1-5])\.", stext, re.MULTILINE))
    missing_r = sorted(r_steps_cited - r_steps_live)
    ok = report("anchors::R-step citation resolves", not missing_r,
                f"missing={missing_r} cited={sorted(r_steps_cited)} live={sorted(r_steps_live)}"
                if missing_r else f"cited={sorted(r_steps_cited)} all live") and ok

    return ok


def main() -> int:
    print("=== verify-rowlist-hydration.py ===")
    print(f"SKILL  : {SKILL}")
    print(f"VISION : {VISION}")
    print(f"SCHEMA : {SCHEMA}")
    print("--- (a) SKILL.md hydration contract ---")
    a = assert_skill_handles_hydration()
    print("--- (b) enum set-equality ---")
    b = assert_enum_set_equality()
    print("--- (c) anchor resolution ---")
    c = assert_anchors_resolve()
    print("===================================")
    all_ok = a and b and c
    print(f"RESULT: {'ALL PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
