---
name: bc-session-close
description: Use on procedure terminal step, explicit customer close, session end, or pending-state submit-now branch. Runs the 9-step close sequence — summary, save state, per-item observation review, drafter handoff for ready research-notes, contributions double-filtered, submission, next-time framing, cleanup, goodbye. Auto-spawns bc-path-drafter and bc-skill-drafter sub-agents for ready research-notes.
---

# Be Civic — Session Close

Two invocations:

- **Full close** — procedure terminal step, explicit customer close, session timeout. Runs the 9 steps below in order.
- **Resume-submit** — invoked from the pending-state surface at session open. Skip steps 1–2 and 7–9; jump to per-item review (step 3), drafter handoff (step 4), and submission (step 6). Used when the customer chose "handle now" on a deferred item from a prior session.

The customer-facing language for the observation buffer is **list** or **notes**, never "buffer."

## The 9 steps

### 1. Summarise progress

One short paragraph in plain English. What you covered today, what's done, what's still open. Tone is warm and concrete, not a status report. Skip on resume-submit.

### 2. Save state

Write `state/procedure_progress_<skill_id>.md` for each procedure walked this session. Carry the last step reached, what's pending, anything the user said worth holding. Skip on resume-submit.

### 3. Per-item observation review

Read this session's observation list at `.be-civic/sessions/<session_id>/observations-buffer.jsonl`. For each item:

- Show it in plain English (rendered from the JSON, not the JSON itself).
- AskUserQuestion: approve / edit / discard.
- On edit: ask what to change, rewrite, re-run `scripts/scrub-layer1.py` against the rewritten version.
- On discard: drop the line; do not re-surface.

Apply the CC BY 4.0 grant reminder **once** at the top of this step, not per item: "Anything you approve is shared anonymously under CC BY 4.0. You can cancel anything within 24 hours of submission — I'll give you the cancel codes after we send."

### 4. Drafter handoff (the new core of close)

Scan `memory/research-notes-*.md` (in the user's Be Civic project folder) for files with frontmatter `status: ready_to_draft`. For each:

- Surface to customer: "I have research-notes from [N] session(s) about [target]. Submit now, keep researching, or discard?"
- **Submit now:** spawn the relevant drafter via the Agent tool.
  - `bc-skill-drafter` for `target_type: skill` (`model: opus` for proposal — judgment-heavy; `model: sonnet` only for trivial amendments).
  - `bc-path-drafter` for `target_type: path`.
  - Pass the research-notes path and the customer's profile snapshot.
- The drafter returns a structured payload per the round-7.3 provenance shape: `{target_skill_id | proposed_skill_id, amendment_type | kind, body_diff | canonical_markdown, rationale, provenance: {...}}`. The `provenance.research_notes_markdown` is the scrubbed body of the notes file.
- Present payload + research-notes to the customer for review.
- **On approve:** bundle via submit-validate-then-stage (two-call MCP pattern, step 6). On success, rewrite frontmatter `status: drafted` and clear the `discovery:*` entry from `profile.json.active_procedures`.
- **On keep-researching:** leave status `ready_to_draft`; pending-state scan picks it up next session.
- **On discard:** rewrite frontmatter `status: discarded`.

### 5. Surface §8 Requests-for-contributions — filtered

For every procedure skill walked this session, read its body's `[Requests for contributions]` section (if present). Apply **two filters** before surfacing — never dump the full list on the customer:

- **Relevance filter.** Only surface items the customer's session actually touched. If the procedure has 5 contribution requests but this customer's path only exercised 2 sub-scenarios, surface only those 2.
- **Genuine-access filter.** Only surface items the customer is actually positioned to help with. A request for "first-hand commune-staff judgment from Schaerbeek" is for a Schaerbeek customer, not a Ghent customer. A request about a sub-category the customer didn't qualify under is not for them.

Present the survivors (typically 0–2 items) as: "Things you've seen firsthand that would help others." Frame as contribution, not extraction (CLAUDE.md §14). If zero survive, skip the section entirely — don't manufacture asks.

For each item the customer commits to, map to the right submission shape:
- "I saw an extra step / missing doc" → observation (event_type per CLAUDE.md §8).
- "I have a fix for a specific claim with a source" → `skill_amendment`.
- "This whole sub-procedure is missing from Be Civic" → route back into `bc-discovery` for next session.

### 6. Submission — two-call MCP pattern with local-buffer fallback

For each approved item (observations from step 3, drafter payloads from step 4, contribution items from step 5):

1. **Validate** via `mcp__becivic__validate_submission`, falling back to HTTP POST to `https://becivic.be/api/validate-submission` if MCP is unavailable. Worker runs Layer-2 scrub; if the response carries a `scrub_failure` (per schemas.md §6.2.7 placed under §6.2.4), tell the customer plainly which field tripped and offer rewrite-or-drop. Do NOT silently retry.
2. **Stage** via `mcp__becivic__stage_submission` (HTTP fallback `https://becivic.be/api/stage-submission`) on validate success. The Worker returns a `cancel_token` and `cancel_url`; carry these into the goodbye.
3. **Local-buffer fallback (third leg).** If BOTH MCP and HTTPS are unreachable (network down, both endpoints 5xx, or both timeout), do NOT lose the submission. Move the approved item from `observations-buffer.jsonl` to `.be-civic/sessions/<session_id>/pending-submissions.jsonl`. Tell the customer plainly: "I couldn't reach Be Civic right now — your submission is saved locally and I'll try again next session." The next session's preamble surfaces this via `PENDING_STATE`; the customer can review and re-submit at first opportunity. The pending-submissions file uses the same JSONL line shape as the observation buffer plus a `staged_at` timestamp; the scrub-layer1 pass already ran at step 3, so resubmit goes straight to validate/stage.

Capture the cancel tokens. If `SUBMIT_OBSERVATIONS_THIS_SESSION: no` was set by preamble (scrub-rules fetch failed beyond retries — CLAUDE.md §6), tell the customer plainly: "I'm holding back submissions this session — Be Civic's scrub rules couldn't be confirmed. We'll send next time." Do NOT submit anyway.

### 7. Name what happens next time

One sentence per active item. "Next session we'll pick up at [step]." / "When you have [doc], come back." / "Cancel link for what we just sent is in your notes; you have 24 hours." Skip on resume-submit.

### 8. Cleanup

Delete `.be-civic/sessions/<session_id>/observations-buffer.jsonl` once all items are either submitted, discarded, or written into `state/`. Leave the session directory for the orphan-buffer scan to handle on a hard close. Skip on resume-submit.

### 9. Goodbye

One sentence. Warm, specific to what the customer worked through. No "great chatting!" Don't preamble. Skip on resume-submit.

## What this skill does NOT own

- Generating canonical markdown from research-notes. The drafter subagent does that; close hands off and reviews.
- Deciding what's an observation vs an amendment vs a discovery. That decision lives in CLAUDE.md §8 (deterministic rule). Close just routes the already-classified items.
- Re-running scrub on items already in the buffer at Layer-1. Layer-2 happens on the Worker call (step 6). If a Layer-1 pass is needed (e.g., an item edited at step 3), call `scripts/scrub-layer1.py` then.

## Authoring source

Lifts from bootstrap.zip's `skills/becivic/SKILL.md` §19 (close sequence) + §22 (multi-procedure attribution) + §11.4 (per-item review). Drafter handoff and the §8 double-filter are new content per the W22 sprint plan.
