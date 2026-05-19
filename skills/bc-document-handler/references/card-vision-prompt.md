# Card vision-extraction prompt (W25.14)

Reference prompt for the agent's vision capability when reading Belgian residence-card images dropped into a `row_list` folder-drop input (Mode 2 of the `belgian_residence_card_history` capture). Invoked by **bc-onboarding** post-submit hydration (SKILL.md §7.1) — not by this skill directly. Lives here because card-image reading is a document-handling concern; it just doesn't go through the normal `bc-document-handler` extract-and-archive flow (the row_list hydration owns its own dialogue).

## When to use this prompt

bc-onboarding's post-submit hydration loop, on detecting `__status: "pending"` with `__mode: "folder_drop"` on a `row_list` field, polls the `<procedure-root>/inputs/<input-name>/` folder. For each image file in that folder, run the agent's vision capability with the prompt below. Aggregate results into the structured rows that the row_list widget expects.

The prompt is designed for `belgian_residence_card_history`, the first user of the `row_list` type. Other `row_list` inputs that take image drops will need their own prompts in this directory (e.g. `references/diploma-vision-prompt.md` for an academic-history list); the current file is named for the card use case specifically.

## The prompt

Pass this as the system / instruction text alongside the image. Repeat per image (or per image pair where the agent has already paired front + back — see "Pairing front and back" below).

> You are reading an image of a Belgian residence document — typically a residence card (carte de séjour / verblijfskaart / Aufenthaltskarte), a long-stay visa (visa D) inside a passport, a short-stay Schengen visa (visa C), an Annex 15 / Annex 15bis "orange card," or an attestation d'enregistrement. Your job is to extract structured routing fields — not to transcribe the document.
>
> **Identify the card type.** Match to one of these values exactly (use the value, not the label):
>
> - `orange` — orange card / Annex 15 / Annex 15bis (paper, A4 or smaller, no chip, typically issued by the commune as a temporary attestation)
> - `A` — A card, temporary residence (electronic card, "Tijdelijk verblijf" / "Séjour temporaire" / "Befristeter Aufenthalt")
> - `B` — B card, long-term resident in the archived format (pre-2022; superseded by L for new issuances but still held by historical bearers)
> - `C` — C card, settled in the archived format (pre-2022; superseded by K)
> - `F` — F card, family member of EU citizen (archived format)
> - `F_plus` — F+ card, permanent family member of EU citizen ("Duurzaam verblijf" / "Séjour permanent" alongside the F+ marking)
> - `K` — K card, permanent resident / long-term (current format, post-2022)
> - `L` — L card, EU long-term resident (current format, post-2022)
> - `H` — H card, EU Blue Card (highly skilled worker)
> - `single_permit` — Single permit (combined work + residence permit; usually marked "Single permit" or "Permis unique" / "Gecombineerde vergunning")
> - `M` — M card, beneficiary of subsidiary protection
> - `N` — N card, recognised refugee
> - `visa_d` — Visa D (long-stay national visa, pasted into a passport page; "Type D" or "long séjour" visible on the visa sticker)
> - `visa_c` — Visa C (short-stay Schengen visa; "Type C" or the Schengen logo)
> - `EU_citizen` — EU/EEA/CH citizen identity card or passport (no Belgian residence card required; this is rare in this folder but possible if the user dropped it)
> - `other` — describe in `notes` if none of the above fit
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

bc-onboarding owns the retry policy (per SKILL.md §7.1, R5). This reference describes what counts as a "fail" for the purposes of that retry:

- The vision call returns invalid JSON (parse error) — **fail**.
- The vision call returns valid JSON but `confidence: low` AND `card_type` is null/empty/"other" with no recoverable signal in notes — **fail**.
- The vision call returns valid JSON with `card_type` set but both `start_month` and `end_month` null — **fail** (we have no usable temporal anchor for this row).
- Any other valid JSON with a non-null `card_type` and at least one non-null date — **pass**, even if confidence is low (the user re-confirms in the widget).

After two consecutive fails on the same image (or paired image set), bc-onboarding surfaces the manual-entry fallback per the design doc R5.

## What this prompt does NOT do

- **No identity extraction.** Do not read or surface the cardholder's name, photograph, card number, NN/NRN, machine-readable zone, signature, or any identity-shaped field. The row_list captures categorical type + month-bucket dates only; everything else stays in the archived image.
- **No validity judgment.** Do not decide whether the card is genuine, current, or sufficient for any procedure. That's procedure-skill territory.
- **No cross-document reasoning.** Each image (or paired image set) is read in isolation. Chronological reconciliation of the resulting rows happens in the row_list confirmation widget, after the user reviews.

## Why this lives in bc-document-handler/references/

Card-image reading is structurally a document-handling concern — it's "reading a document the user provided." It just doesn't go through the normal extract-archive-confirm dialogue in `SKILL.md` because:

1. The row_list hydration owns its own confirmation surface (re-rendered widget), not the document-handler transparency dialogue.
2. The archived images still go to `documents/<procedure-id>/inputs/<input-name>/` per harness §7 archive rule — the row_list hydration is responsible for that archive write before discarding the extraction-side image content.
3. Layer-1 scrub still runs (on the resulting row's `notes` field, per bc-onboarding §7.1), preserving the privacy contract.

The reference file pattern keeps SKILL.md tight while making the prompt findable from the document-handler concept space, which is where an agent investigating "how do we read user-provided images?" will look first.
