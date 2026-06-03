#!/usr/bin/env python3
"""scan-orphan-buffers.py.

For sessions > 72h with unsubmitted observation buffers, submit
session_outcome: abandoned_inferred (analytics endpoint, gated on prior session's
analytics opt-in flag), then delete the orphan session directories.

Status: PLACEHOLDER. Authoring per design doc step 5.

State-dir resolution: when this script grows real logic it MUST take the state
directory from the BC_SUBSTRATE_STATE env var that preamble.py passes down (the
already-resolved ${SUBSTRATE_DATA}/.be-civic/state child). It must NOT re-resolve
CLAUDE_PLUGIN_DATA — that surface is non-persistent on Cowork (bug #51398) and is
no longer the durable state home.

Output schema:
  ORPHAN_SESSIONS_CLEANED: <count>

Runtime: Python 3 stdlib only (uses pathlib, urllib.request for analytics submit).
"""

import os
import sys
from pathlib import Path


def _state_dir() -> Path | None:
    """The resolved state dir, from preamble's BC_SUBSTRATE_STATE handoff.

    Returns None pre-onboarding / in the dev loop (no durable surface yet), in
    which case there are no sessions to sweep.
    """
    raw = os.environ.get("BC_SUBSTRATE_STATE")
    return Path(raw) if raw else None


def main() -> int:
    _ = _state_dir()  # placeholder: real sweep walks <state>/sessions/ here.
    print("ORPHAN_SESSIONS_CLEANED: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
