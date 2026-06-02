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
  SUBSTRATE_STATE = ${CLAUDE_PLUGIN_DATA}   — hidden, agent-managed.
  SUBSTRATE_DATA  = visible path via marker  — user-picked folder.
  SUBSTRATE_ROOT  = ${CLAUDE_PLUGIN_ROOT}    — read-only install.

Failure semantics: hard-fail on read-only hidden surface (install error). On
any sub-script error, emit a `<NAME>: probe_failed` marker and continue. The
schema-migration runner restores the hidden surface from git history on failure
and emits a single silent operator-alert line. If the orchestrator itself
crashes, emit JIT_FALLBACK so CLAUDE.md discovers capabilities just-in-time.

Runtime: Python 3 stdlib only. No third-party dependencies.
Cross-platform: macOS, Windows (native, not WSL), Linux.
Total time budget: <500ms (all local; no network).
"""

from __future__ import annotations

import json
import os
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
PLUGIN_VERSION_STRING = "0.3.0"

# Hidden-surface files the recovery sweep / monitor commit. Identity files
# (.env, user-id is allowlisted but harness_key in .env is not) are governed by
# the on-disk .gitignore allowlist, not this list — we only ever `git add -A`.


def _resolve_substrate_root() -> Path:
    """SUBSTRATE_ROOT = read-only plugin install dir (${CLAUDE_PLUGIN_ROOT}).

    Fall back to the script's parent (Cowork-Project model) when the env var is
    absent.
    """
    return Path(os.environ.get("CLAUDE_PLUGIN_ROOT", str(SCRIPTS_DIR.parent)))


def _resolve_substrate_state(substrate_root: Path) -> Path:
    """SUBSTRATE_STATE = hidden, agent-managed surface (${CLAUDE_PLUGIN_DATA}).

    Survives plugin updates. Falls back to the install root when the env var is
    absent (degraded single-folder model).
    """
    return Path(os.environ.get("CLAUDE_PLUGIN_DATA", str(substrate_root)))


def _resolve_substrate_data(substrate_state: Path) -> Path | None:
    """SUBSTRATE_DATA = visible, user-picked surface.

    Located via the pointer marker the onboarding flow writes at
    ${SUBSTRATE_STATE}/.be-civic/marker. Returns None when the marker is absent
    (onboarding has not run / anonymous-read mode) or points nowhere valid.
    """
    marker = substrate_state / ".be-civic" / "marker"
    try:
        raw = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    candidate = Path(raw)
    try:
        if not candidate.is_dir():
            return None
    except OSError:
        return None
    return candidate


SUBSTRATE_ROOT = _resolve_substrate_root()
SUBSTRATE_STATE = _resolve_substrate_state(SUBSTRATE_ROOT)
SUBSTRATE_DATA = _resolve_substrate_data(SUBSTRATE_STATE)

# Back-compat aliases for any reader still importing the old names.
PLUGIN_ROOT = SUBSTRATE_ROOT
USER_DATA_DIR = SUBSTRATE_STATE
BUNDLE_ROOT = SUBSTRATE_ROOT


JIT_FALLBACK = """\
PREAMBLE: fallback_active
PREAMBLE_JIT_GUIDANCE: |
  The preamble couldn't complete — orchestrator failed before producing full
  state. Proceed with safe defaults AND discover capabilities just-in-time:

  - SESSION_ID: generate a UUIDv7 yourself for this session.
  - SUBSTRATE_STATE: assume the hidden plugin-data folder.
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

WRITE_FAILURE = """\
PREAMBLE: fatal
PREAMBLE_ERROR: bundle_root_read_only
PREAMBLE_DETAIL: |
  The hidden substrate surface is not writable. Be Civic needs a writable
  state directory to save customer state, observation buffers, and research
  notes.

  If you installed this as a Cowork plugin pointing at a folder you own, this
  is an install error — check folder permissions. If you opened the bundle
  from a read-only location (a zip, a system folder, a network share without
  write access), copy it to a writable location and reopen.

  The harness cannot proceed.
"""


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                         SUBSTRATE MECHANISM                               ║
# ║  Disk + git + state-graph plumbing. Runs regardless of agent behaviour.   ║
# ╚══════════════════════════════════════════════════════════════════════════╝


# ----------------------------------------------------------------------------
# §M1 — Writable hard-check (fail fast on a read-only hidden surface)
# ----------------------------------------------------------------------------

def verify_writable() -> bool:
    """Quick write test against the hidden surface. True if writable."""
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
    # exclude the Identity slot. If `.env` exists but is NOT yet gitignored
    # (e.g. onboarding wrote the key before the allowlist), committing would
    # leak the harness key into history. Refuse + alert rather than risk it.
    # `check-ignore -q` exits 0 iff `.env` is ignored.
    if (repo / ".env").exists():
        chk = _git(repo, ["check-ignore", "-q", ".env"])
        if not chk or chk.returncode != 0:
            print(
                f"OPERATOR_ALERT: .env present but not gitignored in {repo}; "
                "refusing auto-commit to protect Identity. "
                "Write the .gitignore allowlist before committing."
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
    """Emit the three substrate surface paths for the harness."""
    print(f"SUBSTRATE_ROOT: {SUBSTRATE_ROOT}")
    print(f"SUBSTRATE_STATE: {SUBSTRATE_STATE}")
    if SUBSTRATE_DATA is not None:
        print(f"SUBSTRATE_DATA: {SUBSTRATE_DATA}")
    else:
        print("SUBSTRATE_DATA: absent")
    # Back-compat aliases consumed by the current CLAUDE.md guidance.
    print(f"PLUGIN_ROOT: {SUBSTRATE_ROOT}")
    print(f"USER_DATA_DIR: {SUBSTRATE_STATE}")


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
    steps between them. On failure, restore the hidden surface from its git
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
        # Auto-restore the hidden surface from git, keep state_version at
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
    """Restore the hidden surface working tree from its committed git history
    (operational rollback). Best-effort; never raises."""
    if not _is_git_repo(SUBSTRATE_STATE):
        return
    # Discard working-tree + index changes back to the last commit. The
    # allowlist means only governed state is touched; .env is untracked and
    # therefore untouched.
    _git(SUBSTRATE_STATE, ["reset", "--hard", "HEAD"])


# ----------------------------------------------------------------------------
# §M5 — Recovery sweep
# ----------------------------------------------------------------------------

def run_recovery_sweep() -> None:
    """For each surface repo, commit uncommitted allowlisted changes ONCE as
    `auto: recovery — <N> file(s) modified outside monitor coverage`.

    Catches writes that landed while no monitor was running. Emits a count
    marker. Never raises."""
    total = 0
    repos = [SUBSTRATE_STATE]
    if SUBSTRATE_DATA is not None:
        repos.append(SUBSTRATE_DATA)
    for repo in repos:
        try:
            # `{n}` is filled with the staged count by _commit_all.
            staged = _commit_all(
                repo,
                "auto: recovery — {n} file(s) modified outside monitor coverage",
            )
        except Exception:
            staged = 0
        total += staged
    print(f"RECOVERY_SWEEP_COMMITTED: {total}")


# ----------------------------------------------------------------------------
# §M6 — procedures.json registry migration
# ----------------------------------------------------------------------------

def migrate_procedures_registry() -> None:
    """Populate ${SUBSTRATE_STATE}/procedures.json from legacy per-procedure
    case.json machinery state if the registry is absent but legacy state
    exists.

    Legacy layout: each procedure kept a case.json under the visible surface
    (e.g. ${SUBSTRATE_DATA}/<slug>/case.json) carrying its own machinery state.
    The current layout uses a single registry on the hidden surface so the
    preamble can read every in-flight procedure without walking the visible
    tree. Idempotent: no-op when procedures.json already exists. Never raises.
    """
    registry_path = SUBSTRATE_STATE / "procedures.json"
    if registry_path.exists():
        print("PROCEDURES_REGISTRY: present")
        return
    if SUBSTRATE_DATA is None:
        # Nothing to migrate from; do not create an empty registry (onboarding
        # writes it on first procedure intent — contract §6).
        print("PROCEDURES_REGISTRY: absent")
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
    """Run a sibling script and capture its stdout."""
    script_path = SCRIPTS_DIR / name
    if not script_path.exists():
        return False, f"{name.upper().replace('-', '_').replace('.PY', '')}: missing"
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
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


# ----------------------------------------------------------------------------
# §H4 — Profile inline
# ----------------------------------------------------------------------------

def emit_profile_json() -> None:
    """Emit profile.json contents inline so the harness doesn't have to Read it.

    Read from SUBSTRATE_STATE first (customer state). Fall back to SUBSTRATE_ROOT
    (template shipped with the plugin) on first-contact when no customer state
    exists yet.
    """
    candidates = [
        SUBSTRATE_STATE / "profile.json",
        SUBSTRATE_ROOT / "profile.json",
    ]
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
    plugin ships a baseline at ${SUBSTRATE_ROOT}/data/scrub-rules.json; the
    harness may refresh it substrate-side at ${SUBSTRATE_STATE}/scrub-rules.json.
    The preamble does NO network (it stays local + fast), so the freshness check
    it can honestly make is: does a usable scrub-rules file exist at all?

      - A usable rules file is present (cached refresh OR shipped baseline) ->
        the regex scrub floor can run -> `yes`. The agent still re-checks its
        own session-start network refresh and may downgrade to `no` later if
        that fetch fails beyond retries (per the harness instructions); the
        preamble sets the floor, not the ceiling.
      - No usable rules file anywhere (corrupt/missing baseline — an install
        error) -> the scrub floor cannot run -> `no`. Fail closed: never submit
        without a scrub floor in place.
    """
    candidates = [
        SUBSTRATE_STATE / "scrub-rules.json",
        SUBSTRATE_ROOT / "data" / "scrub-rules.json",
    ]
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

def main() -> int:
    # --- SUBSTRATE MECHANISM --------------------------------------------------
    # 1. Writable hard check. Fail fast if the hidden surface is read-only.
    if not verify_writable():
        print(WRITE_FAILURE)
        return 1

    # 2. Emit the three substrate surfaces.
    emit_surfaces()

    # 3. Schema-migration runner (compare on-disk state_version to current;
    #    apply ordered steps; restore-on-failure + operator alert).
    run_schema_migration()

    # 4. procedures.json registry migration (legacy case.json → registry).
    migrate_procedures_registry()

    # 5. Recovery sweep (commit uncommitted allowlisted changes once per repo).
    run_recovery_sweep()

    # --- HARNESS BEHAVIOUR ----------------------------------------------------
    # 6. Session id.
    session_id = new_session_id()
    print(f"SESSION_ID: {session_id}")
    print(f"SESSION_STATE_DIR: {SUBSTRATE_STATE}/sessions/{session_id}/state/")

    # 7. Orphan-buffers scan.
    surface_scan("scan-orphan-buffers.py", "ORPHAN_SESSIONS_CLEANED: probe_failed")

    # 8. Pending-state scan.
    surface_scan("scan-pending-state.py", "PENDING_STATE: probe_failed")

    # 9. Pending-verification flag.
    surface_pending_verification()

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
