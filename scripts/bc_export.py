#!/usr/bin/env python3
"""bc_export.py — Be Civic portable-archive exporter (W33.4h).

Bundles both substrate surfaces (visible SUBSTRATE_DATA + hidden SUBSTRATE_STATE)
into a single tarball that can be restored on another machine via bc_import.py.

Bundle format
─────────────
  bc-export-<timestamp>.tar.gz
  ├── manifest.json          # version markers + path metadata
  ├── surfaces/
  │   ├── data.bundle        # git bundle of the visible surface (SUBSTRATE_DATA)
  │   └── state.bundle       # git bundle of the hidden surface (SUBSTRATE_STATE)

IDENTITY HANDLING (40-substrate §6.1 / W33 migration contract §1)
────────────────────────────────────────────────────────────────────
The hidden surface's .env file (harness_key = Identity) is gitignored by the
hidden surface's .gitignore allowlist. It is NOT in the committed git history.
A `git bundle` of committed history NATURALLY EXCLUDES .env — this script
verifies that property before proceeding and prints an explicit warning.

On the destination machine the user must re-verify via POST /api/auth/verify
(or rotate an existing key via POST /api/auth/rotate-key) to get a working
harness key. Identity is not portable; the bundle is safe to copy.

Usage
──────
  python3 bc_export.py --data <SUBSTRATE_DATA_PATH> \\
                       --state <SUBSTRATE_STATE_PATH> \\
                       --out <destination_directory_or_path.tar.gz>

  # With Cowork env vars:
  python3 bc_export.py --cowork --out ~/Desktop

  # Dry-run (verify surfaces, no file written):
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

def _verify_env_excluded_from_git(surface_root: Path, label: str) -> None:
    """Abort if .env is tracked by git — that would mean Identity is in history.

    This is a safety-net assertion, not a configuration choice. If it ever
    fires it means the hidden surface's .gitignore allowlist was corrupted.
    """
    git_dir = surface_root / ".git"
    if not git_dir.exists():
        return  # no git repo; not a problem at verification stage

    env_path = surface_root / ".env"
    if not env_path.exists():
        return  # no .env present at all

    result = subprocess.run(
        ["git", "-C", str(surface_root), "ls-files", ".env"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and ".env" in result.stdout:
        print(
            f"FATAL: .env is tracked by git in the {label} surface.\n"
            "This means Identity (the harness key) is in version-control history\n"
            "and would be included in the git bundle. Aborting export.\n"
            "Fix: add .env to the .gitignore allowlist and rewrite history.",
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

def _read_version_json(state_root: Path) -> dict:
    """Read version.json from the hidden surface."""
    vpath = state_root / "version.json"
    if vpath.exists():
        try:
            return json.loads(vpath.read_text())
        except Exception:
            pass
    return {}


# ── Main export logic ─────────────────────────────────────────────────────────

def export(data_path: Path, state_path: Path, out: Path, dry_run: bool) -> None:
    """Bundle both surfaces into a portable tarball."""

    # ── 0. Sanity checks ─────────────────────────────────────────────────────
    if not data_path.exists():
        print(f"ERROR: SUBSTRATE_DATA path does not exist: {data_path}", file=sys.stderr)
        sys.exit(1)
    if not state_path.exists():
        print(f"ERROR: SUBSTRATE_STATE path does not exist: {state_path}", file=sys.stderr)
        sys.exit(1)

    # ── 1. Verify Identity is excluded from git (safety assertion) ───────────
    _verify_env_excluded_from_git(state_path, "hidden (SUBSTRATE_STATE)")

    version_info = _read_version_json(state_path)

    if dry_run:
        print("DRY RUN — no file will be written.")
        print(f"  SUBSTRATE_DATA  : {data_path}")
        print(f"  SUBSTRATE_STATE : {state_path}")
        print(f"  version.json    : {version_info}")
        env_present = (state_path / ".env").exists()
        print(f"  .env present    : {env_present} (EXCLUDED from bundle — Identity stays on this machine)")
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

        data_bundle_path = surfaces_dir / "data.bundle"
        state_bundle_path = surfaces_dir / "state.bundle"

        data_has_commits = _create_git_bundle(data_path, data_bundle_path, "visible (SUBSTRATE_DATA)")
        state_has_commits = _create_git_bundle(state_path, state_bundle_path, "hidden (SUBSTRATE_STATE)")

        # ── 4. Write manifest ─────────────────────────────────────────────────
        manifest = {
            "bc_export_version": "1",
            "exported_at": ts,
            "state_version": version_info.get("state_version", "unknown"),
            "plugin_version": version_info.get("plugin_version", "unknown"),
            "data_bundle_present": data_has_commits,
            "state_bundle_present": state_has_commits,
            "identity_excluded": True,
            "note": (
                "Identity (harness_key in .env) is NOT in this bundle. "
                "On the destination machine, re-verify via POST /api/auth/verify "
                "or rotate via POST /api/auth/rotate-key."
            ),
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # ── 5. Pack the tarball ────────────────────────────────────────────────
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_path / "manifest.json", arcname="manifest.json")
            for name in ["data.bundle", "state.bundle"]:
                p = surfaces_dir / name
                if p.exists():
                    tar.add(p, arcname=f"surfaces/{name}")

    # ── 6. USER-FACING WARNING (mandatory per 40-substrate §9.1 step 3) ──────
    print()
    print("=" * 68)
    print("IDENTITY WARNING")
    print("=" * 68)
    print()
    print("Your harness key (.env / BECIVIC_HARNESS_KEY) is NOT included in")
    print("this bundle. Identity stays on THIS machine only.")
    print()
    print("On the destination machine you will need to re-verify your email")
    print("via the Be Civic onboarding flow, or rotate your existing key:")
    print()
    print("  POST /api/auth/verify       (new machine, fresh verification)")
    print("  POST /api/auth/rotate-key   (rotates to a new key, same user ID)")
    print()
    print("The bundle is safe to copy or share — it contains no credentials.")
    print("Your data (profile, events, procedures, documents) IS included.")
    print()
    print("=" * 68)
    print()
    print(f"Bundle written to: {archive_path}")
    print(f"  state_version : {manifest['state_version']}")
    print(f"  exported_at   : {ts}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _resolve_cowork_paths() -> tuple[Path, Path]:
    """Read Cowork env vars and the .be-civic/marker to locate both surfaces."""
    state_env = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not state_env:
        print(
            "ERROR: CLAUDE_PLUGIN_DATA not set. "
            "Either pass --data/--state explicitly or run inside Cowork.",
            file=sys.stderr,
        )
        sys.exit(1)
    state_path = Path(state_env)

    # Resolve visible surface from the marker pointer.
    marker_path = state_path / ".be-civic" / "marker"
    if not marker_path.exists():
        print(
            f"ERROR: Marker not found at {marker_path}.\n"
            "The Be Civic project has not been onboarded yet. "
            "Complete first-contact onboarding before exporting.",
            file=sys.stderr,
        )
        sys.exit(1)

    marker_content = marker_path.read_text().strip()
    # Marker format per 51-cowork: either a raw path or a JSON {"visible_path": "..."}
    try:
        meta = json.loads(marker_content)
        data_path = Path(meta["visible_path"])
    except (json.JSONDecodeError, KeyError):
        data_path = Path(marker_content)

    return data_path, state_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="bc_export — bundle a Be Civic substrate for cross-machine portability"
    )
    path_group = parser.add_mutually_exclusive_group(required=True)
    path_group.add_argument(
        "--cowork",
        action="store_true",
        help="resolve paths from CLAUDE_PLUGIN_DATA env var (Cowork plugin runtime)",
    )
    path_group.add_argument(
        "--data",
        type=Path,
        metavar="SUBSTRATE_DATA",
        help="path to the visible surface (user-picked BeCivic folder)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        metavar="SUBSTRATE_STATE",
        help="path to the hidden surface (required with --data)",
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
        help="verify surfaces and print what would be exported; do not write the archive",
    )
    args = parser.parse_args(argv)

    if args.cowork:
        data_path, state_path = _resolve_cowork_paths()
    else:
        if not args.state:
            parser.error("--state is required when --data is given")
        data_path = args.data
        state_path = args.state

    export(data_path, state_path, args.out, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
