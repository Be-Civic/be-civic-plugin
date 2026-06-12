---
name: bc-discovery
description: Use when Be Civic has no verified process for the customer's procedure (process mode) or no verified path for a needed source (path mode). Walks the customer through with research-as-we-go discipline. Produces a durable research-notes file the drafter consumes at session close.
---

# Be Civic — Discovery

Two modes:

- **`process` mode** — fires on graph zero-match for the customer's intent, or when `bc-path-traversal` returns `unknown-process-fallback`.
- **`path` mode** — fires when `bc-path-traversal` returns a structured miss signal (`unknown-path-id` or `all-sources-failed-with-alternative`).

The framing matters: **this is "discovery mode," not "no-process fallback."** First use of the term in a session MUST carry a gloss; the bare phrase is fine thereafter.

## 1. Corpus search — confirm the miss BEFORE you speak

You may have been routed here on a vague intent or a stale miss signal. Before saying anything about coverage — and strictly before the gap-framing opening in §2 — verify the miss **for your mode**.

**Process mode** — fetch the full entity graph and search client-side:

```
GET ${BASE}/api/manifest
Authorization: Bearer <harness_key>   # omit if no key yet; public read still works
```

Response: the bare manifest `{ "version", "generated_at", "entries": [...] }` — `entries` is top-level, there is no `.data` wrapper (the handler returns the manifest unwrapped). Search `entries` by `title`, `summary`, and `applies_to` fields for the customer's intent. Only declare zero-match when no entry matches after a genuine client-side scan.

Read the harness key from `${SUBSTRATE_STATE}/.env` (`BECIVIC_HARNESS_KEY=<value>`). If the file is absent or the key is not set, send the request without the `Authorization` header — anonymous reads succeed against `corpus:read:public`.

**If the search DOES match the customer's intent, Be Civic has it — never tell the customer it's missing.** Do not speak the §2 opening at all: hand back to `bc-path-traversal` with the matched entry (or proceed with the verified entry directly) and exit discovery. Telling a customer "Be Civic doesn't have a verified procedure for X" when the corpus covers X betrays the authoritative-confirmation move; the gap line is earned only by a confirmed zero-match.

**Path mode** — the miss arrived as a structured signal from `bc-path-traversal`, so the *procedure* is covered by construction; do **not** re-litigate the customer's intent against the manifest (an intent match is guaranteed here and is NOT a reason to route back — that would loop discovery and traversal forever). Verify the path-level miss instead:

- `unknown-path-id` → search the manifest's **Path entries** for the missing path id. Only if a matching Path entry exists was the miss stale — hand back to `bc-path-traversal` with that entry and exit discovery. No matching Path entry = the miss is confirmed; proceed to §2.
- `all-sources-failed-with-alternative` → the Path entry exists and its sources failed at runtime; the miss is already verified. Skip the manifest re-check and go straight to the §2 path-mode opening.

## 2. Opening — only after §1 verified the miss

Speak this only once §1 verified the miss for your mode: a confirmed zero-match (process mode), a confirmed missing Path entry (`unknown-path-id`), or the runtime-verified source failure (`all-sources-failed-with-alternative`).

**Process mode:**

> "Be Civic doesn't have a verified procedure for [name the procedure] yet — so let's switch to discovery mode (where we walk through this together and document what we find for the next person filing the same thing). I'll ask you what you know, look up what I can verify, and keep notes as we go. You get help with your procedure today; the next person filing this hits a verified process instead of a blank."

**Path mode:**

> "We needed [path name / source] for this step, and Be Civic doesn't have a verified path entry yet. Let's switch to discovery mode (same idea — we walk it together and document what works). I'll log every source I can verify and we'll see where it lands."

Don't preamble the contribution framing every turn after that — once is enough.

## 3. Source-quality discipline

Citation-grade only for claims that end up in canonical:
- Belgian statute, federal regulation, regional decree.
- Federal / regional / commune official pages (`*.belgium.be`, `*.brussels`, `*.vlaanderen.be`, `*.wallonie.be`, `*.<commune>.be`).
- Professional-body guidance (notary, lawyer, sworn translator).
- Origin-country government sites for foreign documents.

**Signal-only** sources (forum posts, news articles, expat blogs, Reddit) may be read freely to find a trail but are NEVER cited in research-notes as evidence. They are scaffolding, not citation.

## 4. Research-as-we-go

WebFetch authoritative sources as questions come up. Never invent procedural detail. If you can't verify a claim:
- Mark it as `[customer-report: <date>]` and keep going — the drafter may still propose the process with that point flagged as `verify-with-commune`.
- Or surface to the customer and ask whether they have a source we can WebFetch.

Cite every claim with: URL + date-fetched + verbatim snippet (≤300 chars per snippet). If a page is gated or 404s, log it as `[citation_404: <url>]` so the next session knows not to retry.

## 5. Sub-skill detection

If a sub-step in the discovery walk is covered by an existing Be Civic process (e.g. apostille for a foreign birth certificate, EU 2016/1191 multilingual form), load that skill via the Skill tool and walk it normally. In research-notes, mark those segments `[verified-corpus: <process_id> v<version>]` rather than re-deriving the procedure.

## 6. Research-notes file (the durable artefact)

Write to `${SUBSTRATE_DATA}/<procedure-slug>/memory/research-notes-<slug>.md`. This is the path `bc-session-close` scans for `ready_to_draft` notes. Create the `<procedure-slug>/memory/` directory if absent. Slug is kebab-case of the procedure name (process mode) or path id (path mode), truncated to ≤32 chars. Frontmatter:

```yaml
---
kind: discovery_session
target_type: process | path
target_slug: <slug>
status: in_progress | ready_to_draft | drafted | discarded
first_session_at: <ISO8601>
last_session_at: <ISO8601>
session_count: <int>
verified_corpus_refs: [<process_id>, ...]
research_sources:
  - url: <url>
    kind: citation-grade | signal-only
    claim: <≤200 chars>
    fetched_at: <ISO8601>
---
```

Body: prose with tagged claims. Every claim carries one of:
- `[verified-corpus: <id>]` — covered by an existing process walk.
- `[citation: <url>]` — verified against a citation-grade source we WebFetched.
- `[customer-report: <date>]` — customer told us; not independently verified.
- `[verify-with-commune]` — needs a commune visit or appointment to confirm.

The drafter at session close reads this file and produces a `process_draft` (or `path_draft`) submission with `provenance.research_notes_markdown` set to this file's body. The CC BY 4.0 grant the customer makes at submission covers both canonical and research-notes jointly.

## 7. Buffering findings as Issues

As gaps and missing entries are identified during a discovery session, buffer them as Issues at:

```
${SUBSTRATE_STATE}/sessions/<session_id>/observations-buffer.jsonl
```

One JSON object per line. Do NOT submit directly — bc-session-close submits after per-item user review.

Each buffered object shape:

```json
{
  "submission_type": "issue",
  "target_type": "knowledge_graph",
  "target_id": "<proposed_process_slug_or_null>",
  "label": "gap",
  "title": "<≤120 chars, no newlines>",
  "body": "<markdown ≤2000>",
  "context": { "language_used": "<lang>" }
}
```

`target_type` is typically `knowledge_graph` with `label: gap` for a missing process proposal, or `process` with `label: missing` for a gap in a known process. Use `evidence.knowledge_graph.proposed_process_id` when proposing a new process.

## 8. Status transitions

- `in_progress` — active session, more to learn.
- `ready_to_draft` — the customer says they've done the procedure or has enough verified claims to propose a process. Set when the customer agrees in plain language. Picked up by next session's pending-state scan, surfaced at `bc-session-close` for drafter handoff.
- `drafted` — set by session-close after the drafter has produced and the customer has approved a submission.
- `discarded` — customer abandoned; file kept locally but not surfaced again.

## 9. Resume marker on the profile

Add `discovery:process:<slug>` or `discovery:path:<slug>` to `profile.json` `active_procedures` so a returning session resumes correctly. Remove on `drafted` or `discarded` transition.

## 10. Exit

Discovery exits when:
- The customer says they're done for now (status `in_progress`, resume next session).
- The customer says they've finished the procedure (status `ready_to_draft`, session-close offers drafter handoff).
- The customer abandons (`discarded`).

## What this skill does NOT own

- Drafting the canonical or path entry. That's the `bc-process-drafter` / `bc-path-drafter` subagent's job, spawned from `bc-session-close` after customer approval.
- Submitting anything. Submission is gated by per-item review at session close.
- Producing volatile-value catalogue rows. Discovery records them in research-notes; the drafter decides whether they become `<VV>` rows.
