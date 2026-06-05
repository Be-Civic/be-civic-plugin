# Preamble recovery — the manual preamble

**Trigger + scope.** Read this when the preamble (harness §3) did not run, errored, or emitted `PREAMBLE: fallback_active`, AND you resolved `BC_ROOT` (so this file is reachable). It is the by-hand version of `scripts/preamble.py`: derive the session-disposition facts yourself from the state files, then greet from the matched fallback shape below. Because the canary/framing prose now lives in the preamble, a preamble failure means you have NO `SESSION_OPENING_INSTRUCTION` to follow — this file is its replacement. If `BC_ROOT` did not resolve either, you can't read this file; fall back to the minimal inline recovery in harness §3 (derive the disposition from the state files and greet specifically).

> **Deliberate duplication — do NOT "fix".** The four opening shapes below are a hand-copy of `preamble.py`'s `emit_session_opening_instruction`. This duplication is intentional resilience: the preamble normally emits these, but when it has failed this is the only home for them. A JIT-instruction audit should treat this as a sanctioned single-purpose copy (recovery surface), not a single-home violation. Keep the two in sync when either changes.

## Resolve the surfaces by hand

| Surface | How to resolve | Tool |
|---|---|---|
| `BC_ROOT` (install) | Manifest-find, same as harness §3: `find /sessions "$HOME/.claude/plugins" /root/.claude/plugins -maxdepth 8 -path '*/.claude-plugin/plugin.json' -exec grep -l '"name": "be-civic"' {} +` → `dirname dirname`. (If empty, this file isn't reachable — use the §3 inline recovery.) | `bash` |
| `SUBSTRATE_DATA` | The directory that contains *this* loaded `CLAUDE.md` (= the folder holding `.be-civic/marker`). | — |
| `SUBSTRATE_STATE` | `${SUBSTRATE_DATA}/.be-civic/state`. | — |

**The state files are host-`Read`-able** — `profile.json`, `preferences.json`, `procedures.json`, `.env`, `.pending-verification` all live in the user's own project folder, NOT inside the bash-only plugin install. So you can read them with the host `Read` tool even when the preamble *script* couldn't run. (Only `${SUBSTRATE_ROOT}` plugin assets need bash.)

## Derive each disposition fact by hand

Mirror exactly what `emit_session_facts()` computes. Read the three state files once, then:

| Fact | Source | Rule |
|---|---|---|
| `SUBSTRATE_DATA` absent | no folder / no marker | → `first_contact`. Invoke `bc-onboarding`; no canary. Stop here. |
| `PENDING_VERIFICATION` | `${SUBSTRATE_STATE}/.pending-verification` exists | present → mid-ceremony resume (harness §3.2); checked FIRST, before the marker. |
| `HARNESS_KEY` | a `BECIVIC_HARNESS_KEY=<non-empty>` line in `${SUBSTRATE_STATE}/.env` | presence ONLY — never read or echo the value. Absent + marker present → keyless half-state (harness §3.0 / `bc-onboarding` verification-only mode); make NO wire call. |
| `CARRYOVER_LANG` | `preferences.json` → `conversation_language` (non-empty string) | absent → ASK which language; never default to English. |
| `PROFILE_CAPTURED` | `profile.json` → `last_updated_at` | `not in (null, "", "null")` → `yes`; else `no`. Missing file reads `no`. |
| `ACTIVE_PROCEDURE_COUNT` | `procedures.json` → `procedures[]` | count of entries with `status == "active"` (absent `status` treated as active). |
| `CARRYOVER_PROCEDURE` | the single active entry | `process_title` → else `title` → else `slug`. (`intake` / `to be routed` → treat as "your procedure".) |

The scenario then follows the same ladder the preamble uses:

- `first_contact` — `SUBSTRATE_DATA` absent (above).
- `first_working` — `PROFILE_CAPTURED: no` (folder exists, about-you form not run).
- `multi_active` — `PROFILE_CAPTURED: yes` AND `ACTIVE_PROCEDURE_COUNT > 1`.
- `returning_none` — `PROFILE_CAPTURED: yes` AND `ACTIVE_PROCEDURE_COUNT == 0`.
- `continuing_one` — `PROFILE_CAPTURED: yes` AND `ACTIVE_PROCEDURE_COUNT == 1`.

## The fallback opening shapes

Greet from the ONE matched shape. Fill `<procedure>` / `<A>` / `<B>` from the facts above; **phrase the real greeting in `CARRYOVER_LANG`** (the examples are illustrative English). Greet SPECIFICALLY — naming the procedure in the user's language is what proves the harness loaded; never a generic "how can I help?", never a dead-end.

**first_working** (`PROFILE_CAPTURED: no`):
> First working session (the about-you form has not run yet). Greet SPECIFICALLY, naming the carried-over procedure. Do NOT say "welcome back"; this is the first time. Name the procedure, say a few quick questions about their situation come next, then you work through it together. After the greeting, invoke `bc-onboarding` (first-working-session mode), which fetches the canonical, renders the about-you form, and commits the profile sentinel.
>
> *Example: "Hi — I've loaded Be Civic's guide for your **<procedure>**. Since it's our first time, I'll start with a few quick questions about your situation, then we'll work through it together."*

**continuing_one** (`PROFILE_CAPTURED: yes` + one active):
> Continuing project. Greet naming the procedure and offering to pick up where you left off. NUANCE (yours): if the user's first message asks for something ELSE, this is `returning`, not `continuing` — acknowledge the in-flight procedure but follow their lead, pivoting per `bc-path-traversal` without losing it.
>
> *Example: "Hi again — I've got your **<procedure>** loaded and I'm ready to pick up where we left off."*

**multi_active** (`PROFILE_CAPTURED: yes` + more than one active):
> Multi-active project. Greet naming the active procedures, then ask which to work on today (let the user pick; once they pick, treat it as continuing).
>
> *Example: "Hi again — you've got two things going, **<A>** and **<B>**. Last time we were further along on one of them. Which would you like to work on today?"*

**returning_none** (`PROFILE_CAPTURED: yes` + zero active):
> Returning project, no active procedure. Greet naming the project and (if you can see it in `MEMORY.md` / the registry's completed entries) the most recent procedure, then ask what they want to look at today. You have notes from before — do not re-ask routing fields you already hold; if a field changed, confirm and update.
>
> *Example: "Hi again — your Be Civic project's loaded. Last time we wrapped up your **<most recent>**. Has anything changed since we last spoke? What would you like to look at today?"*

## Capability detection by hand

The preamble normally emits capability flags; derive them yourself from your own tool list and degrade to what's present:

| Capability | Check | If absent |
|---|---|---|
| Reads (library) | `WebFetch` in your tool list | no library reads — operate from general knowledge, flag reduced confidence. |
| Writes (submissions, verification) | `scripts/wire.py` reachable at `$BC_ROOT/scripts/wire.py` | no submissions / no email→code — tell the user the verified library can't be reached. |
| Forms | `mcp__visualize__show_widget` in your tool list | no rendered form — fall back to AskUserQuestion / chat for intake. |
| Browser (path discovery) | a browser-control tool in your list | ask the user once at the first browser-needing step, don't pre-empt. |

## What to SKIP / degrade (do NOT fabricate the preamble's side effects)

The preamble does disk + git work you must NOT simulate by hand:

- **Schema migrations** — do not attempt; if state looks stale, proceed read-mostly and note it.
- **Writable probe** — you have no verdict. If you can't confirm `${SUBSTRATE_STATE}` is writable (a `Write` succeeds), tell the user state/submissions may not persist this session.
- **Orphan-buffer sweep / pending-state scan** — skipped. Treat any unsubmitted observation/research files older than this session as pending; surface at session close.
- **Per-session state init** (`SESSION_ID`, session dir) — generate a session id yourself if you need one; do not assume the session dir exists.

Operate read-mostly. Prefer reads over writes; gate every write on a confirmed-writable check.

## Tell the user once

If the failure changes what you can do (no writes, no forms, no library), say so plainly, once, in `CARRYOVER_LANG` — e.g. *"Quick heads-up: I'm running in a limited mode this session, so I may not be able to save progress or send anything back. I can still walk you through your **<procedure>**."* Then proceed. Do not repeat it every turn.
