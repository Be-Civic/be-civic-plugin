#!/usr/bin/env python3
"""scan-pending-state.py.

Scan for pending submissions a prior session buffered when the wire was
unreachable (or scrub-rules could not be confirmed) and could not send.

Per the harness contract (handbook 05-product/50-harness.md §4.2, Pending-state
scan): read `${SUBSTRATE_STATE}/sessions/*/pending-submissions.jsonl`. When any
such file holds at least one valid buffered submission line, emit
`PENDING_STATE: pending_submissions` followed by up to 3 enumerated items the
gate skill can render; otherwise emit `PENDING_STATE: none`. The gate skill
offers the user a "handle now / set aside" branch on a non-empty result, routing
into `bc-session-close` resume-submit mode.

State-dir resolution: the state directory comes from the BC_SUBSTRATE_STATE env
var that preamble.py passes down (the already-resolved
${SUBSTRATE_DATA}/.be-civic/state child). This script MUST NOT re-resolve
CLAUDE_PLUGIN_DATA — that surface is non-persistent on Cowork (bug #51398) and is
no longer the durable state home.

Buffer line shapes are V2 submission shapes (Issue v5 / Validation v5 /
Feedback v1 / Rating v4), one JSON object per line, plus a `staged_at` timestamp
added at buffering time. The scan is shape-agnostic: it counts any line that
parses as a JSON object, so it is robust across submission types and forward
schema bumps. It never re-validates against a fixed submission schema.

Output schema:
  PENDING_STATE: none
  PENDING_STATE: pending_submissions
    - <item summary>            (up to 3 lines, only after pending_submissions)

Runtime: Python 3 stdlib only (pathlib, json).
"""

import json
import os
import sys
from pathlib import Path

# Cap on enumerated item lines, per handbook 50-harness §4.2 ("up to 3
# enumerated items"). The count of files/lines beyond this is not surfaced;
# the marker line itself is the actionable signal.
MAX_ENUMERATED = 3


def _state_dir() -> Path | None:
    """The resolved state dir, from preamble's BC_SUBSTRATE_STATE handoff.

    Returns None pre-onboarding / in the dev loop (no durable surface yet), in
    which case there is no deferred state to surface.
    """
    raw = os.environ.get("BC_SUBSTRATE_STATE")
    return Path(raw) if raw else None


def _summarise(item: dict, fallback: str) -> str:
    """A one-line, shape-agnostic plain summary of a buffered submission.

    V2 submission shapes don't share a single field name across types, so prefer
    a recognised type/id pair when present and degrade gracefully to the
    fallback (the buffer's file + line position) otherwise. Never renders raw
    JSON — the gate skill shows users plain English.
    """
    type_keys = ("submission_type", "kind", "type")
    id_keys = ("submission_id", "id")
    label = next(
        (str(item[k]) for k in type_keys if isinstance(item.get(k), str) and item[k]),
        "submission",
    )
    ident = next(
        (str(item[k]) for k in id_keys if isinstance(item.get(k), str) and item[k]),
        None,
    )
    staged = item.get("staged_at")
    summary = f"{label} {ident}" if ident else label
    if isinstance(staged, str) and staged:
        summary += f" (staged {staged})"
    return summary or fallback


def _scan(state: Path) -> list[str]:
    """Return one summary line per buffered submission, in stable path order.

    A submission counts only when its line parses as a JSON object. Blank lines
    and malformed lines are skipped (a partially-written buffer must not be lost
    or mis-counted). Unreadable files are skipped rather than crashing the scan —
    the preamble degrades a crash to `PENDING_STATE: probe_failed`, but a single
    bad file should not mask the rest.
    """
    items: list[str] = []
    sessions = state / "sessions"
    if not sessions.is_dir():
        return items
    for buf in sorted(sessions.glob("*/pending-submissions.jsonl")):
        try:
            lines = buf.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(obj, dict):
                continue
            items.append(_summarise(obj, f"{buf.parent.name}/pending-submissions.jsonl#{n}"))
    return items


def main() -> int:
    state = _state_dir()
    items = _scan(state) if state is not None else []
    if not items:
        print("PENDING_STATE: none")
        return 0
    print("PENDING_STATE: pending_submissions")
    for summary in items[:MAX_ENUMERATED]:
        print(f"  - {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
