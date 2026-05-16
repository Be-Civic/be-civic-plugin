---
name: bc-path-traversal
description: Use when the harness encounters an inline Path tag in a canonical body, a frontmatter requires_paths entry at filing or document step, or a customer-initiated path request. Owns the spec section 6.12 traversal contract — catalogue load, three invariants, per-source execution with handoff gates, validation submission, capability-aware degradation, discovery-mode default on exhaustion.
---

# Be Civic — Path Traversal

## 1. Triggers

Per CLAUDE.md §6a inline-tag handling:

- **Inline `<Path id="..." />` tag** in the procedure body — the common case. The tag IS the cue; don't wait for a separate "step" or "now we'll get the document" beat. Invoke immediately on encounter.
- **Frontmatter `requires_paths:` entry** reached at filing/document step (when parked at onboarding per CLAUDE.md §7a, the batch fetch beat runs each parked path in sequence).
- **Customer-initiated** ("can you help me get certificate X?") when intent matches a catalogued path.

## 2. Execution modes — split by `purpose:` field

- **Document-fetch purpose** (the common case — `submission` / `preparation` / `check-only` / `handoff`): traversal pulls or produces a document. Run the source-by-source algorithm in §4 under the three invariants in §3.
- **`purpose: tool` paths** (a live online tool — commune appointment booker, federal e-form, MyMinFin): traversal offers to navigate the customer to the tool's URL rather than handle data itself. Surface as: "this step uses [tool name]. I'll open it for you — when you're done, come back and tell me what happened." For `purpose: tool` sources flagged `audited_document_delivery: true`, the per-call consent gate in §3 still applies before the URL is offered.

## 3. Three invariants (must hold at every step)

- **Eligibility-first.** Never attempt a source whose `audience.predicates` don't match the customer profile. Filter the source list once at the top of traversal; never relax this mid-loop.
- **Commune-last.** Never suggest a commune visit until every online source has been tried. By schema invariant, `offline` sources carry `fallback_only: true` — sort accordingly.
- **Consent-before-audited-delivery.** Per-call (not per-session) explicit consent for sources flagged `audited_document_delivery: true`. Plain-English explanation of what audited delivery means (§6). Customer agreeing to fetch a marriage certificate does not extend to a residence certificate.

## 4. Core algorithm

### 4.1 Catalogue load

Read `cache/paths-index.json` populated by inline fetch per CLAUDE.md §6 (MCP → HTTP → WebFetch). On persistent failure (all three layers): tell the customer plainly "I can describe the procedure but can't walk you through getting it" and emit a `skill_surface` observation flagging the catalogue-unreachable state. Continue advice-only — do NOT invent paths from general knowledge.

### 4.2 Path lookup

Look up by id. On miss, return a structured signal to CLAUDE.md (`unknown-path-id`); CLAUDE.md routes to `bc-discovery` in path mode. Do NOT synthesise a path from general knowledge.

### 4.3 `applies_to` check

Validate the path's `applies_to` against the customer's profile. Mismatch → surface plainly ("this path is for [region/civic status], doesn't apply to your situation") and skip. Don't proceed.

### 4.4 Source filtering and ordering

- Filter sources by `audience.predicates` against the profile (eligibility-first invariant).
- Within the surviving set, sort: non-fallback before fallback; by `priority` ascending within each tier. `offline` sources go last (commune-last invariant).

### 4.5 Per-source attempt — three gates

Before executing each source:

1. **Audited-delivery gate** — for sources flagged `audited_document_delivery: true`, AskUserQuestion with a plain-English explanation: "this will request a real, official document — logged on the government's side, usually with a fee, sometimes mailed to your address. Not a preview. OK to proceed?" Per-call, not per-session.
2. **Handoff gate** — read `actor.handoff.when`; surface `agent_responsibility` / `user_responsibility` / `resumption` text to the customer. Frame as "here's what I'll do, here's what you'll need to do, and here's how we pick up after."
3. **Unobserved-flow caveat** — when `post_handoff_observed: false`, tell the customer once: "after [handoff point] I won't see what happens on your screen. Tell me when you're back."

### 4.6 Runtime capability gate

Read `PATH_TRAVERSAL_CAPABLE` and `PATH_HANDOFF_CAPABLE` from preamble session state.

- **Both present** → execute the source normally.
- **Missing or unknown** → do NOT silently skip. Surface a setup nudge: "this route needs Chrome installed and the Be Civic MCP connected; want me to walk you through that now? About a minute." Only fall through to advice-only if the customer declines setup.

### 4.7 Execute

Per `source_class`: deeplink walk (browser MCP), form-fill where capability allows, or offline checklist emit (e.g., "bring these items to the commune"). The execution detail lives in the source row's `instructions` field; follow it.

### 4.8 Validate

Validate the produced document or completed action against `validation_path` per the source's `source_class` template (per schemas.md §6.12.3 if/then branches). The path entry carries the validation rules; apply them, not general knowledge.

### 4.9 Submit validation

Per attempt: call `mcp__becivic__submit_path_source_validation`, falling back to HTTP POST to `https://becivic.be/api/path-validations` if MCP is unavailable. On success: `verdict: confirm`. On failure: `verdict: reject` with structured `rationale`. Validations commit immediately — no 24h staging — so frame this for the customer as "I'm logging that this worked / didn't work for you, so the next person sees the same."

### 4.10 Pause state

If the customer pauses mid-traversal for capability setup or for an external step ("I need to come back after my appointment"), write `.be-civic/sessions/<session_id>/path-traversal-state.json` carrying `{path_id, source_id_in_progress, attempted_sources, pending_attempts, paused_at, reason}`. The next session's pending-state scan surfaces this so the customer resumes mid-walk, not back at the start.

## 5. All sources exhausted — discovery is the default

When every source in the path's source list has been tried and failed, push discovery mode as the **recommended** option, not one of four equal-weight choices. The framing biases for contribution AND glosses "discovery mode" on first use:

> "We've tried every catalogued source for [path name] and none worked. The most useful thing right now is to switch to discovery mode (where we walk through this together and document what we find for the next person) — you'd be the first to map this for Be Civic, and the next person filing this won't hit the same wall. Want to do that?"

AskUserQuestion with discovery as the recommended option:

- **A) Discovery mode (recommended)**
- B) Search online — I'll give you pointers
- C) Visit your commune — I'll prep a checklist
- D) Skip for now

On **A**: return `all-sources-failed-with-alternative` signal to CLAUDE.md with the customer's volunteered context (if any); CLAUDE.md routes to `bc-discovery` in path mode.

On **B**: emit a short list of authoritative-source URLs the customer can try; close the traversal.

On **C**: emit a commune-visit checklist (NIS5-specific contact, hours, documents to bring); close the traversal.

On **D**: close the traversal silently; pending-state carries the unfinished traversal forward if the customer wants to come back.

## 6. Audited document delivery — customer-facing explanation

A source flagged `audited_document_delivery: true` produces a real, official document on each invocation. Logged on the government's side. Often with a fee. Sometimes with physical delivery to the customer's address. Not a preview. Not a test. Real.

The harness MUST obtain explicit per-call consent. Customer agreeing to fetch a marriage certificate does not extend to a residence certificate.

Plain-English script (use roughly this wording, adapt to context):

> "Quick check before I do this: this will request a real, official [doc type] from [authority]. They'll log the request on their side. [If fee: There's a fee of around X EUR — I'll confirm the current figure before you pay.] [If postal: They mail it to your address; takes a few days.] OK to proceed?"

## 7. Exit conditions

- Document produced + validation submitted (`verdict: confirm`) → return to the procedure body at the tag site.
- All sources failed + discovery chosen → return `all-sources-failed-with-alternative`.
- Customer paused → write pause state, exit with `paused`.
- Customer declined a required capability nudge → exit with `capability-blocked`.
- Catalogue unreachable → exit with `catalogue-unreachable`; CLAUDE.md continues advice-only.

In every case the closing turn names what's next — never leave the customer on a hanging "OK" with no framing.

## What this skill does NOT own

- Path drafting. That's `bc-path-drafter` (subagent spawned by `bc-session-close`).
- Document handling once delivered (extraction of routing fields). That's `bc-document-handler` rules (CLAUDE.md §7) or the inline handler if §7 covers it.
- The path catalogue itself. The skill reads the catalogue; the catalogue lives in `data/paths.json` on the corpus side.

## Authoring source

Lifts from bootstrap.zip's `skills/becivic/SKILL.md` §31 (Path Directory traversal). Schema references: schemas.md §6.12; protocol.md §23.2.1 (MCP tool names). Discovery-as-default framing and the round-7.3 `<Path>` inline-tag trigger are new content per the W22 sprint plan.
