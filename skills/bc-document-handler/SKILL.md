---
name: bc-document-handler
description: Use when the customer presents a document — paste, upload, attachment, photo, or described field value. Extracts the routing fields the active procedure needs, archives the original to the customer's machine, discards everything else. Tells the customer plainly what was kept and what wasn't.
---

# Be Civic — Document Handler

This skill applies the data minimisation rules at the moment of document presentation: take only what the procedure needs, archive originals, never write document bodies to routing stores, maintain the cross-procedure index. This skill runs the per-drop dialogue and abort handling.

## When this fires

- The customer pastes document content in chat.
- The customer uploads or attaches a document.
- The customer shares a photo or scan.
- The customer describes a field value verbatim ("my birth certificate says: Jan De Smet, born 1985-04-22 in Antwerpen, RR-number 85.04.22-123.45").

Handle inline. Don't context-switch back to the procedure skill for every drop — extract, archive, confirm, return.

## Resource reads

When the procedure body references a resource by UID to provide document metadata, fetch it via:

```
GET https://becivic.be/api/resources/<uid>
Authorization: Bearer <harness_key>   # omit if absent; public read works
```

Response: `{ "status": 200, "data": { ... } }`. Branch on HTTP status code first. Read the harness key from `${SUBSTRATE_STATE}/.env` (`BECIVIC_HARNESS_KEY=<value>`).

## The discard rule — as principles, not enumerations

1. **Read the document.** Identify the routing fields the active procedure actually needs from its frontmatter `inputs:` plus any fields its body references by name.
2. **Take only those.** Routing fields are categorical or bucketed: a type letter (residence card series), a month-bucket date (`YYYY-MM`), an ISO country code, a NIS5 commune code, boolean inventory flags. Never identity-shaped values.
3. **Never retain:** document numbers, full names, exact dates of birth, exact addresses, photographs, biometric data, signatures, full text blocks beyond the categorical routing fields.
4. **Original document content never gets written to any file under `profile.json` or `MEMORY.md`.** It exists only in the active conversation context and is gone when the conversation ends. The original goes to the visible surface (`${SUBSTRATE_DATA}`) — that's the customer's archive, recoverable next session.

## Archive paths — visible surface

Archive originals to the **visible surface** (`${SUBSTRATE_DATA}`), which is user-accessible from their file manager:

- **Procedure-specific documents:** `${SUBSTRATE_DATA}/<procedure-slug>/documents/<doc-type>.<ext>`
- **Cross-procedure documents** (birth certificate, marriage certificate, etc.): `${SUBSTRATE_DATA}/documents/<doc-type>.<ext>`

Use the procedure-specific path when the document belongs to an active procedure context; use the top-level `documents/` path for documents that are reusable across procedures without a primary owner.

## Judgment heuristics for the model

Use these when deciding whether a field belongs in routing:

- **If you would name this value to identify the customer, it doesn't belong in routing.** "Jan De Smet" identifies. "civic_status: married" does not.
- **If the procedure body never mentions this field by name, you don't need it.** Don't pre-extract "just in case."
- **If you find yourself extracting more than 4–6 fields from a single document, you're probably keeping too much.** Stop and ask which the active procedure actually requires.

## Transparency dialogue (always)

After extraction, tell the customer in plain English what was kept and what wasn't. Brief. Conversational. Not a privacy disclaimer.

Example, after a birth certificate drop for a nationality-declaration procedure:

> "Got it. From your birth certificate I kept: country of birth (BE), birth month-bucket (1985-04). The certificate itself I saved to your Be Civic folder under `nationality-application/documents/birth-certificate.pdf`. The full name, exact date, and certificate number don't get stored anywhere we share. Want to keep going?"

If the procedure didn't need anything from the document (e.g., the customer dropped something not on the procedure's needs list): say so, archive the original, move on.

> "Got it — saved to your folder under `nationality-application/documents/marriage-certificate.pdf`. The nationality declaration doesn't need anything from this one specifically, so I haven't pulled any routing fields. We'll have it on hand if a later step asks."

## Scrub-failure abort

After deciding which routing fields to extract, run `scripts/scrub-layer1.py` against each candidate value before writing it to `profile.json`. On any high-severity hit (identity, biometric, document_number):

1. **Abort the write.** The field does not land in `profile.json`.
2. **Tell the customer one sentence.** "That value tripped the scrub check — looks too identity-shaped to keep as a routing field."
3. **Offer two options via AskUserQuestion.** Drop it (proceed without that field; the procedure body decides if that's blocking). Or rewrite abstractly (e.g., "Antwerpen" → "NIS5 11002"; "1985-04-22" → "1985-04"). Customer chooses; re-run the scrub on the rewrite.

Do NOT silently retry. Do NOT silently write a degraded version. The scrub is load-bearing for the privacy contract; surface every failure.

## Cross-procedure index

When the archived document is reusable across procedures (birth certificate, residence certificate, marriage certificate, apostille, EU 2016/1191 multilingual form), record the path in `MEMORY.md` under a `documents:` section. Future procedures find it without re-asking the customer to fetch it again.

The `documents:` block is path-only — no field values, no transcriptions. Example:

```markdown
## documents
- birth-certificate (BE, archived 2026-05-14): nationality-application/documents/birth-certificate.pdf
- marriage-certificate (BE, archived 2026-05-14): nationality-application/documents/marriage-certificate.pdf
```

## Dossier compilation trigger

**After the first archive for a procedure completes,** if the parent procedure declares `application_dossier` as its artefact class, invoke `be-civic:bc-dossier-compilation` in `initial` mode. This produces the early-stage dossier with placeholders so the user sees value before the procedure completes. Don't fire again for subsequent archives in the same procedure — subsequent archives trigger `refresh` mode, which `bc-dossier-compilation` handles itself based on its own state detection.

To check whether this is the first archive for the current procedure: look for any existing dossier file under `<procedure-slug>/documents/dossier/` in the visible surface. If none exists, this is the first archive; fire `initial` mode. If one already exists, skip the `initial`-mode invocation (subsequent refresh is handled by `bc-dossier-compilation` on its own trigger).

## Reference prompts

- **Belgian residence-card image reading** (used by bc-onboarding's row_list folder-drop hydration, not by this skill directly): `references/card-vision-prompt.md`. Vision-extraction instructions for card-type + month-bucket dates, with pairing heuristics for front/back and a two-fail policy aligned with bc-onboarding §7.1 R5.

## What this skill does NOT own

- Validation of whether the document is genuine, valid, in the right format, or sufficient for the procedure. Those calls live in the procedure skill body.
- Enumerated extraction tables per document type. The model judges per procedure context using the heuristics above.
- Re-archiving documents already in `documents/`. Check the cross-procedure index first; if present, reuse the existing path and skip the upload.
- Vision extraction for row_list folder-drop hydration. The prompt lives at `references/card-vision-prompt.md` but bc-onboarding's §7.1 hydration loop is the caller — this skill does not initiate the read.
