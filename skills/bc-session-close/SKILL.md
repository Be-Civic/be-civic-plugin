---
name: bc-session-close
description: Use on procedure terminal step, explicit customer close, session end, or pending-state submit-now branch. Runs the 9-step close sequence — summary, save state, per-item observation review, drafter handoff for ready research-notes, contributions double-filtered, direct typed submission, defensive dossier check, next-time framing, cleanup, goodbye. Auto-spawns bc-path-drafter and bc-process-drafter sub-agents for ready research-notes.
---

# Be Civic — Session Close

Two invocations:

- **Full close** — procedure terminal step, explicit customer close, session timeout. Runs the 9 steps below in order.
- **Resume-submit** — invoked from the `PENDING_STATE` surface at session open (preamble §4.3). Skip steps 1–2 and 7–9; jump to per-item review (step 3), drafter handoff (step 4), and submission (step 6). Used when the customer chose "handle now" on a deferred item from a prior session — the items live in `${SUBSTRATE_STATE}/sessions/<session_id>/pending-submissions.jsonl` (a prior session's local-buffer fallback).

The customer-facing language for the observation buffer is **list** or **notes**, never "buffer."

## Wire basics (read once)

All submissions are **direct typed POSTs** over `WebFetch` against the REST surface at `https://becivic.be/api`. The per-item user review below IS the gate — it is harness behaviour, not an API call. Once the user approves an item, exactly one POST leaves the machine.

- **Auth.** Read `BECIVIC_HARNESS_KEY` from `${SUBSTRATE_STATE}/.env` and send `Authorization: Bearer <harness_key>` on every submission. Never echo or log the key. If the session is in anonymous-read mode (no key — user declined verification), **no submissions are possible**: tell the customer plainly that their notes can't be sent without verification, offer to verify (hand back to onboarding) or to hold the notes locally (step 6 fallback), and do not POST.
- **submission_id.** Generate client-side before each POST:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gen_submission_id.py <issue|validation|feedback|rating>`
  → prints `<iss|val|fbk|rat>_<uuidv7>`. One id per submission; the worker echoes it back.
- **submitting_harness** = `"be-civic-plugin/0.3.0"`. **submitting_model** = the model running this session with optional effort suffix (e.g. `claude-opus-4-7/xhigh`), per the preamble's model context.
- **NEVER send worker-set fields.** The worker stamps and rejects-if-present: `user_id`, `accepted_at`, `cohort_anchor`, `regex_passes`, `ner_status`, `cancel_token`. Build envelopes from submitter fields only.
- **Accept response.** `202 { "status": 202, "data": { "submission_id", "accepted_at", "cancel_token"[, "cohort_anchor"] } }`. **Persist `cancel_token`** (and the `submission_id` + type) — it is the only handle for the 48-hour cancellation window and cannot be reissued if lost. Branch on the HTTP status first; a non-202 with `{ "error": "<category>", ... }` means the item did not land (handle per step 6).
- **Cancellation (48h).** `DELETE /api/submissions/<type>/<submission_id>` with headers `Authorization: Bearer <harness_key>` + `X-Cancel-Token: <token>`, where `<type>` ∈ `issue|validation|feedback|rating`. Surface the cancel handle to the customer at goodbye (step 7).

## The 9 steps

### 1. Summarise progress

One short paragraph in plain English. What you covered today, what's done, what's still open. Tone is warm and concrete, not a status report. Skip on resume-submit.

### 2. Save state

Update each procedure walked this session: write its visible progress at `${SUBSTRATE_DATA}/<procedure-slug>/progress.md` (last step reached, what's pending, anything the user said worth holding) and refresh that procedure's entry `status` / `updated_at` in `${SUBSTRATE_STATE}/procedures.json`. Skip on resume-submit.

### 3. Per-item observation review (consume the buffer)

Read this session's observation list at `${SUBSTRATE_STATE}/sessions/<session_id>/observations-buffer.jsonl` (on resume-submit, read `pending-submissions.jsonl` instead). One JSON object per line, each an `observation.v3`-shaped item written by `bc-path-traversal` and `bc-discovery` as observations accumulated this session. Inline-commit Validations on path sources (`target_type: path_source`) were already POSTed at traversal time and are **not** in this buffer — do not re-submit them.

For each item:

- Show it in plain English (rendered from the JSON, not the JSON itself).
- AskUserQuestion: approve / edit / discard. (Two options + free-text fallback keeps the gate MECE.)
- On edit: ask what to change, rewrite, re-run `scripts/scrub-layer1.py` against the rewritten version before it is eligible to send.
- On discard: drop the line; do not re-surface.

Apply the CC BY 4.0 grant reminder **once** at the top of this step, not per item: "Anything you approve is shared anonymously under CC BY 4.0. You can cancel anything within 48 hours of submission — I'll give you the cancel codes after we send."

Approved items carry forward to step 6 for submission. The buffer file itself is deleted in step 8, only after every item is submitted, discarded, or written into `pending-submissions.jsonl`.

### 4. Drafter handoff (the new core of close)

Scan `${SUBSTRATE_DATA}/<procedure-slug>/memory/research-notes-*.md` (the preamble surfaced these as `PENDING_STATE: ready_to_draft`) for files with frontmatter `status: ready_to_draft`. For each:

- Surface to customer: "I have research-notes from [N] session(s) about [target]. Submit now, keep researching, or discard?"
- **Submit now:** spawn the relevant drafter via the Agent tool. Dispatch in parallel when multiple distinct entities are ready; collect results and surface them to the user one at a time for review.
  - `bc-process-drafter` for process-shaped notes (`model: opus` for a new-Process proposal — judgment-heavy; `model: sonnet` only for a trivial amendment to an existing Process). If the drafter's Step 0 finds the notes are path-shaped, it hands off to `bc-path-drafter` itself.
  - `bc-path-drafter` for path-shaped notes (`model: sonnet` usually; `model: opus` for cross-region / cross-commune scope judgment).
  - Pass the research-notes path and the customer's profile snapshot.
- The drafter returns a structured payload: `{ proposed_process_id | target_process_id (or path equivalent), label, canonical_markdown | body_diff, rationale, evidence, provenance: { research_notes_scrubbed } }`. It also returns the **Issue submission envelope** it built (it does NOT submit — close owns the wire call):
  - New Process proposal → `target_type: knowledge_graph`, `label: gap`, `evidence.proposed_process_id: <kebab-slug>`.
  - Amend an existing Process → `target_type: process`, `label: missing | bug | divergence`, `target_id: <process_id>`.
  - Wholly-new Path → `target_type: path`, `label: missing`.
  - New / commune-specific Path source → `target_type: path_source`, `label: missing | divergence`, `target_id: <path_id>:<source_id>`.
- Present the payload + research-notes to the customer for review.
- **On approve:** submit the Issue envelope per step 6 (single direct POST to `/api/issues`). On a `202`, rewrite the notes frontmatter to `status: drafted` and clear the matching `discovery:*` entry from `profile.json.active_procedures`.
- **On keep-researching:** leave status `ready_to_draft`; the next session's pending-state scan picks it up.
- **On discard:** rewrite frontmatter `status: discarded`.

### 5. Surface §8 Requests-for-contributions — filtered

For every procedure Process walked this session, read its body's `[Requests for contributions]` section (if present). Apply **two filters** before surfacing — never dump the full list on the customer:

- **Relevance filter.** Only surface items the customer's session actually touched. If the Process has 5 contribution requests but this customer's path only exercised 2 sub-scenarios, surface only those 2.
- **Genuine-access filter.** Only surface items the customer is actually positioned to help with. A request for "first-hand commune-staff judgment from Schaerbeek" is for a Schaerbeek customer, not a Ghent customer. A request about a sub-category the customer didn't qualify under is not for them.

Present the survivors (typically 0–2 items) as: "Things you've seen firsthand that would help others." Frame as contribution, not extraction. If zero survive, skip the section entirely — don't manufacture asks.

For each item the customer commits to, map to the right submission shape (concern/amendment-shaped items are all submitted as **Issues**, per the routing table below):

- "I saw an extra step / a missing doc on this Process" → Issue, `target_type: process`, `label: missing` (or `bug` for an incorrect step).
- "A citation / source link is dead" → Issue, `target_type: process | path | path_source`, `label: rotted`.
- "It differed at my commune" → Issue, `target_type: process | path_source`, `label: divergence`, with `evidence.scope` + `evidence.specifier` (NIS5).
- "This whole sub-procedure is missing from Be Civic" → route into `bc-discovery` for next session (becomes research-notes, then a drafter handoff at a future close), not a bare Issue now.

### 6. Submission — single direct typed POST, with local-buffer fallback

Submit each approved item — observations from step 3, drafter Issue envelopes from step 4, contribution Issues from step 5. **One POST per item**, no staging round-trip.

**Build the envelope** for the item's type and POST it:

- **Issue** → `POST /api/issues`. Body: `{ schema_version, submission_id (iss_…), submitted_at (RFC3339 UTC), submitting_harness ("be-civic-plugin/0.3.0"), submitting_model, submission_contract_version, target_type (process|path|path_source|tool|provider|volatile_value|reference|resource|knowledge_graph), target_id, title (≤120, no newline), body (markdown ≤2000), label (bug|missing|rotted|divergence|gap), context { language_used, region?, commune_nis5? }, evidence { …per-target } }`. Per-target `evidence`: graph entities + `path_source` → `{ evidence_date, evidence_source: customer-report|citation|corroboration, scope?, specifier? }`; `knowledge_graph` → `{ proposed_process_id? }`; `volatile_value` → `{ observed_value, evidence_date }`; `reference` → `{ evidence_date, evidence_source }`; `resource` → `{ evidence_date, observed_path_id? }`.
- **Validation** → `POST /api/validations`. Body: `{ schema_version, submission_id (val_…), submitted_at, submitting_harness, submitting_model, submission_contract_version, target_type, target_id, outcome (positive|negative), signal_class }`. No body/rationale field. (Most Validations are inline-committed at traversal time; a Validation only reaches close if it was buffered.)
- **Feedback** → `POST /api/feedback`. Body: `{ schema_version, submission_id (fbk_…), submitted_at, submitting_harness, submitting_model, submission_contract_version, topic? (bug|suggestion|praise|confusion|accessibility|other), pointer?, body (≤2000) }`. No `target_type`.
- **Rating** → `POST /api/ratings`. Body: `{ schema_version, submission_id (rat_…), submitted_at, submitting_harness, submitting_model, submission_contract_version, target_type (process|agent_protocol|session), target_id, score (1..5), would_be_5_stars? (when score ≤ 4) }`.

**On `202`:** parse `data.{submission_id, accepted_at, cancel_token}` and persist `cancel_token` + `submission_id` + type (carry into step 7). Mark the item submitted.

**On a non-202 / error envelope (`{ "error": "<category>", … }`):** do NOT silently retry.
- A scrub / field rejection (e.g. `worker_field_supplied_by_submitter`, a scrub-detector category) names what tripped — tell the customer plainly which field, offer rewrite-or-drop, and re-submit only after they fix it.
- A transport failure (network down, 5xx, timeout) → **local-buffer fallback (don't lose the contribution).** Append the approved item to `${SUBSTRATE_STATE}/sessions/<session_id>/pending-submissions.jsonl` (same JSONL line shape, plus a `staged_at` timestamp; Layer-1 scrub already ran at step 3 so resubmit goes straight to the POST). Tell the customer plainly: "I couldn't reach Be Civic right now — your contribution is saved locally and I'll try again next session." The next session's preamble surfaces it via `PENDING_STATE: pending_submissions` for the resume-submit branch.

If the preamble set `SUBMIT_OBSERVATIONS_THIS_SESSION: no` (scrub-rules couldn't be confirmed), do NOT submit. Tell the customer: "I'm holding back submissions this session — Be Civic's scrub rules couldn't be confirmed. We'll send next time," and write approved items to `pending-submissions.jsonl` instead.

### 7. Name what happens next time

One sentence per active item. "Next session we'll pick up at [step]." / "When you have [doc], come back." / "Cancel handle for what we just sent is in your notes; you have 48 hours." Skip on resume-submit.

### 8. Defensive dossier check, then cleanup

**Defensive dossier check.**
<!-- Safety net: catch a finished procedure that never produced its filing dossier. -->
Before the goodbye, scan `${SUBSTRATE_STATE}/procedures.json`. For any procedure whose `status` is `completed` (terminal / dossier-eligible) **and** whose visible folder `${SUBSTRATE_DATA}/<slug>/` holds no dossier artefact (nothing under `${SUBSTRATE_DATA}/<slug>/documents/dossier/`), offer once: "You finished [procedure] but we never built the dossier you'd file — want me to compile it now?" On yes, hand off to `bc-dossier-compilation` for that procedure. On no, drop it — don't re-ask. Skip this check entirely on resume-submit.

**Cleanup.** Delete `${SUBSTRATE_STATE}/sessions/<session_id>/observations-buffer.jsonl` once every item is submitted, discarded, or written into `pending-submissions.jsonl`. Leave the session directory for the orphan-buffer scan to handle on a hard close. Do not delete `pending-submissions.jsonl` — the preamble owns its lifecycle. Skip on resume-submit.

### 9. Goodbye

One sentence. Warm, specific to what the customer worked through. No "great chatting!" Don't preamble. Skip on resume-submit.

## Portability — bc-export

If the customer asks "how do I back up my Be Civic data?" or "can I use this on another machine?", run the export script at session close (after cleanup in step 8):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/bc_export.py --cowork --out ~/Desktop
```

The script bundles both surfaces (visible + hidden) into a single `bc-export-<timestamp>.tar.gz` and prints the mandatory Identity warning. Identity (harness key) is NOT in the bundle — it is excluded by construction (gitignored, never committed). On the destination machine the user runs:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/bc_import.py <bundle.tar.gz> --cowork --data-parent <parent>
```

then re-verifies via the onboarding flow. See `CAPABILITIES.md` at the plugin root for the full portability contract and bundle format, and `skills/be-civic/SKILL.md §5` for import detection in the gate skill.

## What this skill does NOT own

- Generating canonical markdown from research-notes. The drafter subagent does that; close hands off, reviews, and owns the single wire POST.
- Deciding what's an Issue vs a Validation vs a discovery. That classification is made upstream (by `bc-path-traversal` / `bc-discovery` as items land in the buffer). Close routes the already-classified items and maps concern/amendment-shaped contributions to the right Issue `target_type` + `label`.
- Inline-commit Validations on path sources — those POST directly from `bc-path-traversal` at traversal time and never enter this skill's buffer.
- Re-running scrub on items already at Layer-1. The worker runs Layer-2 at ingress. A Layer-1 re-run is needed only when an item is edited at step 3 — call `scripts/scrub-layer1.py` then.

