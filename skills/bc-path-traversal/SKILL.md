---
name: bc-path-traversal
description: Walk the user step-by-step through a Belgian-administration procedure once onboarding has captured the profile and the procedure has been routed. Owns the Path Directory traversal contract — batched-phase loop, browser-driven site discovery, browser_driving_preference honouring, eligibility-first / commune-last / consent-before-audited-delivery invariants, inline-commit path-source validations on each attempt. Hands off to bc-onboarding (returning mode) when the user signals a new procedure mid-session. Hands back to the harness at procedure completion.
version: 1.0.0
requires_capabilities:
  - multi_turn
  - structured_output
  - tool_execution
peer_skills:
  - bc-onboarding
  - bc-discovery
  - bc-document-handler
  - bc-session-close
---

# Be Civic — Path Traversal

This skill walks the user, one phase at a time, through a verified Belgian-administration procedure. The procedure canonical is the script; the Path Directory is the route to each document or tool the script names; the user owns every appointment, signature, and visit to a service desk.

Trust posture is conservative. The skill never invents a path that is not in the catalogue, never proceeds past an audited delivery without per-call consent, never drives a browser the user said not to drive, never claims a step succeeded without checking the validation signal the catalogue specified. Failures are surfaced plainly; the user is told what is next; nothing happens silently.

## Step 1 — Inputs from onboarding

The skill enters with three artefacts already on disk from `bc-onboarding`:

- `profile.json` at the BeCivic root — region, commune, civic_status, residency_status, conversation_language, administration_language, preferred_name, `has_id_card`, `browser_driving_preference`, and the `consent` block.
- `procedure_progress.md` inside the project subfolder — empty on first entry, accumulated narrative on returning entries.
- A procedure id resolved by the harness during onboarding (the `process_id` returned by the manifest lookup). The id is the only thing the harness needs to hand over — everything else is read from the artefacts above.

If `profile.json` is absent, do not improvise; route the user back to `bc-onboarding` in `first-contact` mode and exit. If the procedure id is absent, ask the user what they want to work on and route back to `bc-onboarding` for routing.

## Step 2 — Fetch the procedure canonical

Call `WebFetch GET https://becivic.be/api/processes/<id>` with header `Authorization: Bearer <harness_key>` (read from `${SUBSTRATE_STATE}/.env` as `BECIVIC_HARNESS_KEY`; omit the header if the key is absent and operate at the public tier). On success the response envelope is `{ "status": 200, "data": { ... } }`; the canonical markdown body is at `.data.body`. The body also carries frontmatter — `inputs`, `requires`, `requires_paths`, `applies_to` — and the `[Process]` body with inline `<Path>` and `<Process>` tags.

Read the body to extract the phase structure. Procedure canonicals are organised as named phases (eligibility check, document collection, filing, post-filing). The `requires_paths:` frontmatter lists every path the procedure needs across all phases; the inline `<Path id="…" />` tags inside `[Process]` steps anchor each path to the phase where it is consumed. Use the inline tags as the phase markers — the position of a `<Path>` tag determines when it is fetched, not the order in `requires_paths:`.

Cache the canonical body in working memory for the rest of the session. Do not re-fetch on every phase.

## Step 3 — Discover paths

Two surfaces inform path discovery, in order:

1. **The procedure's declared paths.** Build the working set from the canonical's `requires_paths:` frontmatter joined with the inline `<Path>` tags in the body. This is the deterministic, corpus-grounded list.

2. **Browser-driven site discovery — only when needed.** Some path sources gate on commune-specific or region-specific portal behaviour the canonical cannot enumerate (a Brussels-only deeplink, a Wallonia population-register sitemap page, a federal CSAM auth wall that re-clicks differently per portal). When the user's profile points at a region or commune whose path source is not deterministic from the catalogue, call `mcp__Claude_in_Chrome__list_connected_browsers` to confirm the user has a paired browser. If paired, use the browser automation tool to navigate the portal and confirm the deeplink the catalogue cites still resolves before walking the user to it. Site-discovery probes are read-only: navigate, read page text, screenshot if needed, never submit a form.

3. **`GET /api/paths/<id>` for surface enumeration.** When the procedure references a path id whose entry the catalogue has multiple sources for, call `WebFetch GET https://becivic.be/api/paths/<id>` (Bearer when present) to enumerate the catalogued sources and their source list. To fetch a single source, call `WebFetch GET https://becivic.be/api/path-sources/<path_id>:<source_id>`. Filter by the user's profile fields (region, residency_status) before presenting any source to the user — eligibility-first invariant applies at discovery, not just execution.

Do not probe an audited source (`audited_document_delivery: true`) during discovery. Probing is a real document delivery; the user has not consented yet.

## Step 4 — Honor `browser_driving_preference`

Read `browser_driving_preference` from `profile.json`. Three values; behaviour for each is sticky for the session and never re-asked:

- **`drive-by-default`** — agent drives the user's paired browser via browser automation up to authentication walls. At each auth wall, hand off using the source's `actor.handoff` text and pause for the user to sign in. Resume on the user's signal (typically "got it" or a downloaded file).
- **`ask-each-time`** — agent presents the source's deeplink, the agent-responsibility and user-responsibility text, and an explicit choice for this step: drive the browser, or hand over the link. The user's choice on this step does not bind subsequent steps; the next browser-needing source asks again.
- **`never-drive`** — agent never invokes browser automation for navigation; every source is presented as a clean markdown link with the user-responsibility text, and the user clicks themselves. Validation signals for these sources come from the user reporting back what happened ("got it" / "couldn't find the link" / "got a 404"), not from agent-observed page state.

If `browser_driving_preference` is `drive-by-default` but no browser is paired, do not silently downgrade. Surface once: "Your preference is set to drive your browser, but I can't see a paired browser. Want to pair Chrome and the Be Civic extension now, or hand you links for this session?" The user's answer either pairs the browser (preference stands) or updates the preference to `never-drive` for the session.

## Step 5 — Batched phase loop

The skill walks one phase at a time. Each phase is a group of related `[Process]` steps in the canonical that share a logical boundary — usually "collect these documents," "complete this filing," "wait for this acknowledgement." Phases are inferred from the canonical's section headers and the position of inline `<Path>` tags.

At the start of each phase, name it plainly to the user — what is happening in this phase, what documents or actions it produces, roughly how long it takes. Then iterate:

For each step in the phase, in canonical order:

1. **Advance.** Read the next step's body. If the step body is wrapped in `<Risk>`, slow down and name the stakes before proceeding; the wrapped step describes an irreversible routing call the user must understand before acting.

2. **Resolve inline tags.** If the step contains `<Path id="…" />`, the path is the step. Move to step 3. If the step contains `<Process id="…" />`, peer-invoke that procedure skill via `Skill` and return here when it exits. If the step is prose only, present it to the user, take their answer, and move on.

3. **Fetch the path entry.** Call `WebFetch GET https://becivic.be/api/paths/<id>` (Bearer when present) for the cited path id if the catalogue has not already been fetched this session. Filter the source list by the user's profile (eligibility-first invariant). Sort: non-fallback before fallback; within each, by `priority` descending. `source_class: offline` sources are always last (commune-last invariant).

4. **Validate path source per attempt.** Execute Step 6 below for each source attempt in turn until one succeeds or all are exhausted.

5. **Record artefact and move on.** On success:
   - Write the artefact filename and the producing source id to `${SUBSTRATE_DATA}/<procedure-slug>/procedure_progress.md` (VISIBLE surface, user can see this in their file manager).
   - Update the step's status in `${SUBSTRATE_STATE}/procedures.json` (HIDDEN registry) to mark it complete. The registry tracks overall procedure state; `procedure_progress.md` is the human-readable narrative.
   Move to the next step.

At the end of each phase, summarise what was produced and what is next, then advance to the next phase.

If a phase fails entirely (every source for a required path was exhausted), pause and offer the user three choices: search online directly, prepare a commune visit (commune-last invariant: only at this prompt), or pause the procedure and come back later. Do not skip the phase silently.

## Step 6 — Inline-commit path-source validations

Each source attempt produces a structured outcome. The validation submission is inline-commit — no buffer, no session-close approval — because path-source validations are anonymous-by-construction (no identity, only a source id, a verdict, and an optional structured rationale) and the catalogue needs the signal in real time to learn which sources are rotting.

For every source attempt:

1. **Consent gate.** If the source is flagged `audited_document_delivery: true`, present the per-call consent surface in plain English: what authority will produce what document, whether there is a fee, whether the document is mailed, that this is real and not a preview. Obtain explicit consent for this call. Per-source consent does not extend to other sources; agreeing to fetch a marriage certificate does not extend to a residence certificate.

2. **Handoff text.** If `actor.handoff.when` is not `none`, surface the source's `agent_responsibility`, `user_responsibility`, and `resumption` text to the user before executing. Frame as: here is what I will do, here is what you will need to do, here is how we pick up after. Never hand off silently.

3. **Execute per source class.** A `deeplink-after-auth` source drives the browser to the deeplink (if `drive-by-default` and a browser is paired) or presents the link (otherwise) and pauses for the user to authenticate. A `wallonia-sitemap-page` source loads a public page and lets the user navigate. A `federal-auth-handoff` source presents the federal portal URL. An `offline` source emits a commune-visit checklist (contact, hours, documents to bring) and pauses for the user to act in the world.

4. **Validate against `validation_path`.** Apply the success and failure signals the source declared. For a tier-1 deeplink, this is a content-type and PDF-magic check on the downloaded artefact. For a sitemap page, the user's verbal confirmation. For a federal form, a success-page signature. Use the source's signals, not general knowledge.

5. **Submit the validation, inline.** Path-source validations bypass the observation buffer and POST directly. On success or failure:
   a. Generate a `submission_id` by running `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gen_submission_id.py validation` (yields `val_<uuidv7>`).
   b. Build the submission body:
      ```json
      {
        "schema_version": "1.0",
        "submission_id": "<generated>",
        "submitted_at": "<RFC3339 UTC now>",
        "submitting_harness": "be-civic-plugin/0.3.0",
        "submitting_model": "<active model id>",
        "submission_contract_version": "1.0",
        "target_type": "path_source",
        "target_id": "<source-id>",
        "verdict": "confirm|reject",
        "rationale": "<structured failure signal if reject, e.g. '404 on quicklink URL'>",
        "context": { "language_used": "<profile.conversation_language>" }
      }
      ```
   c. `WebFetch POST https://becivic.be/api/validations` with `Authorization: Bearer <harness_key>` and the body above. Expected response: `202 { "status": 202, "data": { "submission_id", "accepted_at", "cancel_token" } }`. Persist `cancel_token` in the session buffer for 48h cancellation.
   d. Frame once per session: "I'm noting that this source worked / didn't work for you, so the next person filing this sees the same."

   If the POST itself fails (network error), retry once. If still failing, append the unsent validation as a JSONL line to `${SUBSTRATE_STATE}/sessions/<session_id>/observations-buffer.jsonl` and continue — do not block the user on a telemetry hiccup. The fallback chain in Step 13 governs this case in full.

## Step 7 — Mini-header rotation

At the start of each phase boundary and at the start of the session if entering through this skill (a returning user whose harness loaded the procedure), surface one mini-header callout. The plugin ships ten rotating strings at `${CLAUDE_PLUGIN_ROOT}/data/mini-header-strings.md`; rotate through them round-robin so the same string is not surfaced twice in adjacent invocations. Do not fire the mini-header on every message, every step, or every source attempt — only at phase boundaries and on session-active re-entry.

The mini-header signals to the user that the procedure work that follows is grounded in the Be Civic catalogue, not improvised. If the session shifts away from procedure work (the user asks a meta question, the user pivots to a non-procedure topic), the mini-header does not re-fire when procedure work resumes mid-session unless a new phase boundary is crossed.

## Step 8 — Mid-session new-procedure trigger

When the user signals an intent that does not fit the current procedure mid-traversal — "I also need to update my address," "actually first my mum just arrived from Tunisia and needs residency" — stop the current step, name the pivot, and hand back to `bc-onboarding` in `returning` mode with the new procedure id. The handover passes the existing `profile.json` snapshot; `bc-onboarding` runs the new procedure's Section-2 routing form without re-asking Section 1, creates a new project subfolder under the existing BeCivic root, and returns control to a fresh invocation of this skill for the new procedure.

The original procedure is parked, not abandoned. Write the current phase and the last completed step to `${SUBSTRATE_DATA}/<procedure-slug>/procedure_progress.md` and update the status in `${SUBSTRATE_STATE}/procedures.json` before pivoting. When the user wants to resume the original procedure later, the harness reads `procedure_progress.md` and `procedures.json` and re-enters this skill at the parked phase.

Both procedures coexist under the BeCivic root. The user can have nationality, address-change, and apostille running in parallel — same profile, different project subfolders, different `procedure_progress.md` files. Confirmation that a pivot is wanted always uses the confirmation-gate copy: "Of course — we'll park the [current procedure] where it is. Would you like me to set up a new project for [new procedure] inside your existing Be Civic folder?"

## Step 9 — Feedback emission

Two channels for feedback against path-step quality:

- **Path-source validations** — the inline-commit channel covered in Step 6. Per attempt, anonymous-by-construction, no buffering.
- **Issues against path or process quality** — buffered, surfaced at session close. When the user reports that a document name is wrong, a fee figure is stale, a step description misses a commune-specific detail, the path catalogue has a gap, or the canonical body is unclear, do not POST inline. Append a JSON line to `${SUBSTRATE_STATE}/sessions/<session_id>/observations-buffer.jsonl` with the appropriate `target_type` and `label`, then let `bc-session-close` present each item to the user for per-item approval before submitting `POST /api/issues`.

  Route to the correct Issue shape:
  - Scoped path issue → `target_type: path`, `label: bug|missing|divergence`.
  - Specific source concern → `target_type: path_source`, `label: bug|rotted|divergence`.
  - Fee or date discrepancy → `target_type: volatile_value`, `label: rotted`.
  - Process canonical-body issue → `target_type: process`, `label: bug|missing|divergence`.
  - Gap (new process proposal) → `target_type: knowledge_graph`, `label: gap`, include `evidence.knowledge_graph.proposed_process_id`.

  JSONL record shape (one line, no trailing comma):
  ```json
  { "target_type": "…", "target_id": "…", "label": "…", "title": "…", "body": "…", "context": { "language_used": "…" } }
  ```

  `bc-session-close` generates the `submission_id` (via `gen_submission_id.py issue`) and POSTs at session end after per-item user approval. Name the issue type and routing to the user when surfacing the item at session close.

## Step 10 — Completion and handback

When every phase of the procedure has completed and every required artefact is in the project's `documents/` folder, summarise the procedure end-to-end for the user in plain language: what was filed, what is in the folder, what the user is waiting on from the authority, and what the user should do next outside the agent (an appointment, a postal acknowledgement, a follow-up after a statutory delay).

Write a closing entry to `${SUBSTRATE_DATA}/<procedure-slug>/procedure_progress.md` naming the completion date and the final artefact set. Update `${SUBSTRATE_STATE}/procedures.json` to remove the completed procedure id from `active_procedures`. Hand back to the harness — there is no automatic exit to a next procedure; the user may close the session here, or continue with a different procedure via the harness's normal routing.

If the procedure does not complete in this session (user paused, awaiting an external step like a commune appointment, awaiting a postal acknowledgement), do not synthesise completion. Write the pause reason and the next concrete user action to `${SUBSTRATE_DATA}/<procedure-slug>/procedure_progress.md` and update the status in `${SUBSTRATE_STATE}/procedures.json`. Exit cleanly. The next session's harness reads `procedure_progress.md` and `procedures.json` and re-enters this skill at the parked phase.

## Step 11 — Failure and fallback

Three failure surfaces, in order of escalation:

1. **A single source failed its validation_path** — submit `reject` inline, move to the next source in the ordering. Standard, expected behaviour. Continue without naming the failure as a session-level concern; the catalogue's validation aggregator handles the signal.

2. **Every source for a required path is exhausted** — surface the all-sources-exhausted prompt at the end of the phase. Three choices for the user: search online for another route (agent emits authoritative-source URLs and closes the path), prepare a commune visit (agent emits a NIS5-specific checklist and closes the path), pause the procedure (agent writes pause state and exits). The fourth option — discovery mode — fires only if the user volunteers willingness to walk through the procedure and document what they find. Route to `bc-discovery` in `path` mode in that case.

3. **REST API unreachable** — fall back per the harness CLAUDE.md §6 fetch chain. First attempt: `WebFetch GET https://becivic.be/api/paths/<id>` (and `/api/processes/<id>`). On persistent failure: `WebFetch GET https://becivic.be/paths/index.json` (static catalogue fallback). If all layers fail, surface the catalogue-unreachable state plainly: "My full Be Civic library isn't reachable right now. I can describe what I know about the procedure, but I can't walk you through getting the documents until the library is back." Continue advice-only; do not invent paths from general knowledge. Append a `process_surface` issue to the observation buffer at session close noting the unreachable window so the operator sees the outage.

User-facing message for catalogue unreachable: do not pretend the agent is working at full capacity. Name the degraded state, offer to continue with what is locally available (the canonical body cached in memory, profile.json) and to defer document-fetching steps until the library is back, or to pause the session entirely. The user picks.

## Step 12 — Multi-active project handling

A user may have multiple Be Civic projects active concurrently under the same BeCivic root — nationality, address-change, apostille, family-reunification — each in its own project subfolder. This skill is scoped to one project at a time. The harness names which project is in focus when invoking the skill; this skill reads `procedure_progress.md` from that subfolder, writes back to the same one, and never reaches across subfolders to read a different procedure's state.

If the user signals a switch to a different active project mid-session ("can we set my mum's residency aside for a minute and get back to my citizenship?"), park the current project's state per Step 8 and hand back to the harness. The harness re-enters this skill with the other project in focus. Profile is shared across projects; `procedure_progress.md` is per-project.

Project switching always crosses through the harness, never directly between two invocations of this skill. The harness owns project-focus; this skill owns the active procedure's traversal.

To start a brand-new procedure mid-session, route back to `bc-onboarding` in `returning` mode per Step 8 — the harness handles `returning` and `multi-active` modes, not this skill.

## What this skill does not own

- Procedure routing and Section-1 / Section-2 capture — `bc-onboarding`.
- Document handling once delivered (extraction of routing fields from the artefact) — `bc-document-handler`.
- The unknown-path or all-sources-failed escalation walkthrough — `bc-discovery` in `path` mode.
- Session-close review and submission of buffered concerns and amendments — `bc-session-close`.
- The path catalogue itself — read via `WebFetch GET https://becivic.be/api/paths/<id>`.

