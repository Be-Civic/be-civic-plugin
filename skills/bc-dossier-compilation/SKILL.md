---
name: bc-dossier-compilation
description: Use at the end of a Be Civic application procedure, after eligibility has passed and the document checklist has been gathered. Produces a Be Civic-styled application dossier — index page, bring-originals callout, checklist table, filled official forms, disclaimer — that the user prints and submits to the filing authority. Agent-tooling sub-skill; produces an artefact rather than running a Belgian admin process.
---

<Tip>
Stable skill — agent-tooling sub-skill. Produces a filing dossier artefact rather than running a Belgian admin process. It does not submit anything over the wire.
</Tip>

Invoked from a `kind: main` application skill at session end, after eligibility has passed, intent is confirmed, and the checklist of required documents has been gathered. Produces a Be Civic-styled application dossier — an index page listing every document the user must file, the "bring originals" callout, the checklist table, and the filled official forms — that the user prints and submits to the filing authority.

The dossier is the artefact the user files. Be Civic does not stage or store it; the agent renders it locally on the user's machine.

## Step 1 — confirm invocation

Invoke this sub-skill only when:

- The parent process's intro paragraph declared the artefact class as `application dossier`.
- The parent process listed `dossier-compilation` in its `requires`.
- The session has reached the point where every checklist item is gathered or accounted for (the user knows where each document comes from, which form is required, and whether it must be brought in original).
- The user has confirmed they are ready to file.

If any of these are unmet, do not render the dossier. Continue gathering with the user under the parent process's guidance.

## Step 2 — capability gate and graceful degradation

The full-capability path requires `pdf_generation`, `file_read`, and `structured_output`. If any are unavailable, degrade per the table:

| Missing capability | Degraded behaviour |
|--------------------|--------------------|
| `pdf_generation` | Emit the dossier markdown only. Tell the user once: *"I can't render PDF in this session. Save the markdown I produce, then convert via your browser's print-to-PDF or a converter like pandoc."* Walk them through one render path. |
| `file_read` | The agent cannot save artefacts locally. Narrate the dossier content inline in chat; tell the user to copy it to a local file themselves. |
| `structured_output` | Render the index page as plain prose rather than tables; mark each document with a clear *"Bring in original"* / *"Copy acceptable"* prefix. |

Tell the user once, briefly, which path you are taking. Do not over-explain — the user wants the dossier, not an apology for what the agent cannot do.

## Step 3 — fill the index-page template

The index page is the cover of the dossier. Render the template below, filling each `{placeholder}` from the parent process's inputs and the user's gathered context.

````markdown
<!-- Be Civic Application Index — generated {generated_date} -->

![Be Civic](https://becivic.be/logo/light-inline.png){ width=120px }

# {application_title}

**Prepared for:**     {user_name_or_self_reference}
**Date prepared:**    {generated_date}
**Filing authority:** {filing_authority}
**Process:**          `{parent_process_id}` v{parent_process_version} ({version_status})

---

> **Bring these in original — the printout is not sufficient:**
> - {original_required_1}
> - {original_required_2}

## What this dossier contains

| § | Document | Form | Source |
|---|----------|------|--------|
| 1 | {document_name} | {form_required} | {source} |
| ... | ... | ... | ... |

## Notes for the filing officer

{agent_note_or_omit}

---

*This dossier was prepared by the user with the assistance of an AI agent
using Be Civic context. Be Civic publishes public information only and has
no legal standing. Verify with the relevant authority before filing —
procedures vary and change.*
````

The logo URL is stable and served at the apex; embedding it as a remote `![]()` is fine for renderers with web access. If the renderer is offline or strips remote images, omit the logo line — do not block rendering on it.

## Step 4 — render the checklist as a table

The checklist enumerates every document in the dossier. One row per document. Use a markdown table — long document names wrap to a second line within the cell rather than overflowing the page edge.

Columns:

- **§** — index number (1, 2, 3, ...)
- **Document** — the official name of the document, in the language used by the issuing authority
- **Form** — one of `Original`, `Certified copy`, `Apostilled`, `Sworn translation`, `Printout acceptable`. Pull from the parent process's `## Required documents` section, where each row carries a form-required marker.
- **Source** — where the user obtained it (commune, origin sub-skill name, payment receipt, etc.)

The "Form" column drives Step 5.

## Step 5 — surface the "Bring in original" callout

Above the checklist table, render the originals callout. Include every document where "Form" is anything other than `Printout acceptable`:

> **Bring these in original — the printout is not sufficient:**
> - {document_1}
> - {document_2}

Before closing the dossier handoff (Step 8), say this out loud to the user:

> *"You'll need to bring these documents in original form — the dossier I'm preparing is for your reference, not a substitute for the originals. Specifically: {list}."*

If the parent process's `## Bring in original` section is empty (rare for application skills, but possible — e.g., a fully digital filing), omit both the callout and the verbal reminder.

## Step 6 — append the official forms

After the index page and checklist, append every official form the user must file. These are pulled from the parent process body (Annexes, declarations, fee receipts, attestations, etc.). For each form:

- Reproduce the form's title and reference number exactly as the issuing authority publishes it.
- If the agent has filled fields based on user answers, mark filled values clearly (some authorities require handwritten signatures on printed forms, so the user must verify and sign physically).
- If a form is not yet available (e.g., the user must collect it from the commune in person), include a placeholder page noting where the user obtains it.

Do not invent or paraphrase form fields. If unsure of a value, leave the field blank and flag it to the user before rendering.

## Step 7 — format and orientation rules

A4 portrait is the default for the entire dossier. Override per page where content demands it:

- **Landscape** — pages with wide tables (more than five columns or document names that exceed ~60 characters). Worth checking that print-to-PDF respects the orientation declaration.
- **ID cards on one page** — render front and back of the same card (residence permit, ID card, driving licence) on a single A4 portrait page rather than wasting two pages. Standard layout: front in the upper half, back in the lower half, both at full readable size.
- **Wrap text in tables** — long names, addresses, and citation text should sit inside table cells which the renderer wraps, rather than as inline prose that runs off the page edge.
- **Page breaks** — insert a manual page break before each new top-level section (`## ...`) to keep the dossier scannable. The index page sits on its own page.
- **Margins** — narrow margins (1.5cm) so checklist tables fit at full width.
- **Fonts** — embed fonts where the renderer supports it; otherwise use a widely-supported sans-serif (Helvetica, Arial) that survives PDF sharing across platforms.

If the renderer does not support a particular instruction (e.g., browser print-to-PDF has limited orientation control), accept the limitation and tell the user.

## Step 8 — output handoff

Save the dossier to the visible surface with the user's permission. Default path: `${SUBSTRATE_DATA}/<procedure-slug>/documents/dossier/{parent_process_id}-dossier-{YYYY-MM-DD}.{md,pdf}`.

Repeat the originals reminder from Step 5. Confirm the user understands the dossier is a reference, not a substitute for the originals.

This sub-skill does not submit anything at session end. The dossier is rendered locally; the parent process's own lifecycle continues independently.

---

*Verify with the relevant authority before filing — procedures vary and change.*

