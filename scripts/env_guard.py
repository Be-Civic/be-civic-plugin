#!/usr/bin/env python3
"""env_guard.py — the single Be Civic harness-key commit guard.

The security invariant this module owns:

    The harness key at the EXACT nested path `.be-civic/state/.env`, inside the
    ONE user-owned project repo, is NEVER committed to git history.

Before this module existed the invariant was implemented four times, in two
languages, each a near-copy of the others:

    - scripts/preamble.py        (_commit_all)
    - scripts/setup_project.py   (_commit_project)
    - scripts/bc_export.py       (_verify_env_excluded_from_git)
    - hooks/auto-commit-monitor.js (the ENV_REL_PATH guards)

A bug found in one copy had to be re-found in the other three. This module is
the single home: all three Python writers import `check_env_guard`; the JS
monitor invokes the `guard` CLI subcommand here via a `python3` subprocess.

The commit-author identity (`Be Civic <noreply@becivic.be>`), also duplicated
across the same writers, lives here too — `commit_identity_args()`.

Runtime: Python 3 stdlib only. No third-party deps. Never raises on git
failures (git-binary-missing / timeout / corrupt repo all degrade to a
None/false result that the caller treats as "could not commit").

The guard verdict (`check_env_guard`) is intentionally just a *classification*.
Each caller renders its own message and chooses its own failure mode — refuse +
OPERATOR_ALERT to stdout (committers), or FATAL + exit 1 (export) — so this
module imposes no I/O policy on its callers.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from enum import Enum
from pathlib import Path

# The harness key lives at this exact nested path inside the single user-owned
# repo. Every guard tests THIS path, never a root `.env`.
ENV_REL_PATH = ".be-civic/state/.env"

# The Be Civic commit author. The ONE source of truth for the identity that was
# previously hardcoded in three writers.
COMMIT_AUTHOR_NAME = "Be Civic"
COMMIT_AUTHOR_EMAIL = "noreply@becivic.be"


class GuardVerdict(str, Enum):
    """The classification a guard check returns. `str` mixin so it serialises to
    a stable token for the CLI / JS-subprocess boundary."""

    OK = "ok"                  # safe to commit — .env absent, or ignored & untracked
    NOT_A_REPO = "not-a-repo"  # path is not a git work tree (or git unavailable)
    NOT_IGNORED = "not-ignored"  # .env present but NOT gitignored — committing would leak it
    TRACKED = "tracked"        # .env already tracked by git (a prior leak) — refuse regardless


# ── git plumbing ─────────────────────────────────────────────────────────────

def git_in(repo: Path, args: list[str], timeout: float = 10.0):
    """Run a git command inside `repo`. Returns the CompletedProcess, or None if
    the git binary is missing / the call times out. Never raises."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def is_git_repo(repo: Path) -> bool:
    res = git_in(repo, ["rev-parse", "--is-inside-work-tree"])
    return bool(res and res.returncode == 0 and res.stdout.strip() == "true")


def count_staged(porcelain: str) -> int:
    """Count entries staged in the index from `git status --porcelain` output."""
    n = 0
    for line in porcelain.splitlines():
        if not line:
            continue
        index_status = line[0]
        if index_status not in (" ", "?"):
            n += 1
    return n


# ── the guard ────────────────────────────────────────────────────────────────

def env_path_in(repo: Path) -> Path:
    """The absolute on-disk path of the harness key inside `repo`."""
    return repo / ".be-civic" / "state" / ".env"


def check_env_guard(repo: Path) -> GuardVerdict:
    """Classify whether `repo` is safe to commit w.r.t. the harness key.

    - `.env` absent on disk → OK (nothing to protect; `add -A` cannot stage it).
    - `.env` present but NOT gitignored → NOT_IGNORED (a plain `add -A` would
      stage and leak it). `check-ignore -q -- <path>` exits 0 iff ignored; any
      non-zero (not-ignored OR git error) is treated as not-ignored — fail safe.
    - `.env` already tracked by git → TRACKED (a prior leak); refuse regardless
      of check-ignore, since the leak is already in the index/history.
    - not a git work tree → NOT_A_REPO (caller decides whether that is benign).

    Pure classification. Never raises, never prints.
    """
    if not is_git_repo(repo):
        return GuardVerdict.NOT_A_REPO

    if env_path_in(repo).exists():
        chk = git_in(repo, ["check-ignore", "-q", "--", ENV_REL_PATH])
        if not chk or chk.returncode != 0:
            return GuardVerdict.NOT_IGNORED

    tracked = git_in(repo, ["ls-files", "--", ENV_REL_PATH])
    if tracked and tracked.returncode == 0 and tracked.stdout.strip():
        return GuardVerdict.TRACKED

    return GuardVerdict.OK


def is_env_tracked(repo: Path) -> bool:
    """Narrow guard for the export path: True iff the harness key is tracked by
    git (i.e. would land in a `git bundle --all`). Unlike `check_env_guard`,
    a present-but-unignored-yet-untracked .env is NOT a problem here — a bundle
    of committed history excludes it. Never raises."""
    if not env_path_in(repo).exists():
        return False
    tracked = git_in(repo, ["ls-files", "--", ENV_REL_PATH])
    return bool(tracked and tracked.returncode == 0 and tracked.stdout.strip())


# ── commit identity ──────────────────────────────────────────────────────────

def commit_identity_args() -> list[str]:
    """The git args that stamp the Be Civic author on a commit. Used as:
        git -C <repo> <commit_identity_args()> commit -m <msg>
    Covers both the committer (`-c user.name/email`) and the author
    (`--author`) so neither falls back to the operator's global identity."""
    return [
        "-c", f"user.name={COMMIT_AUTHOR_NAME}",
        "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
    ]


def author_arg() -> str:
    """`Name <email>` for `--author`."""
    return f"{COMMIT_AUTHOR_NAME} <{COMMIT_AUTHOR_EMAIL}>"


# ── CLI (invoked by hooks/auto-commit-monitor.js via a python3 subprocess) ────

def _cli_guard(repo: Path) -> int:
    """Print the guard verdict token to stdout and exit 0. The JS monitor reads
    the single token line and maps it to its own skip reasons.

        ok | not-a-repo | not-ignored | tracked
    """
    verdict = check_env_guard(repo)
    print(verdict.value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="env_guard.py",
        description="Be Civic harness-key commit guard (single source of truth).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser(
        "guard",
        help="Print the env-guard verdict for a repo (ok/not-a-repo/not-ignored/tracked).",
    )
    g.add_argument("repo", help="path to the project repo to check")

    args = parser.parse_args(argv)
    if args.command == "guard":
        return _cli_guard(Path(args.repo))
    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable; parser.error exits


if __name__ == "__main__":
    sys.exit(main())
