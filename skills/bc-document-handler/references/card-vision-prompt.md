# Card vision-extraction prompt

Reference prompt for the agent's vision capability when reading Belgian residence-card images dropped into a `row_list` folder-drop input (Mode 2 of the `belgian_residence_card_history` capture). Invoked by **bc-onboarding**'s row_list hydration loop (SKILL.md → "First-working-session mode → row_list hydration", step **R2**) — not by this skill directly. Lives here because card-image reading is a document-handling concern; it just doesn't go through the normal `bc-document-handler` extract-and-archive flow (the row_list hydration owns its own dialogue).

## When to use this prompt

bc-onboarding's post-submit row_list hydration loop (SKILL.md → "First-working-session mode → row_list hydration"), on detecting `__status: "pending"` with `__mode: "folder_drop"` on a `row_list` field (step R1), polls the procedure-root inputs folder `${SUBSTRATE_DATA}/<procedure-slug>/inputs/<field_name>/` (step R2). For each image file in that folder, run the agent's vision capability with the prompt below. Aggregate results into the structured rows that the row_list widget expects (re-rendered for confirmation in step R4).

The prompt is designed for `belgian_residence_card_history`, the first user of the `row_list` type. Other `row_list` inputs that take image drops will need their own prompts in this directory (e.g. `references/diploma-vision-prompt.md` for an academic-history list); the current file is named for the card use case specifically.

## The prompt

Pass this as the system / instruction text alongside the image. Repeat per image (or per image pair where the agent has already paired front + back — see "Pairing front and back" below).

> You are reading an image of a Belgian residence document — typically a residence card (carte de séjour / verblijfskaart / Aufenthaltskarte), a long-stay visa (visa D) inside a passport, a short-stay Schengen visa (visa C), an Annex 15 / Annex 15bis "orange card," or an attestation d'enregistrement. Your job is to extract structured routing fields — not to transcribe the document.
>
> **Identify the card type.** Match to one of these values exactly (use the value, not the label). This is the live **23-value** enum, in sync with the `belgian_residence_card_history` catalogue input and `schemas/profile.schema.json` (W25.15 survey, 2026-05-19):
>
> - `orange` — orange card / Annex 15 / 19ter / AI, provisional (paper, A4 or smaller, no chip, typically issued by the commune as a temporary attestation)
> - `visa_d` — Visa D (long-stay national visa, pasted into a passport page; "Type D" or "long séjour" visible on the visa sticker)
> - `visa_c` — Visa C (short-stay Schengen visa; "Type C" or the Schengen logo)
> - `A` — A card, limited / temporary residence (electronic card, "Tijdelijk verblijf" / "Séjour temporaire" / "Befristeter Aufenthalt")
> - `B` — B card, unlimited stay before long-term-resident status (currently issued)
> - `C` — C card, settled in the archived format (pre-2021; replaced by K in 2021)
> - `D` — D card, long-term resident in the archived format (pre-2021; replaced by L in 2021)
> - `K` — K card, permanent resident / long-term (current format)
> - `L` — L card, EU long-term resident — Directive 2003/109 (current format)
> - `F` — F card, family member of EU citizen (first 5 years; currently issued)
> - `F_plus` — F+ card, permanent family member of EU citizen ("Duurzaam verblijf" / "Séjour permanent" alongside the F+ marking)
> - `H` — H card, European Blue Card (highly qualified worker)
> - `I` — I card, Intra-Corporate Transferee (since Dec 2021)
> - `J` — J card, long-term ICT mobility (intra-EU transfer)
> - `M` — M card, subsidiary protection OR Brexit-WA beneficiary
> - `M_plus` — M+ card, Brexit-WA permanent beneficiary (after 5 years)
> - `N` — N card, recognised refugee OR Brexit-WA Art. 45/49 case
> - `E` — E card, legacy EU registration (archived; replaced by EU in May 2021)
> - `E_plus` — E+ card, legacy permanent EU residence (archived; replaced by EU+)
> - `EU` — EU card / Annex 8 — EU citizen registered for >3 months
> - `EU_plus` — EU+ card / Annex 8bis — EU citizen permanent (after 5 years)
> - `EU_citizen` — EU/EEA/CH citizen identity card or passport, present without a Belgian residence card (rare in this folder but possible if the user dropped it)
> - `other` — describe in `notes` if none of the above fit
>
> Note: a combined work + residence permit ("single permit" / "permis unique" / "gecombineerde vergunning") is **not** a distinct card type — it is an annotation on the actual card the bearer holds (usually `A` or `H`). Pick that card's value and record "single permit" in `notes`.
>
> **Read the validity dates.** Look for "Valid from / Valable du / Geldig van / Gültig von" and "Valid until / Valable jusqu'au / Geldig tot / Gültig bis." Format both as YYYY-MM-DD if you can read the day, otherwise YYYY-MM if only the month is legible. The bc-onboarding caller will convert to the YYYY-MM bucket the row_list expects; preserve as much precision as you can read.
>
> **Assign a confidence level.**
>
> - `high` — card type unambiguous from the visible markings, both dates fully legible
> - `medium` — card type clear but one date partially obscured or rotated; OR card type plausible but one of two visually similar types (e.g. A vs B, F vs F+)
> - `low` — card type unclear, or both dates unreadable, or the image is too small / blurry / angled for confident reading
>
> **Output strict JSON, nothing else.** No prose, no markdown fences, no commentary outside the JSON:
>
> ```json
> {
>   "card_type": "<one of the values above>",
>   "start_month": "<YYYY-MM-DD or YYYY-MM, or null if unreadable>",
>   "end_month": "<YYYY-MM-DD or YYYY-MM, or 'current' if the card is still valid and visibly unmarked end date, or null if unreadable>",
>   "confidence": "high|medium|low",
>   "notes": "<short free-text — only when confidence is medium/low or card_type is 'other'; explain what's uncertain. Empty string otherwise.>"
> }
> ```

## Pairing front and back

Many residence cards have two sides: the front carries the photo + name + card type marking; the back carries validity dates + machine-readable zone. The folder-drop user is instructed to drop both sides; filenames are user-chosen and not reliable for pairing.

**Pairing heuristics, in order of preference:**

1. **Filename hint** — if filenames contain `front`/`back`, `recto`/`verso`, `voorkant`/`achterkant`, or numeric pairs (`card1-1.jpg` + `card1-2.jpg`), trust the hint and pair before vision-extraction.
2. **Visual cues** — if no filename hint, vision-extract every image individually with the prompt above, then post-process: images where `card_type` was readable but dates were not → likely a front; images where dates were readable but `card_type` was not → likely a back. Pair by chronological proximity (cards with overlapping or adjacent date ranges) or by visual similarity (same colour scheme, same background pattern).
3. **Sequential ordering as last resort** — if pairing is ambiguous, fall back to sorted-filename order: even-indexed file = front, odd-indexed = back. Flag low confidence on the row.

Merge the paired results: `card_type` from the front-extraction; `start_month` / `end_month` from the back-extraction; pick the lower of the two confidence levels; concatenate notes if both have them.

## Two-fail fallback

bc-onboarding owns the retry policy (SKILL.md step **R2**, "two-fail retry policy"). This reference describes what counts as a "fail" for the purposes of that retry:

- The vision call returns invalid JSON (parse error) — **fail**.
- The vision call returns valid JSON but `confidence: low` AND `card_type` is null/empty/"other" with no recoverable signal in notes — **fail**.
- The vision call returns valid JSON with `card_type` set but both `start_month` and `end_month` null — **fail** (we have no usable temporal anchor for this row).
- Any other valid JSON with a non-null `card_type` and at least one non-null date — **pass**, even if confidence is low (the user re-confirms in the widget).

After two consecutive fails on the same image (or paired image set), bc-onboarding surfaces the manual-entry fallback (SKILL.md step R2: re-upload / type manually / skip).

## What this prompt does NOT do

- **No identity extraction.** Do not read or surface the cardholder's name, photograph, card number, NN/NRN, machine-readable zone, signature, or any identity-shaped field. The row_list captures categorical type + month-bucket dates only; everything else stays in the archived image.
- **No validity judgment.** Do not decide whether the card is genuine, current, or sufficient for any procedure. That's procedure-skill territory.
- **No cross-document reasoning.** Each image (or paired image set) is read in isolation. Chronological reconciliation of the resulting rows happens in the row_list confirmation widget, after the user reviews.

## Why this lives in bc-document-handler/references/

Card-image reading is structurally a document-handling concern — it's "reading a document the user provided." It just doesn't go through the normal extract-archive-confirm dialogue in `SKILL.md` because:

1. The row_list hydration owns its own confirmation surface (the `pre_rows` re-rendered widget, SKILL.md step R4), not the document-handler transparency dialogue.
2. The dropped images stay archived at `${SUBSTRATE_DATA}/<procedure-slug>/inputs/<field_name>/` (the same folder the user dropped them in, per the harness archive rule — SKILL.md step R2 "Archive rule"); the row_list hydration does not move or delete them.
3. Layer-1 scrub still runs on the resulting row's `notes` field (SKILL.md step R5), preserving the privacy contract.

The reference file pattern keeps SKILL.md tight while making the prompt findable from the document-handler concept space, which is where an agent investigating "how do we read user-provided images?" will look first.
