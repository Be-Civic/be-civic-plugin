#!/usr/bin/env python3
"""detect-browser-capability.py.

Detects the browser-driving signals path-traversal needs, using only what a
local Python subprocess can honestly observe: the operating system and whether
a Chrome/Chromium binary is installed on this machine.

What this script CAN detect (real, filesystem/OS signals):
  - OS_PLATFORM: which OS we are on (macos | windows | linux | unknown).
  - CHROME_INSTALLED: whether a Chrome/Chromium binary exists at a
    platform-standard install location or on PATH. This is the substrate-side
    prerequisite for a browser-driving tool to do anything useful.

What this script CANNOT detect, and why:
  The preamble runs as a detached `python3` subprocess. It has no view of the
  host agent's tool list or model capabilities. So the two capability keys the
  harness contract ultimately needs —

    BROWSER_TOOL_AVAILABLE  (does the host expose a browser-control tool?)
    VISION_AVAILABLE        (does the host model have vision?)

  — depend on the host's runtime surface, not on anything visible from a
  subprocess. There is no environment variable or file a subprocess can read to
  learn the host's tool list. The honest answer from here is `unknown`; the
  agent itself resolves the true value from its own tool list at session start
  (the harness instructions already tell the agent to inspect its own tools and
  ask the user once at the first browser-needing step).

  We still emit a useful, honest default rather than a flat placeholder:
    - BROWSER_TOOL_AVAILABLE: we can detect a locally installed Chrome (the
      substrate prerequisite for a browser tool to drive anything), but NOT
      whether the host actually exposes the tool. So we emit `unknown` and let
      the agent confirm against its tool list. We deliberately never emit `yes`
      from here — a false `yes` is worse than `unknown`, because it would make
      path-traversal attempt a tool that may not exist.
    - VISION_AVAILABLE: not observable from a subprocess at all -> `unknown`.

  TODO(runtime-signal): if a future host binding exports its capability surface
  to the subprocess environment (e.g. a CLAUDE_TOOLS env var listing available
  tool names, or a CLAUDE_VISION=1 flag), read it here and upgrade
  BROWSER_TOOL_AVAILABLE / VISION_AVAILABLE from `unknown` to a real yes/no.
  Until such a signal exists, `unknown` + agent-side tool-list resolution is the
  honest contract.

Output schema (KEY: VALUE lines):
  OS_PLATFORM:            macos | windows | linux | unknown
  CHROME_INSTALLED:       yes | no | unknown
  BROWSER_TOOL_AVAILABLE: unknown   (agent resolves from its own tool list)
  VISION_AVAILABLE:       unknown   (agent resolves from its own tool list)

Runtime: Python 3 stdlib only (os, platform, shutil, pathlib).
Cross-platform: macOS, Windows (native), Linux.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def detect_os() -> str:
    """Map platform.system() to the harness vocabulary."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    return "unknown"


def _macos_chrome_installed() -> bool:
    apps = [
        Path("/Applications/Google Chrome.app"),
        Path("/Applications/Chromium.app"),
        Path.home() / "Applications" / "Google Chrome.app",
    ]
    return any(p.exists() for p in apps)


def _windows_chrome_installed() -> bool:
    candidates: list[Path] = []
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key)
        if base:
            candidates.append(
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            )
    return any(p.exists() for p in candidates)


def _linux_chrome_installed() -> bool:
    binaries = (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    )
    return any(shutil.which(b) is not None for b in binaries)


def detect_chrome(os_platform: str) -> str:
    """yes | no | unknown — whether a Chrome/Chromium binary is installed.

    Returns `unknown` on an unrecognised OS rather than guessing `no`."""
    try:
        if os_platform == "macos":
            return "yes" if _macos_chrome_installed() else "no"
        if os_platform == "windows":
            return "yes" if _windows_chrome_installed() else "no"
        if os_platform == "linux":
            return "yes" if _linux_chrome_installed() else "no"
    except OSError:
        return "unknown"
    return "unknown"


def main() -> int:
    os_platform = detect_os()
    chrome_installed = detect_chrome(os_platform)

    print(f"OS_PLATFORM: {os_platform}")
    print(f"CHROME_INSTALLED: {chrome_installed}")
    # Host-surface capabilities a subprocess cannot observe. `unknown` is the
    # honest default; the agent confirms against its own tool list. We never
    # emit `yes` from here — a false positive would make path-traversal attempt
    # a tool that may not exist.
    print("BROWSER_TOOL_AVAILABLE: unknown")
    print("VISION_AVAILABLE: unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
