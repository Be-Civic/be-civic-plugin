#!/usr/bin/env python3
"""preamble.py — Be Civic session-start orchestrator.

Runs every session-start check in dependency order and emits one combined
stream of `KEY: VALUE` lines on stdout for CLAUDE.md to parse into session
state.

This file is deliberately split into two clearly-bandered halves:

  ┌─ SUBSTRATE MECHANISM ────────────────────────────────────────────────────┐
  │ Filesystem + git + state-graph plumbing that must run regardless of what  │
  │ the agent does this session: writable check, surface-path resolution,     │
  │ schema-migration runner, recovery sweep, procedures.json registry         │
  │ migration. Touches disk; emits a few operator/diagnostic markers.         │
  └───────────────────────────────────────────────────────────────────────────┘
  ┌─ HARNESS BEHAVIOUR ──────────────────────────────────────────────────────┐
  │ What gets surfaced into the agent's first turn: session id, the           │
  │ session-start scans (orphan buffers, pending state), pending-verification │
  │ surfacing, the capability probes (browser/vision/MCP-fallback + the       │
  │ scrub-rules freshness that gates observation submission), and the inline  │
  │ profile.json.                                                             │
  └───────────────────────────────────────────────────────────────────────────┘

Surfaces:
  SUBSTRATE_DATA  = the ONE durable surface — the user-picked BeCivic folder,
                    resolved via `--data-root` or an ancestor-walk for
                    `.be-civic/marker`. Absent pre-onboarding / in the dev loop.
  SUBSTRATE_STATE = ${SUBSTRATE_DATA}/.be-civic/state — a pure child of the
                    folder (NOT ${CLAUDE_PLUGIN_DATA}; that surface is
                    structurally non-persistent on Cowork — bug #51398).
  SUBSTRATE_ROOT  = ${CLAUDE_PLUGIN_ROOT}    — read-only install.

Failure semantics: when SUBSTRATE_DATA is absent (pre-onboarding / dev loop),
emit absent surfaces, skip every disk sweep, and exit 0 — no hard-fail. When it
is present but the state dir is not writable, emit `SUBSTRATE_WRITABLE: no` and
continue (non-fatal). On any sub-script error, emit a `<NAME>: probe_failed`
marker and continue. The schema-migration runner restores the state subtree from
git history on failure and emits a single silent operator-alert line. If the
orchestrator itself crashes, emit JIT_FALLBACK so CLAUDE.md discovers
capabilities just-in-time.

Runtime: Python 3 stdlib only. No third-party dependencies.
Cross-platform: macOS, Windows (native, not WSL), Linux.
Total time budget: <500ms (all local; no network).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path


# ============================================================================
# Shared constants + path resolution
# ============================================================================

SCRIPTS_DIR = Path(__file__).resolve().parent

# CURRENT_SCHEMA_VERSION is the substrate schema version THIS plugin build
# targets (matches the `plugin_version` field in version.json, as an integer).
# The migration runner compares it to the on-disk `state_version` in
# version.json and applies the ordered steps in MIGRATION_STEPS between them.
# Bump this whenever a new migration step is added below.
CURRENT_SCHEMA_VERSION = 1

# Plugin version string for provenance in version.json (matches plugin.json).
PLUGIN_VERSION_STRING = "0.8.0"

# How far up the directory tree the ancestor-walk looks for `.be-civic/marker`.
MARKER_WALK_CAP = 12

# State-surface files the recovery sweep / monitor commit. Identity files
# (.env, user-id is allowlisted but harness_key in .env is not) are governed by
# the on-disk .gitignore allowlist, not this list — we only ever `git add -A`.


def _resolve_substrate_root() -> Path:
    """SUBSTRATE_ROOT = read-only plugin install dir (${CLAUDE_PLUGIN_ROOT}).

    Fall back to the script's parent (Cowork-Project model) when the env var is
    absent.
    """
    return Path(os.environ.get("CLAUDE_PLUGIN_ROOT", str(SCRIPTS_DIR.parent)))


def _resolve_substrate_data(data_root: str | None) -> Path | None:
    """SUBSTRATE_DATA = the ONE durable, user-picked BeCivic folder.

    Resolution order:
      1. `--data-root <dir>` (the directory of the loaded CLAUDE.md) when passed.
      2. Ancestor-walk from cwd looking for `.be-civic/marker` (cap
         MARKER_WALK_CAP levels), gating on the detection-only marker.
    Returns None when neither resolves (pre-onboarding / dev loop) — the caller
    skips every disk sweep and exits 0.
    """
    if data_root:
        candidate = Path(data_root)
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            return None
        return None

    try:
        here = Path.cwd().resolve()
    except OSError:
        return None
    current = here
    for _ in range(MARKER_WALK_CAP + 1):
        marker = current / ".be-civic" / "marker"
        try:
            if marker.is_file():
                return current
        except OSError:
            pass
        if current.parent == current:
            break
        current = current.parent
    return None


def _resolve_substrate_state(substrate_data: Path | None) -> Path | None:
    """SUBSTRATE_STATE = ${SUBSTRATE_DATA}/.be-civic/state — a pure child.

    NEVER read from an env var for durable state (the old
    ${CLAUDE_PLUGIN_DATA}-backed surface is non-persistent on Cowork). Returns
    None whenever SUBSTRATE_DATA is absent.
    """
    if substrate_data is None:
        return None
    return substrate_data / ".be-civic" / "state"


# SUBSTRATE_ROOT is env-only (no --data-root dependency) so it is safe to
# resolve at import. SUBSTRATE_DATA / SUBSTRATE_STATE are resolved in main()
# (after arg-parse) and bound into these module globals there.
SUBSTRATE_ROOT = _resolve_substrate_root()
SUBSTRATE_DATA: Path | None = None
SUBSTRATE_STATE: Path | None = None

# Back-compat aliases for any reader still importing the old names. PLUGIN_ROOT
# / BUNDLE_ROOT are stable; USER_DATA_DIR now tracks SUBSTRATE_STATE and is
# re-bound alongside it in main().
PLUGIN_ROOT = SUBSTRATE_ROOT
BUNDLE_ROOT = SUBSTRATE_ROOT
USER_DATA_DIR: Path | None = None


JIT_FALLBACK = """\
PREAMBLE: fallback_active
PREAMBLE_JIT_GUIDANCE: |
  The preamble couldn't complete — orchestrator failed before producing full
  state. Proceed with safe defaults AND discover capabilities just-in-time:

  - SESSION_ID: generate a UUIDv7 yourself for this session.
  - SUBSTRATE_DATA: the user-picked BeCivic folder (the one durable surface).
    Resolve it from the loaded CLAUDE.md's directory, or by walking up from cwd
    for a `.be-civic/marker`. If you cannot find it, onboarding has not run yet.
  - SUBSTRATE_STATE: ${SUBSTRATE_DATA}/.be-civic/state (a child of the folder).
  - PENDING_STATE: assume none. If you find unsubmitted observation files
    or research-notes files older than this session start, treat as pending.
  - BECIVIC_WIRE: library reads + submissions go over HTTPS via the WebFetch
    tool against `becivic.be/api/*`, Bearer key from `${SUBSTRATE_STATE}/.env`
    when present.
  - BECIVIC_MCP_CONNECTED: check your own tool list for `mcp__becivic__*`
    (fallback transport during MCP sunset); otherwise use WebFetch.
  - BROWSER_TOOL_AVAILABLE: check your own tool list for a browser-control tool.
  - VISION_AVAILABLE: assume from your own model capability.
  - SUBMIT_OBSERVATIONS_THIS_SESSION: assume yes if the scrub-rules baseline is
    present; hold submissions if you cannot confirm a scrub floor.
    Ask the customer once at the first browser-needing step rather than running
    a pre-emptive setup walkthrough.

  In short: behave as if all flags are unknown but DO actively check when a
  flag matters.
"""

def _bind_surfaces(substrate_data: Path | None) -> None:
    """Bind the resolved durable surface into the module globals the rest of the
    file reads. Called from main() after arg-parse so `--data-root` is honoured.
    """
    global SUBSTRATE_DATA, SUBSTRATE_STATE, USER_DATA_DIR
    SUBSTRATE_DATA = substrate_data
    SUBSTRATE_STATE = _resolve_substrate_state(substrate_data)
    USER_DATA_DIR = SUBSTRATE_STATE


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                         SUBSTRATE MECHANISM                               ║
# ║  Disk + git + state-graph plumbing. Runs regardless of agent behaviour.   ║
# ╚══════════════════════════════════════════════════════════════════════════╝


# ----------------------------------------------------------------------------
# §M1 — Writable probe (non-fatal — emits SUBSTRATE_WRITABLE: yes|no)
# ----------------------------------------------------------------------------

def verify_writable() -> bool:
    """Quick write test against ${SUBSTRATE_DATA}/.be-civic/state. True if
    writable. Non-fatal: a `no` result downgrades the session (emit
    SUBSTRATE_WRITABLE: no) but never hard-fails. Only called when
    SUBSTRATE_STATE is resolved."""
    if SUBSTRATE_STATE is None:
        return False
    try:
        SUBSTRATE_STATE.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = SUBSTRATE_STATE / f".preamble-probe-{uuid.uuid4().hex[:8]}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


# ----------------------------------------------------------------------------
# §M2 — git helpers (used by the migration restore + recovery sweep)
# ----------------------------------------------------------------------------

def _git(repo: Path, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess | None:
    """Run a git command inside `repo`. Returns the CompletedProcess, or None
    if the git binary is missing / the call times out. Never raises."""
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


def _is_git_repo(repo: Path) -> bool:
    res = _git(repo, ["rev-parse", "--is-inside-work-tree"])
    return bool(res and res.returncode == 0 and res.stdout.strip() == "true")


def _count_staged(porcelain: str) -> int:
    """Count entries staged in the index from `git status --porcelain` output."""
    n = 0
    for line in porcelain.splitlines():
        if not line:
            continue
        index_status = line[0]
        if index_status not in (" ", "?"):
            n += 1
    return n


def _commit_all(repo: Path, message_template: str) -> int:
    """`git add -A` then commit `repo` with the Be Civic author. Returns the
    number of files committed (0 if nothing staged / on any failure).

    `message_template` may contain a `{n}` placeholder, filled with the staged
    file count before committing. The on-disk .gitignore allowlist governs what
    is staged; .env is never in it. Never raises."""
    if not _is_git_repo(repo):
        return 0
    # Identity guard: `git add -A` relies on the .gitignore allowlist to
    # exclude the Identity slot. The harness key lives at the EXACT nested path
    # `.be-civic/state/.env` inside the single user-owned repo. If it exists but
    # is NOT yet gitignored (e.g. onboarding wrote the key before the allowlist)
    # OR is already tracked, committing would leak the harness key into history.
    # Refuse + alert rather than risk it.
    #   - `check-ignore -q -- .be-civic/state/.env` exits 0 iff it is ignored.
    #   - `ls-files -- .be-civic/state/.env` returning anything means it is
    #     already tracked (a prior leak) — refuse regardless of check-ignore.
    env_rel = ".be-civic/state/.env"
    if (repo / ".be-civic" / "state" / ".env").exists():
        chk = _git(repo, ["check-ignore", "-q", "--", env_rel])
        if not chk or chk.returncode != 0:
            print(
                f"OPERATOR_ALERT: {env_rel} present but not gitignored in {repo}; "
                "refusing auto-commit to protect Identity. "
                "Write the .gitignore allowlist before committing."
            )
            return 0
    tracked = _git(repo, ["ls-files", "--", env_rel])
    if tracked and tracked.returncode == 0 and tracked.stdout.strip():
        print(
            f"OPERATOR_ALERT: {env_rel} is tracked by git in {repo}; "
            "refusing auto-commit to protect Identity. "
            "Untrack it and rewrite history before committing."
        )
        return 0
    add = _git(repo, ["add", "-A"])
    if not add or add.returncode != 0:
        return 0
    status = _git(repo, ["status", "--porcelain"])
    if not status or status.returncode != 0:
        return 0
    staged = _count_staged(status.stdout)
    if staged == 0:
        return 0
    message = message_template.replace("{n}", str(staged))
    commit = _git(
        repo,
        [
            "-c", "user.name=Be Civic",
            "-c", "user.email=noreply@becivic.be",
            "commit",
            "--author", "Be Civic <noreply@becivic.be>",
            "-m", message,
        ],
    )
    if not commit or commit.returncode != 0:
        return 0
    return staged


# ----------------------------------------------------------------------------
# §M3 — Surface emission (SUBSTRATE_STATE / SUBSTRATE_DATA / SUBSTRATE_ROOT)
# ----------------------------------------------------------------------------

def emit_surfaces() -> None:
    """Emit the three substrate surface paths for the harness.

    SUBSTRATE_ROOT is always present (env / install dir). SUBSTRATE_DATA and its
    child SUBSTRATE_STATE are `absent` pre-onboarding / in the dev loop.
    """
    print(f"SUBSTRATE_ROOT: {SUBSTRATE_ROOT}")
    if SUBSTRATE_DATA is not None:
        print(f"SUBSTRATE_DATA: {SUBSTRATE_DATA}")
        print(f"SUBSTRATE_STATE: {SUBSTRATE_STATE}")
    else:
        print("SUBSTRATE_DATA: absent")
        print("SUBSTRATE_STATE: absent")
    # Back-compat aliases consumed by the current CLAUDE.md guidance.
    print(f"PLUGIN_ROOT: {SUBSTRATE_ROOT}")
    print(f"USER_DATA_DIR: {SUBSTRATE_STATE if SUBSTRATE_STATE is not None else 'absent'}")


def write_session_data_root(session_id: str) -> None:
    """Write the preamble→monitor handoff pointer at
    ${CLAUDE_PLUGIN_DATA}/.session-data-root.

    Line 1 = absolute path to ${SUBSTRATE_DATA} (the one durable surface, the
    repo the monitor watches). Line 2 = `session=<id>` so a stale read is
    detectable. Best-effort: only when CLAUDE_PLUGIN_DATA is set AND
    SUBSTRATE_DATA resolved. Monitor + preamble share ${CLAUDE_PLUGIN_DATA}
    within one conversation, which is sound (the persistence bug is
    cross-conversation only). Never raises."""
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data or SUBSTRATE_DATA is None:
        return
    pointer = Path(plugin_data) / ".session-data-root"
    try:
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(
            f"{SUBSTRATE_DATA}\nsession={session_id}\n", encoding="utf-8"
        )
    except OSError:
        pass


# ----------------------------------------------------------------------------
# §M4 — version.json read/write + schema-migration runner
# ----------------------------------------------------------------------------

def _version_path() -> Path:
    return SUBSTRATE_STATE / "version.json"


def read_state_version() -> int:
    """Read `state_version` from ${SUBSTRATE_STATE}/version.json.

    Returns CURRENT_SCHEMA_VERSION when the file is absent (fresh install — no
    migration needed; the version stamp is written lazily). Returns 0 when the
    file exists but is unparseable/missing the field (treat as oldest, so the
    full migration chain runs to repair it)."""
    vp = _version_path()
    if not vp.exists():
        return CURRENT_SCHEMA_VERSION
    try:
        data = json.loads(vp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    v = data.get("state_version")
    return v if isinstance(v, int) else 0


def write_version_stamp(state_version: int) -> None:
    """Write version.json with the canonical shape."""
    vp = _version_path()
    stamp = {
        "state_version": state_version,
        "plugin_version": PLUGIN_VERSION_STRING,
        "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        vp.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


# Ordered migration steps. Each entry is (target_version, callable). The
# callable migrates the on-disk hidden state FROM target_version-1 TO
# target_version and must be idempotent. Empty for the initial baseline
# (CURRENT_SCHEMA_VERSION == 1 with no prior shipped schema); future schema
# units append (2, _migrate_to_2), (3, _migrate_to_3), ...
MIGRATION_STEPS: list[tuple[int, "callable"]] = []


def run_schema_migration() -> None:
    """Compare on-disk state_version to CURRENT_SCHEMA_VERSION; run ordered
    steps between them. On failure, restore the state subtree from its git
    history and emit a single silent operator-alert line.

    Never raises; never blocks the user."""
    on_disk = read_state_version()
    if on_disk >= CURRENT_SCHEMA_VERSION:
        # Up to date (or fresh install). Ensure the stamp exists for fresh
        # installs so the next session has a baseline to compare against.
        if not _version_path().exists():
            write_version_stamp(CURRENT_SCHEMA_VERSION)
        print("SCHEMA_MIGRATION: up_to_date")
        return

    steps = [s for s in MIGRATION_STEPS if on_disk < s[0] <= CURRENT_SCHEMA_VERSION]
    if not steps:
        # No registered steps but versions differ → just bump the stamp
        # (covers the "schema constant advanced with no data change" case).
        write_version_stamp(CURRENT_SCHEMA_VERSION)
        print(f"SCHEMA_MIGRATION: bumped {on_disk}->{CURRENT_SCHEMA_VERSION}")
        return

    applied = on_disk
    try:
        for target, migrate in steps:
            migrate()
            applied = target
        write_version_stamp(CURRENT_SCHEMA_VERSION)
        print(f"SCHEMA_MIGRATION: applied {on_disk}->{CURRENT_SCHEMA_VERSION}")
    except Exception:
        # Auto-restore the state subtree from git, keep state_version at
        # the pre-migration value, and page the operator out-of-band. The user
        # gets a non-blocking degraded-mode session.
        _restore_hidden_from_git()
        # Single silent operator-alert line (parsed by CLAUDE.md, not shown
        # verbatim to the user).
        print(
            "OPERATOR_ALERT: schema_migration_failed "
            f"from_version={on_disk} target_version={CURRENT_SCHEMA_VERSION} "
            f"last_ok_step={applied}"
        )
        print("SCHEMA_MIGRATION: failed_degraded_mode")


def _restore_hidden_from_git() -> None:
    """Restore the state subtree from its committed git history (operational
    rollback). There is ONE repo at ${SUBSTRATE_DATA}; we must NOT
    `git reset --hard HEAD` it — that would clobber the user's uncommitted
    visible prose (CLAUDE.md, MEMORY.md, procedure notes) in the same tree.
    Scope the restore to `.be-civic/state/` only. Best-effort; never raises."""
    if SUBSTRATE_DATA is None or not _is_git_repo(SUBSTRATE_DATA):
        return
    # Path-scoped restore: clears a half-staged migration AND reverts the
    # working tree for the state subtree, leaving everything else (including the
    # user's uncommitted prose) untouched. .env / sessions/ are untracked and so
    # are unaffected.
    res = _git(
        SUBSTRATE_DATA,
        ["restore", "--staged", "--worktree", "--", ".be-civic/state/"],
    )
    if res is None or res.returncode != 0:
        # Older git without `restore`: fall back to a path-scoped checkout.
        _git(SUBSTRATE_DATA, ["checkout", "HEAD", "--", ".be-civic/state/"])


# ----------------------------------------------------------------------------
# §M5 — Recovery sweep
# ----------------------------------------------------------------------------

def run_recovery_sweep() -> None:
    """Commit uncommitted allowlisted changes in the single project repo ONCE as
    `auto: recovery — <N> file(s) modified outside monitor coverage`.

    There is now ONE git repo at the project-folder root (${SUBSTRATE_DATA});
    state lives at the `.be-civic/state/` subtree under it. Catches writes that
    landed while no monitor was running. Emits a count marker. Never raises.
    Only called when SUBSTRATE_DATA is resolved."""
    if SUBSTRATE_DATA is None:
        print("RECOVERY_SWEEP_COMMITTED: 0")
        return
    try:
        # `{n}` is filled with the staged count by _commit_all.
        total = _commit_all(
            SUBSTRATE_DATA,
            "auto: recovery — {n} file(s) modified outside monitor coverage",
        )
    except Exception:
        total = 0
    print(f"RECOVERY_SWEEP_COMMITTED: {total}")


# ----------------------------------------------------------------------------
# §M6 — procedures.json registry migration
# ----------------------------------------------------------------------------

def migrate_procedures_registry() -> None:
    """Populate ${SUBSTRATE_STATE}/procedures.json from legacy per-procedure
    case.json machinery state if the registry is absent but legacy state
    exists.

    Legacy layout: each procedure kept a case.json under the project folder
    (e.g. ${SUBSTRATE_DATA}/<slug>/case.json) carrying its own machinery state.
    The current layout uses a single registry at ${SUBSTRATE_STATE}/procedures.json
    so the preamble can read every in-flight procedure without walking the whole
    folder. Idempotent: no-op when procedures.json already exists. Harmless
    no-op for greenfield. Never raises.
    """
    if SUBSTRATE_STATE is None or SUBSTRATE_DATA is None:
        # No durable surface yet (pre-onboarding / dev loop) — nothing to do.
        print("PROCEDURES_REGISTRY: absent")
        return
    registry_path = SUBSTRATE_STATE / "procedures.json"
    if registry_path.exists():
        print("PROCEDURES_REGISTRY: present")
        return

    entries: list[dict] = []
    try:
        for child in sorted(SUBSTRATE_DATA.iterdir()):
            if not child.is_dir():
                continue
            legacy = child / "case.json"
            if not legacy.exists():
                continue
            try:
                case = json.loads(legacy.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            # Map legacy fields → registry entry. Tolerate both legacy (skill_*) and
            # current (process_*) field names.
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            entries.append(
                {
                    "slug": child.name,
                    "process_id": case.get("process_id")
                    or case.get("skill_id")
                    or child.name,
                    "process_version": str(
                        case.get("process_version")
                        or case.get("skill_version")
                        or "0"
                    ),
                    "status": case.get("status", "active"),
                    "started_at": case.get("started_at", now),
                    "updated_at": case.get("updated_at", now),
                }
            )
    except OSError:
        pass

    if not entries:
        print("PROCEDURES_REGISTRY: no_legacy_state")
        return

    registry = {"schema_version": 1, "procedures": entries}
    try:
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        print(f"PROCEDURES_REGISTRY: migrated {len(entries)} procedure(s)")
    except OSError:
        print("PROCEDURES_REGISTRY: migrate_failed")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                          HARNESS BEHAVIOUR                                 ║
# ║  What gets surfaced into the agent's first turn.                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝


# ----------------------------------------------------------------------------
# §H1 — Session id
# ----------------------------------------------------------------------------

def new_session_id() -> str:
    """UUIDv7-ish identifier (stdlib lacks uuid7; combine time+random)."""
    ts = int(time.time() * 1000)
    rnd = uuid.uuid4().hex[:16]
    return f"ses_{ts:013x}-{rnd}"


# ----------------------------------------------------------------------------
# §H2 — Session-start scans (orphan buffers / pending state / browser cap)
# ----------------------------------------------------------------------------

def run_script(name: str) -> tuple[bool, str]:
    """Run a sibling script and capture its stdout.

    The already-resolved SUBSTRATE_STATE is passed down via the
    BC_SUBSTRATE_STATE env var so sub-scripts use the preamble's resolution
    (the `.be-civic/state` child) rather than re-resolving CLAUDE_PLUGIN_DATA.
    """
    script_path = SCRIPTS_DIR / name
    if not script_path.exists():
        return False, f"{name.upper().replace('-', '_').replace('.PY', '')}: missing"
    child_env = dict(os.environ)
    if SUBSTRATE_STATE is not None:
        child_env["BC_SUBSTRATE_STATE"] = str(SUBSTRATE_STATE)
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=child_env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False, ""
    ok = result.returncode == 0
    return ok, result.stdout.rstrip()


def surface_scan(name: str, fail_marker: str) -> None:
    """Run a scan sub-script and print its output, or a probe_failed marker."""
    ok, output = run_script(name)
    if ok and output:
        print(output)
    elif not ok:
        print(fail_marker)


# ----------------------------------------------------------------------------
# §H3 — Pending-verification surfacing (transient .pending-verification flag)
# ----------------------------------------------------------------------------

def surface_pending_verification() -> None:
    """Surface a transient ${SUBSTRATE_STATE}/.pending-verification flag.

    Written by the onboarding auth flow between POST /api/auth/start-verification
    and the paste-back POST /api/auth/verify. Its presence at session start means
    a verification ceremony was begun but not completed; the harness should resume
    it (re-prompt for the magic link) rather than starting onboarding fresh.
    Transient — not committed (absent from the allowlist)."""
    if SUBSTRATE_STATE is None:
        print("PENDING_VERIFICATION: none")
        return
    flag = SUBSTRATE_STATE / ".pending-verification"
    if not flag.exists():
        print("PENDING_VERIFICATION: none")
        return
    try:
        body = flag.read_text(encoding="utf-8").strip()
    except OSError:
        body = ""
    print("PENDING_VERIFICATION: present")
    if body:
        print(f"PENDING_VERIFICATION_DETAIL: {body}")


_HARNESS_KEY_PRESENT_RE = re.compile(r"^\s*BECIVIC_HARNESS_KEY\s*=\s*\S")


def surface_harness_key() -> None:
    """Surface HARNESS_KEY: present | absent — PRESENCE ONLY, value never bound.

    The harness key lives at ${SUBSTRATE_STATE}/.env as the `BECIVIC_HARNESS_KEY=`
    line. This probe reports only whether such a line exists with *something*
    after the `=`, so the harness can branch into the keyless-half-state recovery
    (re-run email→code verification) without itself reading .env. It NEVER binds,
    slices, retains, prints, or echoes the key value: it runs a boolean regex
    (`= ` followed by at least one non-whitespace char) per line and keeps only
    the True/False result. The secret substring is never assigned to a variable.
    Identity stays substrate-side; this probe treats the value as untouchable.
    """
    if SUBSTRATE_STATE is None:
        print("HARNESS_KEY: absent")
        return
    env_path = SUBSTRATE_STATE / ".env"
    present = False
    try:
        if env_path.is_file():
            with env_path.open(encoding="utf-8") as fh:
                for line in fh:
                    # Boolean match only — does NOT capture or materialise the
                    # value. `.search` returns a match object we coerce to bool.
                    if _HARNESS_KEY_PRESENT_RE.search(line):
                        present = True
                        break
    except (OSError, UnicodeDecodeError):
        # Can't read .env (permissions, or non-UTF-8 bytes) — report unknown so
        # the harness verifies for itself rather than assuming a key is present.
        # UnicodeDecodeError is a ValueError subclass (not OSError), so it is
        # caught explicitly here to keep a local .env problem from cascading into
        # a whole-preamble JIT fallback.
        print("HARNESS_KEY: unknown")
        return
    print(f"HARNESS_KEY: {'present' if present else 'absent'}")


# ----------------------------------------------------------------------------
# §H4 — Profile inline
# ----------------------------------------------------------------------------

def emit_profile_json() -> None:
    """Emit profile.json contents inline so the harness doesn't have to Read it.

    Read from SUBSTRATE_STATE first (customer state). Fall back to SUBSTRATE_ROOT
    (template shipped with the plugin) on first-contact when no customer state
    exists yet.
    """
    candidates = []
    if SUBSTRATE_STATE is not None:
        candidates.append(SUBSTRATE_STATE / "profile.json")
    candidates.append(SUBSTRATE_ROOT / "profile.json")
    for profile_path in candidates:
        if profile_path.exists():
            try:
                content = profile_path.read_text(encoding="utf-8")
            except OSError:
                continue
            print(f"PROFILE_JSON_SOURCE: {profile_path}")
            print("PROFILE_JSON: inline_below")
            print("PROFILE_JSON_BEGIN")
            print(content.rstrip())
            print("PROFILE_JSON_END")
            return
    print("PROFILE_JSON: absent")


# ----------------------------------------------------------------------------
# §H5 — Capability probes (BECIVIC_MCP_CONNECTED + scrub-rules freshness)
# ----------------------------------------------------------------------------

def emit_mcp_capability() -> None:
    """Emit BECIVIC_MCP_CONNECTED.

    The wire is WebFetch-against-REST first; the becivic MCP server is a
    fallback transport that still ships in `.mcp.json` during its sunset. So the
    key is still meaningful — it tells the harness whether the fallback transport
    is reachable.

    BUT a detached Python subprocess cannot see the host agent's connected-tool
    list: there is no env var or file that lists `mcp__becivic__*`. The honest
    value from here is `unknown`; the agent resolves it from its own tool list
    (the harness instructions tell it to check for `mcp__becivic__*` and fall
    back to WebFetch otherwise). We deliberately never assert `yes`/`no` from a
    surface that can't observe the answer.
    """
    print("BECIVIC_MCP_CONNECTED: unknown")


def emit_submit_observations() -> None:
    """Emit SUBMIT_OBSERVATIONS_THIS_SESSION: yes | no.

    The Layer-1 PII scrub floor is a regex pass against a scrub-rules file. The
    plugin ships a baseline at ${SUBSTRATE_ROOT}/data/scrub-rules.json (the
    floor); the harness may refresh it into the ephemeral plugin-data cache at
    ${CLAUDE_PLUGIN_DATA}/scrub-rules.json. Scrub-rules are NOT durable state —
    they never live in the project folder. The preamble does NO network (it
    stays local + fast), so the freshness check it can honestly make is: does a
    usable scrub-rules file exist at all?

      - A usable rules file is present (cached refresh OR shipped baseline) ->
        the regex scrub floor can run -> `yes`. The agent still re-checks its
        own session-start network refresh and may downgrade to `no` later if
        that fetch fails beyond retries (per the harness instructions); the
        preamble sets the floor, not the ceiling.
      - No usable rules file anywhere (corrupt/missing baseline — an install
        error) -> the scrub floor cannot run -> `no`. Fail closed: never submit
        without a scrub floor in place.
    """
    candidates = [SUBSTRATE_ROOT / "data" / "scrub-rules.json"]
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        candidates.insert(0, Path(plugin_data) / "scrub-rules.json")
    for rules_path in candidates:
        try:
            if rules_path.is_file() and rules_path.stat().st_size > 0:
                print("SUBMIT_OBSERVATIONS_THIS_SESSION: yes")
                return
        except OSError:
            continue
    print("SUBMIT_OBSERVATIONS_THIS_SESSION: no")


# ============================================================================
# Orchestration
# ============================================================================

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="preamble.py — Be Civic session-start orchestrator",
        add_help=True,
    )
    parser.add_argument(
        "--data-root",
        dest="data_root",
        default=None,
        metavar="DIR",
        help=(
            "absolute path to the BeCivic folder (the directory of the loaded "
            "CLAUDE.md). When omitted, the preamble ancestor-walks from cwd for "
            "a `.be-civic/marker`."
        ),
    )
    # Tolerate unknown args so the harness can pass extras without breaking us.
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    # --- RESOLUTION (after arg-parse so --data-root is honoured) ---------------
    args = _parse_args(argv)
    _bind_surfaces(_resolve_substrate_data(args.data_root))

    # --- SUBSTRATE MECHANISM --------------------------------------------------
    # 1. Pre-onboarding / dev loop: no durable folder resolved. Emit absent
    #    surfaces, SKIP every disk sweep, and exit 0 (no hard-fail).
    if SUBSTRATE_DATA is None:
        emit_surfaces()
        session_id = new_session_id()
        print(f"SESSION_ID: {session_id}")
        print("SESSION_STATE_DIR: absent")
        print("SCHEMA_MIGRATION: skipped_no_data_root")
        print("PROCEDURES_REGISTRY: absent")
        print("RECOVERY_SWEEP_COMMITTED: 0")
        # Still surface the read-only capability probes + profile template so the
        # harness can run onboarding.
        surface_pending_verification()
        surface_harness_key()
        ok, browser_output = run_script("detect-browser-capability.py")
        if ok and browser_output:
            print(browser_output)
        elif not ok:
            print("OS_PLATFORM: unknown")
            print("CHROME_INSTALLED: unknown")
            print("BROWSER_TOOL_AVAILABLE: unknown")
            print("VISION_AVAILABLE: unknown")
        emit_mcp_capability()
        emit_submit_observations()
        emit_profile_json()
        return 0

    # 2. Emit the three substrate surfaces.
    emit_surfaces()

    # 2a. Writable probe (NON-FATAL). When the state dir is not writable, emit a
    #     downgrade marker instead of a hard-fail and continue with the read
    #     surfaces still useful for the harness.
    writable = verify_writable()
    print(f"SUBSTRATE_WRITABLE: {'yes' if writable else 'no'}")

    # 3. Schema-migration runner (compare on-disk state_version to current;
    #    apply ordered steps; restore-on-failure + operator alert).
    if writable:
        run_schema_migration()
        # 4. procedures.json registry migration (legacy case.json → registry;
        #    harmless no-op for greenfield).
        migrate_procedures_registry()
        # 5. Recovery sweep (commit uncommitted allowlisted changes once in the
        #    single project repo).
        run_recovery_sweep()
    else:
        print("SCHEMA_MIGRATION: skipped_not_writable")
        print("PROCEDURES_REGISTRY: skipped_not_writable")
        print("RECOVERY_SWEEP_COMMITTED: 0")

    # --- HARNESS BEHAVIOUR ----------------------------------------------------
    # 6. Session id.
    session_id = new_session_id()
    print(f"SESSION_ID: {session_id}")
    print(f"SESSION_STATE_DIR: {SUBSTRATE_STATE}/sessions/{session_id}/state/")

    # 6a. Write the preamble→monitor handoff pointer (best-effort).
    write_session_data_root(session_id)

    # 7. Orphan-buffers scan.
    surface_scan("scan-orphan-buffers.py", "ORPHAN_SESSIONS_CLEANED: probe_failed")

    # 8. Pending-state scan.
    surface_scan("scan-pending-state.py", "PENDING_STATE: probe_failed")

    # 9. Pending-verification flag.
    surface_pending_verification()

    # 9a. Harness-key presence (presence only; value never read/echoed) so the
    #     harness can branch into keyless-half-state recovery without a Read.
    surface_harness_key()

    # 10. Browser + vision capability (OS_PLATFORM, CHROME_INSTALLED,
    #     BROWSER_TOOL_AVAILABLE, VISION_AVAILABLE). On probe failure, emit the
    #     honest conservative defaults for every key the sub-script owns so the
    #     harness always sees the full set.
    ok, browser_output = run_script("detect-browser-capability.py")
    if ok and browser_output:
        print(browser_output)
    elif not ok:
        print("OS_PLATFORM: unknown")
        print("CHROME_INSTALLED: unknown")
        print("BROWSER_TOOL_AVAILABLE: unknown")
        print("VISION_AVAILABLE: unknown")

    # 11. MCP fallback-transport capability (agent resolves the true value from
    #     its own tool list; the preamble emits the honest `unknown`).
    emit_mcp_capability()

    # 12. Scrub-rules freshness -> whether observations may be submitted.
    emit_submit_observations()

    # 13. Profile inline.
    emit_profile_json()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Catch-all: if orchestration itself crashes, emit fallback so the
        # harness never sees a half-written preamble.
        print(JIT_FALLBACK)
        try:
            emit_profile_json()
        except Exception:
            print("PROFILE_JSON: probe_failed")
        sys.exit(1)
