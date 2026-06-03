#!/usr/bin/env python3
"""scan-pending-state.py.

Scan for deferred customer state per harness-spec §H.3:
  - observation_buffer (unsubmitted observation items)
  - research_notes (status: ready_to_draft)
  - staged_submission (status: ready_to_submit)
  - path_traversal_state (paused mid-traversal)

Emit PENDING_STATE: none if empty, else write items to a JSON file and emit
its path. CLAUDE.md surfaces items at session-start before opening framing.

Status: PLACEHOLDER. Authoring per design doc step 5.

State-dir resolution: when this script grows real logic it MUST take the state
directory from the BC_SUBSTRATE_STATE env var that preamble.py passes down (the
already-resolved ${SUBSTRATE_DATA}/.be-civic/state child). It must NOT re-resolve
CLAUDE_PLUGIN_DATA — that surface is non-persistent on Cowork (bug #51398) and is
no longer the durable state home.

Output schema:
  PENDING_STATE: none | <absolute file path>

Runtime: Python 3 stdlib only (pathlib, json).
"""

import os
import sys
from pathlib import Path


def _state_dir() -> Path | None:
    """The resolved state dir, from preamble's BC_SUBSTRATE_STATE handoff.

    Returns None pre-onboarding / in the dev loop (no durable surface yet), in
    which case there is no deferred state to surface.
    """
    raw = os.environ.get("BC_SUBSTRATE_STATE")
    return Path(raw) if raw else None


def main() -> int:
    _ = _state_dir()  # placeholder: real scan reads <state> buffers/notes here.
    print("PENDING_STATE: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
