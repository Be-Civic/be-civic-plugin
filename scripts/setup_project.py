#!/usr/bin/env python3
"""setup_project.py — Be Civic one-call onboarding project write.

Collapses the entire `bc-onboarding` §6 "state-shape activation" sequence — git
init, `.gitignore`, the five `.be-civic/state/` files, the marker, `CLAUDE.md`,
`MEMORY.md`, and the first commit — into ONE deterministic call the onboarding
agent makes after the folder picker returns.

`CLAUDE.md` is written byte-for-byte from the canonical `harness-CLAUDE.md`
template — NO `## Carry-over` block is appended. The carry-over (chosen procedure
+ conversation language) lives in the state files this script writes — the
`procedures.json` registry and `preferences.json` — which the preamble reads as
CARRYOVER_PROCEDURE / CARRYOVER_LANG. The prose block was redundant with that
state AND mutated the always-on harness, breaking the byte-identical-to-canonical
fidelity the JIT instruction-surface doctrine depends on.

Why a script instead of ~12 agent tool calls:
  - The agent previously `cp`-copied the read-only `harness-CLAUDE.md` template,
    which hardlinked it read-only, so writes against the destination failed with
    EPERM/EACCES. Every "copy verbatim" here is `read_text` → `_write` (FRESH
    bytes), so the destination is a new, writable inode — the hardlink bug cannot
    recur.
  - One call instead of ~12 round-trips; no char-by-char `CLAUDE.md` write.
  - Idempotent + re-run-safe, so partial-crash recovery is a single re-invocation.

The harness key is read from STDIN (`--key-stdin`) or a `--key-file` — NEVER from
argv (process-table / shell-history exposure). It is validated, written to
`.be-civic/state/.env`, and never echoed on stdout.

Output: `KEY: VALUE` lines for the calling agent to parse (mirrors preamble.py).
The agent proceeds on `SETUP_RESULT: ok` + a non-`none` `COMMIT_SHA` — it does
not need to Read any written file back.

Runtime: Python 3 stdlib only. Cross-platform: macOS, Windows (native), Linux.
Time budget: <500ms (all local; a few git subprocesses; no network).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# The harness-key commit guard + commit identity live in ONE module beside this
# script (scripts/env_guard.py). Ensure that dir is importable when this runs as
# a standalone script (`python3 scripts/setup_project.py`).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import env_guard
from env_guard import (
    GuardVerdict,
    count_staged as _count_staged,
    git_in as _git,
    is_git_repo as _is_git_repo,
)


# ============================================================================
# Constants
# ============================================================================

SCRIPTS_DIR = Path(__file__).resolve().parent

# Default plugin version stamped into the marker (matches plugin.json /
# preamble.py PLUGIN_VERSION_STRING). Overridable via --plugin-version.
PLUGIN_VERSION_STRING = "0.8.0"

# Template locations relative to ${SUBSTRATE_ROOT} (the plugin install dir).
GITIGNORE_REL = "data/gitignore.txt"
PROFILE_TEMPLATE_REL = "skills/bc-onboarding/references/project-init/profile.json"
MEMORY_TEMPLATE_REL = "skills/bc-onboarding/references/project-init/MEMORY.md"
MARKER_TEMPLATE_REL = "skills/bc-onboarding/references/project-init/.be-civic/marker"
HARNESS_TEMPLATE_REL = "skills/bc-onboarding/references/harness-CLAUDE.md"

COMMIT_MESSAGE = "chore: initialise Be Civic project (onboarding setup)"


def _now() -> str:
    """RFC3339 UTC timestamp, matching preamble.py's format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ============================================================================
# git helpers + the harness-key guard now live in the single guard module
# (scripts/env_guard.py): _git / _is_git_repo / _count_staged are imported at
# the top of this file, and _commit_project calls env_guard.check_env_guard.
# ============================================================================


# ============================================================================
# Write helper — the core fix: fresh bytes, utf-8, LF
# ============================================================================

def _write(path: Path, text: str) -> None:
    """Write `text` as FRESH bytes (never shutil.copy → never a hardlink that
    inherits a read-only template's mode), forcing utf-8 + LF newlines so a
    CRLF-checked-out template can't poison the output on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def _read_template(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


# ============================================================================
# Builders for the generated files
# ============================================================================

def _fill_marker(template: str, user_id: str, plugin_version: str, created_at: str) -> str:
    """Line-anchored placeholder fill (not blind str.replace, so a stray
    placeholder substring elsewhere can't be hit)."""
    out = []
    for line in template.split("\n"):
        if line.startswith("user_id="):
            out.append(f"user_id={user_id}")
        elif line.startswith("plugin_version="):
            out.append(f"plugin_version={plugin_version}")
        elif line.startswith("created_at="):
            out.append(f"created_at={created_at}")
        else:
            out.append(line)
    return "\n".join(out)


def _procedures_seed(slug: str, process_id: str, process_version: str,
                     status: str, now: str, process_title: str = "") -> str:
    entry = {
        "slug": slug,
        "process_id": process_id,
        "process_version": process_version,
        "status": status,
        "started_at": now,
        "updated_at": now,
    }
    # process_title is OPTIONAL in the registry schema: include it only when a
    # real title was passed (never an empty string — the schema requires
    # minLength 1, and a missing field is the valid legacy/`intake` shape that
    # readers fall back to the slug for). Inserted after process_id to mirror
    # the schema property order.
    title = (process_title or "").strip()
    if title:
        ordered = {}
        for k, v in entry.items():
            ordered[k] = v
            if k == "process_id":
                ordered["process_title"] = title
        entry = ordered
    registry = {
        "schema_version": 1,
        "procedures": [entry],
    }
    return json.dumps(registry, indent=2) + "\n"


# ============================================================================
# The project-write commit (the harness-key guard is env_guard.check_env_guard)
# ============================================================================

def _commit_project(repo: Path) -> tuple[str | None, int]:
    """`git add -A` then commit `repo` with the Be Civic author. Returns
    (commit_sha, files_committed). Refuses (returns (None, 0) after an
    OPERATOR_ALERT) if `.be-civic/state/.env` would be tracked — protecting the
    harness key, exactly as preamble.py does. Never raises."""
    if not _is_git_repo(repo):
        return None, 0
    # Harness-key guard — single source of truth: env_guard.check_env_guard.
    verdict = env_guard.check_env_guard(repo)
    if verdict is GuardVerdict.NOT_IGNORED:
        print(
            f"OPERATOR_ALERT: {env_guard.ENV_REL_PATH} present but not gitignored "
            f"in {repo}; refusing commit to protect Identity. "
            "Write the .gitignore allowlist first."
        )
        return None, 0
    if verdict is GuardVerdict.TRACKED:
        print(
            f"OPERATOR_ALERT: {env_guard.ENV_REL_PATH} is tracked by git in {repo}; "
            "refusing commit to protect Identity."
        )
        return None, 0
    add = _git(repo, ["add", "-A"])
    if not add or add.returncode != 0:
        return None, 0
    status = _git(repo, ["status", "--porcelain"])
    if not status or status.returncode != 0:
        return None, 0
    staged = _count_staged(status.stdout)
    if staged == 0:
        # Nothing to commit (idempotent re-run with no changes) — report the
        # existing HEAD so the caller still sees a commit sha.
        head = _git(repo, ["rev-parse", "HEAD"])
        sha = head.stdout.strip() if head and head.returncode == 0 else None
        return sha, 0
    commit = _git(
        repo,
        [
            *env_guard.commit_identity_args(),
            "commit",
            "--author", env_guard.author_arg(),
            "-m", COMMIT_MESSAGE,
        ],
    )
    if not commit or commit.returncode != 0:
        return None, 0
    head = _git(repo, ["rev-parse", "HEAD"])
    sha = head.stdout.strip() if head and head.returncode == 0 else None
    return sha, staged


# ============================================================================
# Key transport
# ============================================================================

def _read_key(args: argparse.Namespace) -> str | None:
    """Read the harness key from stdin (--key-stdin) or a --key-file. NEVER from
    argv. Returns the stripped key, or None if unreadable/empty."""
    if args.key_stdin:
        try:
            raw = sys.stdin.buffer.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        key = raw.strip()
        return key or None
    if args.key_file:
        kf = Path(args.key_file)
        try:
            key = kf.read_text(encoding="utf-8").strip()
        finally:
            # Best-effort removal of the temp key file regardless of read outcome.
            try:
                kf.unlink(missing_ok=True)
            except OSError:
                pass
        return key or None
    return None


# ============================================================================
# Orchestration
# ============================================================================

def _resolve_substrate_root(arg_root: str | None) -> Path:
    if arg_root:
        return Path(arg_root)
    return Path(os.environ.get("CLAUDE_PLUGIN_ROOT", str(SCRIPTS_DIR.parent)))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="setup_project.py — Be Civic one-call onboarding project write",
        add_help=True,
    )
    p.add_argument("--data-root", required=True, metavar="DIR",
                   help="absolute path to the user-picked PARENT folder; the "
                        "script creates DIR/BeCivic/ as ${SUBSTRATE_DATA}")
    p.add_argument("--substrate-root", default=None, metavar="DIR",
                   help="plugin install root for templates (default: "
                        "CLAUDE_PLUGIN_ROOT, then the script's parent dir)")
    p.add_argument("--user-id", required=True)
    p.add_argument("--locale", required=True)
    # --language-name and --process-title were both consumed only by the prose
    # `## Carry-over` block that used to be appended to CLAUDE.md. That block is
    # gone (the carry-over now lives in preferences.json + procedures.json, which
    # the preamble reads). --process-title is now written into the procedures.json
    # entry as the optional `process_title` field, so the first-working-session
    # load canary names the real Process title instead of the kebab-case slug.
    # --language-name remains accepted-but-unused (the conversation language lives
    # in preferences.json, keyed by --locale).
    p.add_argument("--language-name", default="",
                   help="(accepted but unused — conversation language is written "
                        "from --locale into preferences.json)")
    p.add_argument("--process-id", required=True)
    p.add_argument("--process-slug", required=True)
    p.add_argument("--process-title", default="",
                   help="human-readable Process title; written into procedures.json "
                        "as the optional `process_title` (omitted when empty) so the "
                        "load canary names the real title, not the slug")
    p.add_argument("--process-version", default="0")
    p.add_argument("--process-status", default="active")
    p.add_argument("--plugin-version", default=PLUGIN_VERSION_STRING)
    p.add_argument("--allow-nested", action="store_true",
                   help="bypass the nested-repo guard (after the agent has "
                        "confirmed with the user)")
    p.add_argument("--key-stdin", action="store_true",
                   help="read the harness key from stdin (recommended)")
    p.add_argument("--key-file", default=None, metavar="PATH",
                   help="read the harness key from a file, then unlink it "
                        "(fallback; --key-stdin preferred)")
    args, _unknown = p.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    substrate_root = _resolve_substrate_root(args.substrate_root)
    substrate_data = Path(args.data_root).resolve() / "BeCivic"
    substrate_state = substrate_data / ".be-civic" / "state"

    print(f"SUBSTRATE_DATA: {substrate_data}")
    print(f"SUBSTRATE_STATE: {substrate_state}")

    # --- Preconditions (abort BEFORE any write) -------------------------------
    key = _read_key(args)
    if not key:
        print("SETUP_RESULT: failed")
        print("SETUP_ERROR: empty_harness_key")
        return 1

    marker_path = substrate_data / ".be-civic" / "marker"
    mode = "reuse" if marker_path.exists() else "fresh"
    print(f"SETUP_MODE: {mode}")

    # Nested-repo guard: refuse if the picked parent is inside another work tree
    # and the BeCivic dir isn't already its own repo — keep the human decision
    # with the agent (it re-runs with --allow-nested on confirmation).
    parent = Path(args.data_root).resolve()
    becivic_is_repo = (substrate_data / ".git").exists()
    if not args.allow_nested and not becivic_is_repo and _is_git_repo(parent):
        print("NESTED_REPO_GUARD: tripped")
        print("SETUP_RESULT: failed")
        print("SETUP_ERROR: nested_repo_needs_confirmation")
        return 1
    print(f"NESTED_REPO_GUARD: {'bypassed' if args.allow_nested else 'clear'}")

    result = "ok"
    files_written = 0

    def step(label: str, ok: bool, detail: str = "ok") -> None:
        nonlocal result
        print(f"{label}: {detail if ok else 'failed'}")
        if not ok:
            result = "partial"

    # --- Phase A — repo + allowlist (order is load-bearing) -------------------
    try:
        substrate_data.mkdir(parents=True, exist_ok=True)
        substrate_state.mkdir(parents=True, exist_ok=True)
    except OSError:
        print("SETUP_RESULT: failed")
        print("SETUP_ERROR: cannot_create_folder")
        return 1

    # .gitignore FIRST — it is the load-bearing protection for the harness key.
    # If it cannot be written (missing template / wrong --substrate-root), ABORT
    # before writing any state: a `.env` on disk without the allowlist is an
    # unprotected key. The commit guard below would refuse the commit, but the
    # key would still be sitting in the folder for the monitor or the user to
    # stage. So fail closed here rather than continuing.
    try:
        _write(substrate_data / ".gitignore", _read_template(substrate_root, GITIGNORE_REL))
        print("GITIGNORE_WRITTEN: ok")
        files_written += 1
    except OSError as exc:
        print("GITIGNORE_WRITTEN: failed")
        print("SETUP_RESULT: failed")
        print(f"SETUP_ERROR: gitignore_write_failed_{type(exc).__name__}")
        return 1

    if becivic_is_repo:
        print("GIT_INIT: already_repo")
    else:
        init = _git(substrate_data, ["init", "-q"])
        if init is not None and init.returncode == 0:
            print("GIT_INIT: ok")
        else:
            print("GIT_INIT: failed")
            result = "partial"

    # --- Phase B — state files (§6.3 order) -----------------------------------
    now = _now()

    # .env — with identity guard: never clobber a DIFFERENT existing key.
    env_path = substrate_state / ".env"
    existing_env_differs = False
    if env_path.exists():
        try:
            existing = env_path.read_text(encoding="utf-8")
            existing_env_differs = (f"BECIVIC_HARNESS_KEY={key}" not in existing)
        except OSError:
            existing_env_differs = False
    # Identity guard applies whenever a DIFFERENT key already exists — not only
    # in `reuse` mode. A folder can carry a `.env` with no marker yet (a prior
    # run crashed mid-write → mode reads as `fresh`); guarding only on `reuse`
    # would let a new key clobber that existing identity.
    if existing_env_differs:
        print("ENV_WRITTEN: skipped_mismatch")
        print("OPERATOR_ALERT: existing .env holds a different harness key; "
              "refusing to overwrite another identity")
        result = "partial"
    else:
        try:
            _write(env_path, f"BECIVIC_HARNESS_KEY={key}\n")
            step("ENV_WRITTEN", True)
            files_written += 1
        except OSError:
            step("ENV_WRITTEN", False)

    # user-id — identity guard: refuse if a DIFFERENT id already present.
    uid_path = substrate_state / "user-id"
    if uid_path.exists():
        try:
            existing_uid = uid_path.read_text(encoding="utf-8").strip()
        except OSError:
            existing_uid = ""
        if existing_uid and existing_uid != args.user_id:
            print(f"USER_ID_WRITTEN: skipped_mismatch existing={_short_hash(existing_uid)} "
                  f"incoming={_short_hash(args.user_id)}")
            print("OPERATOR_ALERT: user_id_mismatch — folder belongs to another identity")
            result = "partial"
        else:
            print("USER_ID_WRITTEN: skipped_present")
    else:
        try:
            _write(uid_path, f"{args.user_id}\n")
            step("USER_ID_WRITTEN", True)
            files_written += 1
        except OSError:
            step("USER_ID_WRITTEN", False)

    # profile.json — verbatim template, last_updated_at stays null.
    try:
        _write(substrate_state / "profile.json", _read_template(substrate_root, PROFILE_TEMPLATE_REL))
        step("PROFILE_WRITTEN", True)
        files_written += 1
    except OSError:
        step("PROFILE_WRITTEN", False)

    # preferences.json
    try:
        _write(substrate_state / "preferences.json",
               json.dumps({"conversation_language": args.locale}, indent=2) + "\n")
        step("PREFERENCES_WRITTEN", True)
        files_written += 1
    except OSError:
        step("PREFERENCES_WRITTEN", False)

    # procedures.json — seeded registry (process_title written when non-empty)
    try:
        _write(substrate_state / "procedures.json",
               _procedures_seed(args.process_slug, args.process_id,
                                args.process_version, args.process_status, now,
                                args.process_title))
        step("PROCEDURES_WRITTEN", True)
        files_written += 1
    except OSError:
        step("PROCEDURES_WRITTEN", False)

    # .pending-verification — redundant now; remove if present.
    pending = substrate_state / ".pending-verification"
    try:
        if pending.exists():
            pending.unlink(missing_ok=True)
            print("PENDING_VERIFICATION_CLEARED: ok")
        else:
            print("PENDING_VERIFICATION_CLEARED: absent")
    except OSError:
        print("PENDING_VERIFICATION_CLEARED: failed")

    # --- Phase C — the rest of the folder (§6.4 + 6.4a) -----------------------
    # marker
    try:
        marker = _fill_marker(_read_template(substrate_root, MARKER_TEMPLATE_REL),
                              args.user_id, args.plugin_version, now)
        _write(marker_path, marker)
        step("MARKER_WRITTEN", True)
        files_written += 1
    except OSError:
        step("MARKER_WRITTEN", False)

    # CLAUDE.md = the harness template written VERBATIM as fresh bytes (never
    # cp-then-append — that hardlinked the read-only template). NO `## Carry-over`
    # block is appended: the carry-over (chosen procedure + conversation language)
    # lives in the state files written above — procedures.json (the registry) and
    # preferences.json (conversation_language) — which the preamble reads as
    # CARRYOVER_PROCEDURE / CARRYOVER_LANG. Appending a prose block to CLAUDE.md
    # was pure redundancy AND mutated the always-on harness (breaking the
    # byte-identical-to-canonical fidelity the JIT instruction-surface doctrine
    # depends on). So the written CLAUDE.md is now byte-for-byte the canonical
    # harness.
    try:
        harness = _read_template(substrate_root, HARNESS_TEMPLATE_REL)
        _write(substrate_data / "CLAUDE.md", harness)
        step("CLAUDE_MD_WRITTEN", True)
        files_written += 1
    except OSError:
        step("CLAUDE_MD_WRITTEN", False)

    # MEMORY.md — verbatim
    try:
        _write(substrate_data / "MEMORY.md", _read_template(substrate_root, MEMORY_TEMPLATE_REL))
        step("MEMORY_WRITTEN", True)
        files_written += 1
    except OSError:
        step("MEMORY_WRITTEN", False)

    print(f"FILES_WRITTEN: {files_written}")

    # --- Phase D — commit -----------------------------------------------------
    commit_sha, committed = _commit_project(substrate_data)
    print(f"COMMIT_SHA: {commit_sha if commit_sha else 'none'}")
    print(f"COMMIT_FILE_COUNT: {committed}")
    if commit_sha is None:
        result = "partial"

    # Presence only — the key value is never echoed.
    print("HARNESS_KEY: present")
    print(f"SETUP_RESULT: {result}")
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — never leak a stack trace with paths/key
        print("SETUP_RESULT: failed")
        print(f"SETUP_ERROR: unexpected_{type(exc).__name__}")
        sys.exit(1)
