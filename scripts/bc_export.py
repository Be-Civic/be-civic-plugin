#!/usr/bin/env python3
"""bc_export.py — Be Civic portable-archive exporter.

Bundles the ONE durable project repo (${SUBSTRATE_DATA}) into a single tarball
that can be restored on another machine via bc_import.py. State lives at the
`.be-civic/state/` subtree inside that repo, so a single `git bundle --all`
carries everything committed (visible prose + state).

Bundle format
─────────────
  bc-export-<timestamp>.tar.gz
  ├── manifest.json          # version markers + bundle_present flag
  └── surfaces/
      └── becivic.bundle     # git bundle --all of the project repo

IDENTITY HANDLING
─────────────────
The harness key lives at `.be-civic/state/.env` and is gitignored by the
project folder's .gitignore allowlist — it is NOT in committed git history. A
`git bundle` of committed history NATURALLY EXCLUDES it; this script verifies
that property before proceeding. When a key is present it is carried as a loose
`identity/env` file in the tarball (credential-bearing — warned below). On the
destination the user may instead re-verify via POST /api/auth/verify (or rotate
via POST /api/auth/rotate-key) to get a working key. The bundle is safe to copy.

Usage
──────
  python3 bc_export.py --data <SUBSTRATE_DATA_PATH> \\
                       --out <destination_directory_or_path.tar.gz>

  # With Cowork env vars (resolves the folder via .session-data-root, else the
  # ancestor-walk for .be-civic/marker):
  python3 bc_export.py --cowork --out ~/Desktop

  # Dry-run (verify the repo, no file written):
  python3 bc_export.py --cowork --dry-run

Runtime: Python 3 stdlib only. No third-party deps.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ── Identity-exclusion verification ─────────────────────────────────────────

ENV_REL_PATH = ".be-civic/state/.env"


def _verify_env_excluded_from_git(repo_root: Path, label: str) -> None:
    """Abort if the harness-key .env is tracked by git — that would mean Identity
    is in history. The key lives at the EXACT nested path `.be-civic/state/.env`
    inside the single project repo.

    This is a safety-net assertion, not a configuration choice. If it ever
    fires it means the folder's .gitignore allowlist was corrupted.
    """
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return  # no git repo; not a problem at verification stage

    env_path = repo_root / ".be-civic" / "state" / ".env"
    if not env_path.exists():
        return  # no .env present at all

    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--", ENV_REL_PATH],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        print(
            f"FATAL: {ENV_REL_PATH} is tracked by git in the {label} repo.\n"
            "This means Identity (the harness key) is in version-control history\n"
            "and would be included in the git bundle. Aborting export.\n"
            "Fix: add it to the .gitignore allowlist and rewrite history.",
            file=sys.stderr,
        )
        sys.exit(1)


# ── Git bundle helpers ───────────────────────────────────────────────────────

def _has_commits(surface_root: Path) -> bool:
    """Return True if the surface repo has at least one commit."""
    r = subprocess.run(
        ["git", "-C", str(surface_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
    )
    return r.returncode == 0


def _create_git_bundle(surface_root: Path, bundle_path: Path, label: str) -> bool:
    """Create a git bundle of committed history. Returns False if no commits."""
    git_dir = surface_root / ".git"
    if not git_dir.exists():
        print(
            f"WARNING: {label} surface has no git repo at {surface_root}.\n"
            "Only committed git history is portable; this surface has none.\n"
            "The export will proceed but the import will reinitialise a bare repo.",
            file=sys.stderr,
        )
        return False

    if not _has_commits(surface_root):
        print(
            f"WARNING: {label} surface at {surface_root} has no commits yet.\n"
            "The bundle will include a placeholder. Run the Be Civic session-start\n"
            "at least once to create an initial commit before exporting.",
            file=sys.stderr,
        )
        return False

    result = subprocess.run(
        ["git", "-C", str(surface_root), "bundle", "create",
         str(bundle_path), "--all"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"ERROR: git bundle failed for {label} surface:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    return True


# ── Version info ─────────────────────────────────────────────────────────────

def _read_version_json(repo_root: Path) -> dict:
    """Read version.json from the state subtree (.be-civic/state/)."""
    vpath = repo_root / ".be-civic" / "state" / "version.json"
    if vpath.exists():
        try:
            return json.loads(vpath.read_text())
        except Exception:
            pass
    return {}


# ── Main export logic ─────────────────────────────────────────────────────────

def export(data_path: Path, out: Path, dry_run: bool) -> None:
    """Bundle the single project repo into a portable tarball."""

    # ── 0. Sanity checks ─────────────────────────────────────────────────────
    if not data_path.exists():
        print(f"ERROR: SUBSTRATE_DATA path does not exist: {data_path}", file=sys.stderr)
        sys.exit(1)

    # ── 1. Verify Identity is excluded from git (safety assertion) ───────────
    _verify_env_excluded_from_git(data_path, "project (SUBSTRATE_DATA)")

    version_info = _read_version_json(data_path)
    env_file = data_path / ".be-civic" / "state" / ".env"
    env_present = env_file.exists()

    if dry_run:
        print("DRY RUN — no file will be written.")
        print(f"  SUBSTRATE_DATA  : {data_path}")
        print(f"  version.json    : {version_info}")
        if env_present:
            print("  .env (identity) : present — WILL BE INCLUDED (bundle carries your key)")
        else:
            print("  .env (identity) : absent — anonymous-tier export (no key to carry)")
        print("DRY RUN complete. Verification passed.")
        return

    # ── 2. Determine output path ─────────────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if out.is_dir():
        archive_path = out / f"bc-export-{ts}.tar.gz"
    else:
        archive_path = out

    # ── 3. Stage into a temp dir ─────────────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="bc-export-") as tmp:
        tmp_path = Path(tmp)
        surfaces_dir = tmp_path / "surfaces"
        surfaces_dir.mkdir()

        bundle_path = surfaces_dir / "becivic.bundle"
        bundle_present = _create_git_bundle(data_path, bundle_path, "project (SUBSTRATE_DATA)")

        # Identity: .env is gitignored, so it is NOT in the git bundle. Carry it
        # as a loose file so the bundle works immediately on the destination
        # machine. The user is warned below that the bundle is credential-bearing
        # and is responsible for transferring + deleting it safely.
        identity_dir = tmp_path / "identity"
        if env_present:
            identity_dir.mkdir()
            (identity_dir / "env").write_bytes(env_file.read_bytes())

        # ── 4. Write manifest ─────────────────────────────────────────────────
        manifest = {
            "bc_export_version": "2",
            "exported_at": ts,
            "state_version": version_info.get("state_version", "unknown"),
            "plugin_version": version_info.get("plugin_version", "unknown"),
            "bundle_present": bundle_present,
            "identity_excluded": not env_present,
            "note": (
                "Identity (harness key) IS included as identity/env. Treat this "
                "bundle like a password."
                if env_present else
                "No identity in this bundle (none was set). Verify on the "
                "destination via the onboarding flow."
            ),
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # ── 5. Pack the tarball ────────────────────────────────────────────────
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_path / "manifest.json", arcname="manifest.json")
            if bundle_path.exists():
                tar.add(bundle_path, arcname="surfaces/becivic.bundle")
            if env_present:
                tar.add(identity_dir / "env", arcname="identity/env")

    # ── 6. USER-FACING WARNING ────────────────────────────────────────────────
    print()
    print("=" * 68)
    if env_present:
        print("IDENTITY INCLUDED — TREAT THIS BUNDLE LIKE A PASSWORD")
        print("=" * 68)
        print()
        print("This bundle CONTAINS your Be Civic identity (your harness key), so")
        print("it works the moment you import it on another machine — no re-")
        print("verification needed.")
        print()
        print("Anyone who has this file can act as you on Be Civic. It's yours to")
        print("look after:")
        print("  - Move it over a channel you trust (not a public link/upload).")
        print("  - Delete it once you've imported it on the new machine.")
        print("  - If it leaks, rotate your key from any active session.")
        print()
        print("Your data (profile, events, procedures, documents) is included too.")
    else:
        print("NO IDENTITY IN THIS BUNDLE")
        print("=" * 68)
        print()
        print("No harness key was set, so this bundle carries only your data")
        print("(profile, events, procedures, documents). On the destination")
        print("machine, verify via the onboarding flow to get a key.")
    print()
    print("=" * 68)
    print()
    print(f"Bundle written to: {archive_path}")
    print(f"  state_version : {manifest['state_version']}")
    print(f"  exported_at   : {ts}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _resolve_cowork_data_path() -> Path:
    """Locate the single project folder (${SUBSTRATE_DATA}) under Cowork.

    Resolution order:
      1. The preamble→monitor pointer ${CLAUDE_PLUGIN_DATA}/.session-data-root
         (line 1 = absolute path to the folder).
      2. Ancestor-walk from cwd for a `.be-civic/marker` (cap 12 levels).
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        pointer = Path(plugin_data) / ".session-data-root"
        try:
            first = pointer.read_text(encoding="utf-8").split("\n")[0].strip()
        except OSError:
            first = ""
        if first and Path(first).is_dir():
            return Path(first)

    # Fallback: ancestor-walk from cwd for the detection marker.
    try:
        current = Path.cwd().resolve()
    except OSError:
        current = None
    if current is not None:
        for _ in range(13):
            if (current / ".be-civic" / "marker").is_file():
                return current
            if current.parent == current:
                break
            current = current.parent

    print(
        "ERROR: Could not locate the Be Civic project folder. No "
        "${CLAUDE_PLUGIN_DATA}/.session-data-root pointer and no .be-civic/marker\n"
        "found by walking up from the current directory. Pass --data explicitly, "
        "or run inside an onboarded Be Civic session.",
        file=sys.stderr,
    )
    sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="bc_export — bundle a Be Civic substrate for cross-machine portability"
    )
    path_group = parser.add_mutually_exclusive_group(required=True)
    path_group.add_argument(
        "--cowork",
        action="store_true",
        help="resolve the project folder from .session-data-root / .be-civic/marker (Cowork runtime)",
    )
    path_group.add_argument(
        "--data",
        type=Path,
        metavar="SUBSTRATE_DATA",
        help="path to the project folder (user-picked BeCivic folder)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "Desktop",
        help="destination directory or .tar.gz path (default: ~/Desktop)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="verify the repo and print what would be exported; do not write the archive",
    )
    args = parser.parse_args(argv)

    if args.cowork:
        data_path = _resolve_cowork_data_path()
    else:
        data_path = args.data

    export(data_path, args.out, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
