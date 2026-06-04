#!/usr/bin/env python3
"""bc_import.py — Be Civic portable-archive importer.

Validates and restores a bc_export bundle into the ONE durable project folder
on the destination machine. State lives at the `.be-civic/state/` subtree inside
that folder, so restoring the single `git bundle --all` brings back everything
committed (visible prose + state) in one shot.

By default a bundle carries the user's Identity (the harness key), so after
activation the user is fully active: profile, events, procedures, documents,
AND the key are all restored. If the bundle was exported without a key
(anonymous-tier), the session-start preamble detects the missing key and
routes through bc-onboarding's verify branch.

Import sequence
────────────────
  1. Receive     — user passes the .tar.gz archive path
  2. Probe       — read manifest.json; check state_version vs receiving plugin
  3. Stage       — unpack to a temp dir (NOT the live folder)
  4. Verify      — confirm surfaces/becivic.bundle present; validate integrity
  5. Reconcile   — if existing state is present in the folder → prompt
  6. Activate    — restore the git repo + checkout at the destination folder,
                   write the detection-only marker, restore the loose key

NO BACKWARD-COMPAT: greenfield — no active users. This importer ONLY reads the
single-surface bundle format (surfaces/becivic.bundle). The old two-surface
format (data.bundle + state.bundle) is not supported.

Usage
──────
  python3 bc_import.py <bundle.tar.gz> --data <destination_BeCivic_folder>

  # With Cowork (BeCivic/ created inside the picked parent):
  python3 bc_import.py <bundle.tar.gz> --cowork --data-parent ~/Documents

  # Dry-run (validate only, do not write):
  python3 bc_import.py <bundle.tar.gz> --data ~/BeCivic --dry-run

Runtime: Python 3 stdlib only. No third-party deps.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


# ── Plugin version — must match plugin.json / version.json ──────────────────
PLUGIN_VERSION = "0.7.0"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _semver_tuple(v: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z' → (X, Y, Z). Non-numeric parts → 0."""
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0, 0, 0)


def _git_bundle_verify(bundle_path: Path) -> bool:
    """Return True if the git bundle is readable.

    Uses `git bundle list-heads` which works without a repo context (unlike
    `git bundle verify` which requires being inside an existing git repo).
    list-heads parses the bundle header and fails on corrupt/invalid bundles.
    """
    r = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle_path)],
        capture_output=True,
        text=True,
    )
    # A valid bundle emits at least one ref line.
    return r.returncode == 0 and bool(r.stdout.strip())


def _restore_bundle(bundle_path: Path, dest: Path, label: str) -> bool:
    """Initialise dest as a git repo and unpack the bundle into it.

    Returns True on success, False on failure (with error to stderr).
    """
    dest.mkdir(parents=True, exist_ok=True)

    # Init bare repo in dest if not already a git repo.
    if not (dest / ".git").exists():
        r = subprocess.run(
            ["git", "-C", str(dest), "init"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"ERROR: git init failed for {label}: {r.stderr}", file=sys.stderr)
            return False

    # Fetch all refs from the bundle.
    r = subprocess.run(
        ["git", "-C", str(dest), "fetch", str(bundle_path), "refs/heads/*:refs/heads/*",
         "--update-head-ok"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"ERROR: git fetch from bundle failed for {label}: {r.stderr}", file=sys.stderr)
        return False

    # Determine default branch name and check it out.
    r_branch = subprocess.run(
        ["git", "-C", str(dest), "bundle", "list-heads", str(bundle_path)],
        capture_output=True,
        text=True,
    )
    # Pick main or master; fall back to the first listed branch.
    branch = "main"
    if r_branch.returncode == 0:
        lines = [l.strip() for l in r_branch.stdout.splitlines() if l.strip()]
        for line in lines:
            ref = line.split()[-1] if line.split() else ""
            if ref.endswith("main"):
                branch = "main"
                break
            elif ref.endswith("master"):
                branch = "master"
                break
        else:
            if lines:
                # Take whatever the first branch is.
                parts = lines[0].split()
                if len(parts) >= 2:
                    branch = parts[-1].split("/")[-1]

    r_checkout = subprocess.run(
        ["git", "-C", str(dest), "checkout", branch],
        capture_output=True,
        text=True,
    )
    if r_checkout.returncode != 0:
        # If branch already exists as HEAD just reset.
        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", f"origin/{branch}"],
            capture_output=True,
        )

    return True


def _folder_has_existing_state(folder_path: Path) -> bool:
    """Return True if the project folder has already been initialised."""
    marker = folder_path / ".be-civic" / "marker"
    version = folder_path / ".be-civic" / "state" / "version.json"
    return marker.exists() or version.exists()


def _prompt_reconcile(label: str) -> str:
    """Prompt the user to choose merge or replace. Returns 'replace' or 'merge'."""
    print(f"\nExisting state found on {label} surface.")
    print("Choose how to proceed:")
    print("  [replace] Overwrite existing state (a timestamped backup is made first)")
    print("  [merge]   Skip this surface (keep existing; manual merge required)")
    print("  [abort]   Cancel the import entirely")
    while True:
        try:
            choice = input("Choice [replace/merge/abort]: ").strip().lower()
        except EOFError:
            choice = "abort"
        if choice in ("replace", "merge", "abort"):
            return choice
        print("  Please type replace, merge, or abort.")


# ── Core import logic ─────────────────────────────────────────────────────────

def run_import(
    archive: Path,
    data_dest: Path,
    dry_run: bool,
    non_interactive: bool = False,
) -> None:
    """Full import sequence — single project folder."""

    # ── Step 1: Receive ───────────────────────────────────────────────────────
    if not archive.exists():
        print(f"ERROR: bundle not found: {archive}", file=sys.stderr)
        sys.exit(1)
    if not tarfile.is_tarfile(archive):
        print(f"ERROR: {archive} is not a valid tar archive.", file=sys.stderr)
        sys.exit(1)

    print(f"Importing bundle: {archive}")

    with tempfile.TemporaryDirectory(prefix="bc-import-") as tmp:
        tmp_path = Path(tmp)

        # ── Step 2: Probe — extract and read manifest ─────────────────────────
        with tarfile.open(archive, "r:gz") as tar:
            # filter="data" (Python 3.12+) blocks path-traversal / absolute-path
            # members in a crafted bundle; fall back gracefully on older Python.
            try:
                tar.extractall(tmp_path, filter="data")
            except TypeError:
                tar.extractall(tmp_path)

        manifest_path = tmp_path / "manifest.json"
        if not manifest_path.exists():
            print(
                "ERROR: Bundle is missing manifest.json. This archive was not created by\n"
                "bc_export.py or has been corrupted.",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as e:
            print(f"ERROR: manifest.json is not valid JSON: {e}", file=sys.stderr)
            sys.exit(1)

        bc_export_version = manifest.get("bc_export_version", "0")
        bundle_state_version = manifest.get("state_version", "unknown")
        bundle_plugin_version = manifest.get("plugin_version", "unknown")
        exported_at = manifest.get("exported_at", "unknown")
        identity_excluded = manifest.get("identity_excluded", True)

        print(f"  Exported at     : {exported_at}")
        print(f"  state_version   : {bundle_state_version}")
        print(f"  plugin_version  : {bundle_plugin_version}")
        print(f"  Identity in bundle: {not identity_excluded}")

        # Version gate: refuse bundles newer than receiving plugin.
        if (bundle_state_version != "unknown"
                and _semver_tuple(bundle_state_version) > _semver_tuple(PLUGIN_VERSION)):
            print(
                f"\nERROR: Bundle state_version ({bundle_state_version}) is newer than\n"
                f"this plugin ({PLUGIN_VERSION}). Upgrade the Be Civic plugin on this\n"
                "machine first, then retry the import.",
                file=sys.stderr,
            )
            sys.exit(1)

        # ── Step 3: Stage — locate the single bundle ──────────────────────────
        surfaces_dir = tmp_path / "surfaces"
        becivic_bundle = surfaces_dir / "becivic.bundle"

        # ── Step 4: Verify — git bundle verify ────────────────────────────────
        print("\nVerifying bundle integrity...")
        if not becivic_bundle.exists():
            print(
                "ERROR: surfaces/becivic.bundle is missing from the archive.\n"
                "This importer only reads the single-surface bundle format. The "
                "old two-surface format (data.bundle + state.bundle) is not "
                "supported.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not _git_bundle_verify(becivic_bundle):
            print("ERROR: surfaces/becivic.bundle failed git bundle verify.", file=sys.stderr)
            sys.exit(1)
        print("  becivic.bundle : OK")

        if dry_run:
            print("\nDRY RUN — verification passed. No files will be written.")
            print(f"  Would restore project folder to : {data_dest}")
            _print_post_import_guidance(not identity_excluded)
            return

        # ── Step 5: Reconcile — check for existing state ──────────────────────
        if _folder_has_existing_state(data_dest):
            label = "project (SUBSTRATE_DATA)"
            if non_interactive:
                print(
                    f"WARNING: Existing state in the folder at {data_dest}.\n"
                    "Non-interactive mode: skipping (existing state preserved).",
                    file=sys.stderr,
                )
                print("Import skipped.")
                return
            choice = _prompt_reconcile(label)
            if choice == "abort":
                print("Import aborted by user.")
                sys.exit(0)
            elif choice == "merge":
                print(f"  Skipping {label} (keeping existing state).")
                print("Import skipped.")
                return
            # replace: fall through to restore

        # ── Step 6: Activate — restore the single bundle ──────────────────────
        print("\nActivating...")

        data_ok = _restore_bundle(becivic_bundle, data_dest, "project (SUBSTRATE_DATA)")
        if not data_ok:
            print(
                "\nERROR: The project folder failed to restore. "
                "Check errors above and retry.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Write the detection-only .be-civic/marker at the folder root (no
        # hidden-path pointer field — state is a known child of the folder).
        _write_marker(data_dest)

        # Restore Identity (the harness key) if the bundle carried it. .env is
        # gitignored at .be-civic/state/.env, so the monitor never commits it.
        identity_src = tmp_path / "identity" / "env"
        if identity_src.exists():
            env_dest = data_dest / ".be-civic" / "state" / ".env"
            env_dest.parent.mkdir(parents=True, exist_ok=True)
            env_dest.write_bytes(identity_src.read_bytes())

        print("\nImport complete.")
        _print_post_import_guidance(not identity_excluded)


def _write_marker(data_dest: Path) -> None:
    """Write the detection-only .be-civic/marker at the project-folder root.

    The marker is detection-only — it carries no hidden-path pointer (state is a
    known child of the folder). Idempotent: leave an existing marker in place
    (it carries the user_id / version stamp written at onboarding)."""
    marker_dir = data_dest / ".be-civic"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "marker"
    if not marker_path.exists():
        marker_path.write_text(f"be-civic-v{PLUGIN_VERSION}\n")


def _print_post_import_guidance(identity_in_bundle: bool) -> None:
    print()
    print("=" * 68)
    if identity_in_bundle:
        print("READY — your identity was restored")
        print("=" * 68)
        print()
        print("Your harness key, profile, procedures, and documents are all in")
        print("place. Open Be Civic on this machine and pick up where you left")
        print("off — no re-verification needed.")
        print()
        print("If you exported this to move between machines, delete the bundle")
        print("file now: it contains your key. If the key was rotated or revoked")
        print("since export, the preamble will surface an auth error — re-verify")
        print("or rotate to get a fresh one.")
    else:
        print("NEXT STEP — verify your identity")
        print("=" * 68)
        print()
        print("This bundle carried your data but no harness key. To activate:")
        print("open Be Civic — the gate detects the imported state and routes")
        print("you to verification. Enter your email and paste the magic link.")
    print()
    print("=" * 68)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="bc_import — restore a Be Civic substrate bundle on this machine"
    )
    parser.add_argument("bundle", type=Path, help="path to the .tar.gz bundle from bc_export")

    # The destination is the ONE project folder. State (.be-civic/state/) is a
    # child of it — it is derived, never passed separately.
    parser.add_argument(
        "--data",
        type=Path,
        metavar="SUBSTRATE_DATA",
        help="destination project folder (restored in place).",
    )
    parser.add_argument(
        "--cowork",
        action="store_true",
        help="Cowork runtime: pair with --data-parent to create BeCivic/ inside the parent",
    )
    parser.add_argument(
        "--data-parent",
        type=Path,
        metavar="PARENT",
        help="parent directory; a BeCivic/ subfolder is created inside it (the project folder)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the bundle without writing to disk",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="skip reconciliation prompts (skip rather than replace on conflict)",
    )

    args = parser.parse_args(argv)

    # Resolve the single project-folder destination.
    if args.data:
        data_dest = args.data
    elif args.data_parent:
        data_dest = args.data_parent / "BeCivic"
    else:
        parser.error("provide --data <folder> or --data-parent <parent> for the project folder")
        return 1  # unreachable

    run_import(
        archive=args.bundle,
        data_dest=data_dest,
        dry_run=args.dry_run,
        non_interactive=args.non_interactive,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
