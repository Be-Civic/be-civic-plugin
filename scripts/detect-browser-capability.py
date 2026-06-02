#!/usr/bin/env python3
"""detect-browser-capability.py.

Two independent checks for path-traversal's runtime needs:
  (a) Is Chrome installed on the machine? Check platform-standard paths:
      - macOS: /Applications/Google Chrome.app
      - Windows: %ProgramFiles%/Google/Chrome/Application/chrome.exe (and per-user)
      - Linux: which google-chrome, which chromium
  (b) Are the relevant MCP connectors connected in Claude Desktop?
      Detected via the harness's tool list at session start, not this script
      directly. This script reports the OS-side Chrome installation;
      MCP-connection signals (CHROME_MCP_CONNECTED) come from CLAUDE.md
      inspecting its own tool list and emitting the flags into session state.

Derived flags computed by CLAUDE.md from these signals:
  PATH_TRAVERSAL_CAPABLE = CHROME_INSTALLED && CHROME_MCP_CONNECTED

Cross-platform considerations: macOS / Windows / Linux paths differ; tolerate
unknown-OS with CHROME_INSTALLED: unknown.

Status: PLACEHOLDER. Authoring per design doc step 5.

Output schema:
  CHROME_INSTALLED: yes | no | unknown
  OS_PLATFORM: macos | windows | linux | unknown

Runtime: Python 3 stdlib only (platform, pathlib, shutil.which).
"""

import sys


def main() -> int:
    print("CHROME_INSTALLED: unknown")
    print("OS_PLATFORM: unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
