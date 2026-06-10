#!/usr/bin/env python3
"""scan-orphan-buffers.py.

Scan for orphaned ready-to-draft research notes — discovery work a prior session
left buffered for the drafter but never handed off (the customer didn't reach
session-close, or deferred the drafter handoff).

Per the harness contract (handbook 05-product/50-harness.md §4.2, Pending-state
scan): read `${SUBSTRATE_DATA}/<procedure-slug>/memory/research-notes-*.md` and
count the files whose frontmatter carries `status: ready_to_draft`. The preamble
surfaces the count via the `ORPHAN_SESSIONS_CLEANED:` marker line; the gate skill
routes a non-zero count into `bc-session-close`'s drafter handoff so the buffered
research is offered to the customer ("submit now / keep researching / discard")
rather than silently lost.

State-dir resolution: the hidden state directory comes from the
BC_SUBSTRATE_STATE env var that preamble.py passes down (the already-resolved
${SUBSTRATE_DATA}/.be-civic/state child). Research notes live on the VISIBLE
surface `${SUBSTRATE_DATA}`, which is the grandparent of BC_SUBSTRATE_STATE
(state = ${SUBSTRATE_DATA}/.be-civic/state). This script MUST NOT re-resolve
CLAUDE_PLUGIN_DATA — that surface is non-persistent on Cowork (bug #51398) and is
no longer the durable state home.

The `.be-civic/` hidden subtree is excluded from the per-procedure walk: only
real procedure-slug folders carry `memory/research-notes-*.md`.

Output schema:
  ORPHAN_SESSIONS_CLEANED: <count>   (count of ready_to_draft research-notes)

Runtime: Python 3 stdlib only (pathlib).
"""

import os
import sys
from pathlib import Path

STATE_SUBDIR = ".be-civic"


def _state_dir() -> Path | None:
    """The resolved hidden state dir, from preamble's BC_SUBSTRATE_STATE handoff.

    Returns None pre-onboarding / in the dev loop (no durable surface yet), in
    which case there are no research notes to surface.
    """
    raw = os.environ.get("BC_SUBSTRATE_STATE")
    return Path(raw) if raw else None


def _data_dir(state: Path) -> Path | None:
    """The VISIBLE durable surface ${SUBSTRATE_DATA}.

    state == ${SUBSTRATE_DATA}/.be-civic/state, so SUBSTRATE_DATA is its
    grandparent. Returns None if the layout doesn't match (defensive: never
    walk an unexpected tree).
    """
    if state.name != "state" or state.parent.name != STATE_SUBDIR:
        return None
    return state.parent.parent


def _is_ready_to_draft(note: Path) -> bool:
    """True iff the note's leading YAML frontmatter block sets
    `status: ready_to_draft`.

    Stdlib-only: parse the leading `---`-fenced block by line rather than
    pulling in a YAML dependency. Only the frontmatter is inspected — a
    `status:` mention later in the prose body does not count. Unreadable files
    are treated as not-ready rather than crashing the scan.
    """
    try:
        text = note.read_text(encoding="utf-8")
    except OSError:
        return False
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break  # end of frontmatter
        key, sep, value = stripped.partition(":")
        if sep and key.strip() == "status":
            return value.strip() == "ready_to_draft"
    return False


def _count(data: Path) -> int:
    """Count ready_to_draft research-notes across every procedure-slug folder."""
    count = 0
    for child in sorted(data.iterdir()):
        if not child.is_dir() or child.name == STATE_SUBDIR:
            continue
        memory = child / "memory"
        if not memory.is_dir():
            continue
        for note in sorted(memory.glob("research-notes-*.md")):
            if _is_ready_to_draft(note):
                count += 1
    return count


def main() -> int:
    state = _state_dir()
    count = 0
    if state is not None:
        data = _data_dir(state)
        if data is not None and data.is_dir():
            count = _count(data)
    print(f"ORPHAN_SESSIONS_CLEANED: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
