# Be Civic Plugin — Capability Declaration (Cowork binding)

Per [40-substrate §10.3](../bc-workspace/handbook/content/05-product/40-substrate.md), every substrate binding
ships a capability declaration table naming the concrete mechanism it provides
for each prerequisite in §10.1 (required) and §10.2 (optional). This file is
the Cowork plugin's declaration.

Authoritative source: [handbook/05-product/51-cowork.md §10](../bc-workspace/handbook/content/05-product/51-cowork.md).
This file is a machine-readable / quick-reference copy; the handbook is
canonical. When they differ, the handbook wins.

Column convention per 51-cowork §10:
- **col 1** — prerequisite name verbatim from 40 §10.1/§10.2
- **col 2** — the concrete Cowork mechanism
- **col 3** — degraded fallback when the mechanism is absent or unavailable
- **col 4** — complete citation chain (40 §-anchor + vendor docs + back-links)

---

## Required prerequisites (40 §10.1)

| Prerequisite | Cowork mechanism | Degraded fallback | References |
|---|---|---|---|
| File system access | Standard POSIX-equivalent read/write/edit via the Cowork tool runtime (Write, Edit, MultiEdit) | n/a — required | 40 §10.1 |
| `${SUBSTRATE_DATA}` — user-visible writable storage | `<picked-parent>/BeCivic/` — user picks the parent at first contact via `mcp__cowork__request_cowork_directory`; harness creates `BeCivic/` inside it | n/a — required | 40 §10.1; 51-cowork §3.1, §4, §11 |
| `${SUBSTRATE_STATE}` — agent-managed hidden writable storage | `${CLAUDE_PLUGIN_DATA}` — Cowork-allocated persistent dir, survives plugin updates by contract; never user-browsed in normal use | n/a — required | 40 §10.1; [Cowork plugins reference §env vars](https://code.claude.com/docs/en/plugins-reference); 51-cowork §3.2, §5 |
| Identity-slot discipline within `${SUBSTRATE_STATE}` | `${CLAUDE_PLUGIN_DATA}/.env` excluded from git by the `.gitignore` allowlist shipped in `data/gitignore-state`; the atomic-commit monitor honours this exclusion; `bc-export` bundles via `git bundle` which naturally excludes `.env` (gitignored → never committed) | n/a — required | 40 §6.1, §10.1; 51-cowork §5, §7.3 |
| `${SUBSTRATE_ROOT}` — read-only plugin install directory | `${CLAUDE_PLUGIN_ROOT}` — Cowork-managed, refreshed on plugin update; harness never writes to it at runtime | n/a — required | 40 §10.1; 51-cowork §3.3 |
| Code execution | Python 3 stdlib at session start (`scripts/preamble.py` + sub-probes: `scan-orphan-buffers.py`, `scan-pending-state.py`, `detect-browser-capability.py`, `recovery-sweep.py`); on-demand execution via skills + the agent runtime; `scripts/bc_export.py` and `scripts/bc_import.py` for portability | n/a — required | 40 §10.1; 51-cowork §9 |
| Session-start hook | Cowork `SessionStart` hook registered in `hooks/hooks.json`, invoking `scripts/preamble.py` before any agent turn | n/a — required | 40 §10.1; [Cowork hooks reference](https://code.claude.com/docs/en/hooks); 51-cowork §9 |
| Session-lifetime watcher, per-write hook, OR built-in commit primitive | Cowork `monitor` mechanism — `hooks/auto-commit-monitor.js` (Node, `fs.watch` or equivalent; see W33 contract §5) declared in `plugin.json` with `when: "always"`. Satisfies the session-lifetime-watcher arm of 40 §8.1. Watches both surfaces; commits via per-surface allowlist `.gitignore`s; preamble recovery sweep backstops missed windows. | n/a — required | 40 §8.1, §10.1; [Cowork plugins reference §monitors](https://code.claude.com/docs/en/plugins-reference); 51-cowork §7 |
| Version-control or archive-bundling primitive | git per surface (visible `BeCivic/` root + `${CLAUDE_PLUGIN_DATA}` root) for atomic commit history; `scripts/bc_export.py` / `scripts/bc_import.py` tarball (`git bundle` per surface + manifest) for cross-machine portability | n/a — required | 40 §10.1; 51-cowork §7.3, §12 |
| Wire access to the platform | REST via `WebFetch` against `https://becivic.be/api/*` — primary surface. `mcp__plugin_be-civic_becivic__*` is a sunset surface retained as fallback. | n/a — required | 40 §10.1; 50-harness §10; 51-cowork §12 |
| Network access | Agent HTTPS via the Cowork runtime's network stack (no plugin-specific config required) | n/a — required | 40 §10.1 |

---

## Optional capabilities (40 §10.2)

| Capability | Cowork mechanism | Degraded fallback | References |
|---|---|---|---|
| Widget rendering | `mcp__visualize__show_widget` — used by `bc-onboarding` for the branded email-capture form and onboarding framing | Chat-driven Section 1 capture: harness collects email, name, and region via conversational turns | 40 §10.2; 51-cowork §11A |
| Image / vision input | Agent vision on user-supplied document images (no plugin-specific binding; uses substrate runtime capability) | Manual data entry: user reads and transcribes document content; harness prompts field by field | 40 §10.2 |
| Browser automation | `mcp__claude-in-chrome__*` when present; preamble `detect-browser-capability.py` reports availability at session start | Text-only step-by-step portal walkthroughs (no live narration) | 40 §10.2; 51-cowork §9 |
| Native file picker | `mcp__cowork__request_cowork_directory` at first contact for `${SUBSTRATE_DATA}` parent selection | Text prompt: harness asks for an absolute path and validates it | 40 §10.2; 51-cowork §11 |

---

## Portability (bc-export / bc-import)

`scripts/bc_export.py` and `scripts/bc_import.py` implement the 40 §9
export/import rituals for the Cowork binding.

**Bundle format:** `bc-export-<UTC-timestamp>.tar.gz`

```
manifest.json          version markers, export metadata, identity_excluded flag
surfaces/
  data.bundle          git bundle of the visible surface (SUBSTRATE_DATA)
  state.bundle         git bundle of the hidden surface (SUBSTRATE_STATE)
```

**Identity handling.** The hidden surface's `.env` (harness_key) is gitignored
by construction — it is absent from the allowlist in `${SUBSTRATE_STATE}/.gitignore`,
so it is never committed and therefore never appears in a `git bundle`. The export
script verifies this property before proceeding. `identity_excluded: true` is
recorded in `manifest.json`. The user-facing warning at export time:

> Your harness key (.env / BECIVIC_HARNESS_KEY) is NOT included in this bundle.
> Identity stays on THIS machine only. On the destination machine you will need
> to re-verify your email via the Be Civic onboarding flow, or rotate your
> existing key (POST /api/auth/rotate-key).

**Post-import state.** The imported substrate is in "returning user, needs to
re-verify" state. The gate skill detects the bc-import bundle / marker and
routes into the bc-onboarding imported-state branch, which frames the session
as: "Welcome back — let's get your key set up on this machine."

See also: 40 §9.1 (abstract export contract), 40 §9.2 (abstract import
contract), 51-cowork §12 (Cowork binding specifics).
