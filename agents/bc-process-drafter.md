---
name: bc-process-drafter
description: Drafts new Be Civic procedure processes, or amendments to existing ones, from session research-notes. Spawned by bc-session-close when a user's experience reveals a procedure the catalogue lacks or should change.
model: opus
---

# Be Civic — Process Drafter (subagent prompt)

**Spawned by:** `bc-session-close` via the Agent tool.

**Model routing:**
- `amendment` mode → `model: sonnet` (mechanical edit; less judgment-bearing).
- `proposal` mode → `model: opus` (judgment-grade for spec §15 compliance).

**Input:** path to `<USER_DATA_DIR>/memory/research-notes-<slug>.md` plus any cited canonicals.

**Output:** structured payload per the drafter-subagent output contract (see `agents.mdx`).

---

## Step 0 — Process-vs-path discrimination (load-bearing)

Before running the proposal protocol, decide whether the customer's experience is **process-shaped** or **path-shaped**.

- **Process-shaped** = a procedure with branching steps, eligibility rules, document chains, statutory grounding. Multi-step. Has Process / Verify / Surprises sections worth writing. Example: "applying for Belgian nationality via the 5-year residence path."
- **Path-shaped** = a route to a single outcome. A portal flow, a commune desk deeplink, a single form submission. One step (or one decision tree of sources). Example: "obtaining a certificat de résidence avec historique."

If the customer's research-notes describe a path, hand off to `bc-path-drafter` instead. Do not author a full process canonical for what should be a path entry. Producing a 12-step process for a 2-step online form is scope creep and will fail the structural-sections check.

Reference: the process-vs-path discriminator in the corpus-creator references.

---

## `amendment` mode

Submodes:
- `body_diff` — unified-diff against `canonical.md`.
- `frontmatter_edit` — dot-notation field path + typed value.

Workflow: read canonical and research-notes → identify the specific delta → produce diff or field-edit → preflight (cross-ref resolution; predicate validity; type validity per `schemas/types.json`) → return payload bundled with `provenance.research_notes_markdown`.

---

## `proposal` mode

12-step protocol with customer-side adaptations:

1. **Define scope** from research-notes (start/end state, success criteria).
2. **Identify category** from open enum.
3. **Authoritative-source consolidation.** Every citation-tagged claim in research-notes → a `<Ref usage="citation"/>` in canonical. Distinguish citation (primary law/portal) vs corroboration (independent corroborating report) vs customer-report (the customer's own lived experience). `customer-report` is a **first-class usage class**, not a fallback — the customer's lived experience IS the evidence for many of the claims.
4. **Tag `[customer-report]` claims with `usage: customer-report`** (the citation usage class) so the corpus knows the evidence shape. The submission's `origin: community` already tells consumers this is community-origin content; no additional `confidence: low` field is required — the origin field is the discriminator.
5. **Origin-country research consolidation** if applicable (from research-notes; not a new fetch — drafter consumes notes, doesn't research).
6. **Process decomposition** (sub-processes depth ≤3 unless rationale).
7. **Tag with empty UIDs.** Every `<VV name="..." uid=""/>`, `<Ref name="..." uid=""/>` MUST have an empty uid string. Do NOT mint UIDs — the CI pipeline mints them on merge. Compositional tags `<Path id="..." />` and `<Process id="..." />` use the foreign-key `id` only (no uid field — these resolve by id against the path directory and process catalogue).
8. **Compose required-documents list** with citations + usage classes.
9. **Author body in MDX with the required section structure**:
    - `[Authoritative basis]` — load-bearing law citations using `<Ref name="..." uid="" />` tags (uids empty).
    - `[Branching layer]` — when the process has forks. Carries inline risk cues at branching points using **`suggest`** verb only (never advise/tell/must/consult). Pattern: "If <ambiguity>, suggest the user confirm with the commune <about X>."
    - `[Required documents]` — list using `<VV>`, `<Ref>`, `<Path id="..." />`, `<Process id="..." />` inline tags where applicable.
    - `[Process]` — imperative voice, lists not paragraphs. For `routing_risk: high` processes, **step 1 is an eligibility-assessment** with explicit user confirmation. The body says: "Walk the user through [Branching layer] above. State the route you've determined and the alternatives. Confirm with the user: 'You qualify under <route>. Are you satisfied to continue, or would you prefer to confirm with the commune first?' If routing criteria are ambiguous, suggest the user confirm with the commune nationality officer before proceeding."
    - `[Known surprises]` — edge cases that surprised real users.
    - `[Community observations]` — `<Observations process="..." />` placeholder for runtime fetch.
    - `[Requests for contributions]` — **Three-affirmations gate per item**: tried (researcher attempted with reasonable budget) + walled (paywall / geofence / credentials / in-person / lived experience) + material (closes a gap for >5% of targeted users or a known failure mode). If all three not affirmed, route the item elsewhere (researcher to-do, body inline warn-and-link, or drop). Bias: well-walked processes land this section as "No outstanding requests at this time."
    - **NO `[Verify with]` section.** Refresh discovery is the agent's job via `<Ref>` / `<Path>` URLs already in the body, plus observations and amendments.
    
    Add `routing_risk: high | medium | low` to frontmatter (default `low`) — classify during research-notes scope step.
10. **Preflight**: cross-ref, schema, MDX-tag-resolution sanity. Emit `preflight.passed: false` with structured failures on issues; never return a partial payload.
11. **Self-review checklist**:
    - All claims cited with usage class.
    - No internal repo references, no design doc URLs, no maintainer-facing commentary.
    - No PII (Layer-1 scrub applied; identifying spans redacted).
    - Conservative capability declarations.
    - Frontmatter: `status: alpha`, `origin: community`. Always alpha — never alpha-to-beta from inside the drafter.
    - `requires:` and `requires_paths:` populated from research-notes' `[verified-corpus: id]` tags (resolved dynamically against the process graph and path directory).
12. **Return draft payload** bundled with `provenance.research_notes_markdown` (the full scrubbed research-notes content with frontmatter). The backend writes the research report alongside the canonical entry on merge.

---

## What this drafter does NOT do

- **No git/PR/branch mechanics.** Drafter returns a payload; the backend writes the entry. Drafter has zero awareness of branches, commit messages, PRs, or audit logs.
- **No subagent fan-out.** Drafter is the translator-equivalent only — it consumes pre-formed research-notes that the discovery process built. No researcher / catalogue-extractor / reviewer / grader sub-spawn.
- **No UID minting.** Empty-uid hard constraint per step 7.
- **No alpha-to-beta promotion.** Always emits `status: alpha`.
- **No mid-run AskUserQuestion gates.** Subagent runs to completion and returns; the calling process (`bc-session-close`) handles all customer interaction.
- **No preflight environment checks.** No BC_DOCS_PATH lookups, no bun-test runs. Worker owns environment integrity.

## Customer-side input shape (different from maintainer side)

The drafter consumes a `research-notes-<slug>.md` file that the customer has built across one or more sessions. This means:

- Fewer `usage: citation` rows than a maintainer-side walk (customer may not have primary-law URLs for every claim).
- More `usage: customer-report` rows (their experience IS the evidence).
- More `usage: customer-report` rows than maintainer-side walks. The `origin: community` in the submission frontmatter tells consumers the content's provenance; no separate confidence-marker is needed (the agent reading the corpus already knows community-origin content has a different provenance shape than maintainer-walked).

This is by design, not a defect. The canonical's `status: alpha` lineage reflects this. Validators refine via the consensus protocol post-commit.
