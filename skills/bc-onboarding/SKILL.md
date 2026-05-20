---
id: bc-onboarding
name: bc-onboarding
description: First-contact onboarding for Be Civic. Classifies opener intent, runs the confirmation gate, fetches the server-rendered branded onboarding form via MCP, renders it in Cowork, handles the post-submit folder mount + profile.json write, then hands off to bc-path-traversal. Owns first-contact only — returning and multi-active modes are owned by the harness.
version: 2.0.0
requires_capabilities:
  - cowork_directory_tool: mcp__cowork__request_cowork_directory
  - cowork_widget_tool: mcp__visualize__show_widget
  - becivic_mcp: mcp__becivic__read_skill, mcp__becivic__get_onboarding_form, mcp__becivic__find_skill
peer_skills:
  - be-civic                   # gate skill — classifies opener, decides whether to invoke this skill
  - bc-path-traversal          # next step after onboarding exits
  - bc-document-handler        # invoked downstream by bc-path-traversal; not by this skill directly
  - bc-session-close
---

# Be Civic — Onboarding (first-contact)

## Preamble

Be Civic is a tool for the user's agent, not an agent itself. The user already has an agent (you, running inside Cowork); Be Civic gives that agent a verified library of Belgian administrative procedures. This skill is the brand-impression beat where the user first sees Be Civic do something — a branded form, a project folder, and a clear handoff to their first procedure.

This skill owns **first-contact only**. It runs once per Be Civic project: classify the opener, confirm with the user, fetch and render the branded onboarding form, mount the folder after the user submits, write `profile.json` + `case.json` + the shared-root `CLAUDE.md` + `.be-civic/marker`, hand off to `bc-path-traversal`. Returning sessions (project already exists) and mid-session pivots to a second procedure are handled by the harness `CLAUDE.md`, not here.

---

## Step 1. Confirmation gate + shared-root CLAUDE.md + .be-civic/marker

This skill is invoked by the `be-civic` gate skill when no Be Civic project folder exists (no `.be-civic/marker` was found walking up from the cwd). Before this skill runs, the gate has already done two things:

- Detected the opener shape (procedure intent, meta, off-topic, or no-intent). Only **procedure intent** (clear or vague) routes here. Other shapes are handled by `be-civic` directly and never invoke this skill.
- Run the AskUserQuestion confirmation in the `be-civic` skill body: *"Yes, set up a Be Civic project"* / *"Just answer this one question"* / *"Not interested."* Only option A invokes this skill.

The artefacts this skill writes on submit (after the form, in step 8):

- **Shared root** = `<picked-parent>/BeCivic/`. One folder per user; every procedure the user runs is a subfolder beneath it.
- **Shared `CLAUDE.md` at the BeCivic root** (`<picked-parent>/BeCivic/CLAUDE.md`) from `${CLAUDE_PLUGIN_ROOT}/skills/bc-onboarding/references/harness-CLAUDE.md`. Cowork's CLAUDE.md auto-load walks ancestors and picks this up when the user opens any procedure subfolder. **Do NOT write a CLAUDE.md inside per-procedure subfolders** (D52).
- **Hidden marker** at `<picked-parent>/BeCivic/.be-civic/marker`. System-only files (marker, sessions, observation buffers, pending submissions) live under `.be-civic/` at the BeCivic root and stay hidden from the user's sidebar.
- **Shared profile + memory** at the BeCivic root: `profile.json` (from form values), `MEMORY.md` (empty narrative store, populated turn-by-turn by the harness), and `privacy-attachment.md` (copied from `${CLAUDE_PLUGIN_ROOT}/data/privacy-attachment.md` per D49).
- **Per-procedure subfolder** for the procedure the user is about to start — e.g. `<picked-parent>/BeCivic/nationality-application/`. Contains `case.json` (Section 2 form values) plus, as the procedure runs, `procedure_progress.md`, `documents/`, `memory/research-notes-*.md`. **No CLAUDE.md, no profile, no marker in here.**

**Do not create empty placeholder subfolders.** No `documents/`, `sessions/`, `memory/` upfront — they get created lazily by the relevant skills when there's actual content.

The whole write happens in step 8 after the user submits the form, not before. Steps 2–7 below describe everything that happens before the folder exists on disk.

---

## Step 2. Intent classification (4 shapes)

The `be-civic` gate skill already classified before invoking you. Confirm the shape; if it isn't one of the two listed below, refuse the invocation and route back to the gate.

| Shape | Example opener | Handling here |
|---|---|---|
| **procedure-intent (clear)** | "Help me apply for Belgian nationality" / "I need to apostille a US birth certificate" | Step 3 onwards. Skill-match confidence = high; confirmation copy names the procedure. |
| **procedure-intent (vague)** | "I think I need to do something at the commune?" / "My husband told me I should become Belgian." | Step 3 onwards. Skill-match confidence = medium or low; confirmation copy hedges. |
| **meta question** ("what data do you keep?") | n/a — gate skill handled in chat | **Do not enter this skill.** Gate skill answers from `${CLAUDE_PLUGIN_ROOT}/data/privacy-snippet.md` verbatim. No folder created. |
| **off-topic** / **no-intent** / **just exploring** | n/a — gate skill handled in chat | **Do not enter this skill.** Gate skill answers in chat with a 2–3 line tour or polite redirect. No folder created. |

For procedure-intent (clear or vague), the gate skill already asked the AskUserQuestion confirmation prompt and the user picked "Yes, set up a Be Civic project." Proceed.

---

## Step 3. Pre-form loading message (D19)

Composing the form takes a moment — skill-match + canonical fetch + form composition + pre-population. To prevent a silent pause, say the loading line **in the user's conversation language** before firing the MCP call:

> "Okay, I'm going to pull together an onboarding form for you. Just give me a moment while I analyse your case."

Translate verbatim per detected language:
- FR: *"D'accord, je vous prépare un formulaire d'accueil. Donnez-moi un instant pour analyser votre situation."*
- NL: *"Goed — ik stel even een intakeformulier voor u op. Eén moment terwijl ik uw situatie bekijk."*
- DE: *"In Ordnung — ich stelle Ihnen ein Aufnahmeformular zusammen. Einen Moment, während ich Ihre Situation prüfe."*
- AR: *"حسنًا، سأُحضّر لك نموذج البداية. لحظة واحدة بينما أحلّل وضعك."*
- UK: *"Гаразд, я зараз підготую для вас форму. Хвилинку, поки я ознайомлюся з вашою ситуацією."*

Fire the MCP call (step 4) immediately after sending the line — the call runs in parallel with the user reading.

---

## Step 4. MCP fetch — canonical + form (D30, D33, D34, D42)

**Two separate MCP calls**, each within tool-output budget on its own. The 2026-05-20 form-rendering refactor split the W24 single-round-trip (D43) shape into two surfaces because the combined payload (~135K wire) blew the host agent's tool-output budget. Now: one call for the canonical, one for the form HTML.

### 4.1. With a candidate procedure (most cases)

**(a) Fetch the canonical** via `mcp__becivic__read_skill`:

```json
{ "skill_id": "<gate-skill's match>" }
```

Cache the `body` field (markdown canonical) in your context — Section 2 validation (step 6.1) and post-submit sentinel-payload validation (step 7.2) both read the procedure's `inputs:` block from it. Do not re-fetch within this session.

**(b) Fetch the form HTML** via `mcp__becivic__get_onboarding_form` with the same `skill_id` so the server fetches the canonical, extracts its `inputs:` block, and renders Section 1 + Section 2 + consent.

Request shape:

```json
{
  "skill_id": "<gate-skill's match, e.g. 'nationality-application' or 'apostille-foreign-document-hague'>",
  "app": "cowork",
  "locale": "<detected, one of: en | fr | nl | de | ar | uk>",
  "mode": "first-contact",
  "pre_selected": {
    "region": "<one of: brussels | flanders | wallonia | german-speaking | not_yet_arrived>",
    "commune": "<free text, only if confidently extractable>",
    "civil_status": "<single | married | legal_cohabitation | divorced | widowed>",
    "nationality_situation": "<eu_citizen | non_eu_with_card | non_eu_no_card | not_sure>",
    "conversation_language": "<free text, language the user opened in>",
    "<procedure-specific-field>": "<value, if confidently extractable>"
  }
}
```

Response shape:

```json
{
  "skill_id": "nationality-application",
  "form_html": "<branded HTML — pass directly to show_widget>",
  "locale_actual": "en",
  "locale_fallback_reason": null,
  "version": "<sha256-first-12>"
}
```

- **`mode: first-contact` is the only value this skill ever sends.** Returning and multi-active modes are owned by the harness, not by this skill (D34).
- **`pre_selected` derivation (D33):** scan the opener (and any preceding chat context) for the fields above. Extract conservatively — categorical fields only, never names / NN/NISS / addresses / document numbers. If unsure about a value, omit the key (the form will leave it blank). Procedure-specific fields go in `pre_selected` too if the opener volunteered them — e.g. `years_legal_residence_bucket: "5_to_10"` when the user said "I've been here 6 years."
- **`locale`** = the language the user opened in. Detect from the opener text. Mapping: EN → `en`, FR → `fr`, NL → `nl`, DE → `de`, Arabic → `ar`, Ukrainian → `uk`. Anything else → `en` (server returns `locale_fallback_reason` so you can surface the fallback note to the user — see step 6.4).
- **Cache the `version` field** — it lands in the form's hidden inputs and must match on submit (§5 of phase-2-contracts).
- **Parallelise the two calls** if your tool runtime supports concurrent MCP invocations — they're independent reads. If not, do them sequentially in (a) then (b) order; (a) returns markdown the agent must hold, (b) returns HTML the agent passes straight to show_widget.

### 4.2. Without a candidate procedure (low-confidence intent, "let's figure it out")

When the gate skill's intent classification was procedure-intent-vague AND no skill matched (zero hits on `find_skill`), call `get_onboarding_form` **without** `skill_id`:

```json
{
  "app": "cowork",
  "locale": "<detected>",
  "pre_selected": { "region": "<...>", "civil_status": "<...>" }
}
```

Returns Section-1-only HTML (`form_html`). After submit, the agent runs procedure-routing in chat via AskUserQuestion or a Tier-2 elicitation form once enough is known to pick a procedure.

### 4.3. Failure handling

If the MCP call fails (timeout, connection error, HTTP 5xx, malformed response), drop straight to the fallback path in §11. Do not retry more than once; one retry max, then fallback.

---

## Step 5. Render the form via `mcp__visualize__show_widget`

Call `mcp__visualize__show_widget` with the `form_html` returned in step 4 as the `widget_code` parameter. The widget surface in Cowork displays the branded form; the user fills it; the in-form `<button type="submit">` triggers Cowork's `sendPrompt` round-trip back to you (step 6).

Do not modify the `form_html`. The server pre-applied locale, pre-population, RTL direction (for Arabic), and version stamping. The HTML is a self-contained `<div>` with inline styles; the `bc-*` class names are advisory for your post-submit read-back.

After firing `show_widget`, **wait silently for the submit**. Do not chat-fill while the form is open. The form contains:

- Hero panel: Belgian flag stripe, Be Civic wordmark, tagline, inline trust callout (D2 — always visible)
- Section 1 (always-on, 9 fields per phase-2-contracts §5):
  1. `region` (pills, single)
  2. `commune` (free text — hidden when region = `not_yet_arrived`, per D29)
  3. `civil_status` (pills, single)
  4. `nationality_situation` (pills, single — note: D29 adds `not_yet_arrived` residency variant)
  5. `conversation_language` (free text input, pre-filled with detected language per D27)
  6. `admin_language` (pills, single, region-filtered per D26)
  7. `preferred_name` (free text, optional)
  8. `has_id_card` (yes/no/not_sure — simplified per D23, no eID disambiguation here)
  9. `browser_driving_preference` (pills, single)
- Section 2 (dynamic) — procedure-routing questions from the matched skill's `inputs:` block joined against the inputs catalogue. **Omitted when `get_onboarding_form` was used.**
- Consent statement (D28) — required statement, not opt-in checkbox. Hidden input sends `alpha_consent_bundle: "yes"` automatically. **`get_onboarding_form` may omit this when called from non-onboarding contexts; for this skill, it is always present** because mode is always `first-contact`.
- Submit button (`Continue →`)

---

## Step 6. Handle the `sendPrompt` round-trip (D11)

When the user clicks Continue, Cowork's `sendPrompt` returns a flat JSON `{ field: value }` payload back as a chat message. Receive it; do not respond conversationally yet. Run the following sequence.

### 6.1. Validate the payload

Validate against:
- Section 1 fields against `${CLAUDE_PLUGIN_ROOT}/schemas/profile.schema.json` (region enum, civil_status enum, nationality_situation enum, has_id_card enum, browser_driving_preference enum, alpha_consent_bundle exists and equals `yes`, hidden `version` matches what step 4 returned).
- Section 2 fields against the procedure's `inputs:` block (already in the canonical you cached). Each value should be one of the input's declared enum values or a free-text string (per the input's `type`).

If a value fails validation, **do not abort**. Cache the invalid value, note it for post-submit probing (step 7), and continue — the form may have a stale catalogue version or the user typed something unexpected in a free-text field. The agent treats the form as the opening salvo, not the final word (D21).

If `alpha_consent_bundle` is absent (the user never submitted — they read the consent statement and closed the form), follow the **decline path** in §6.5 below.

### 6.2. Request the directory

Call `mcp__cowork__request_cowork_directory`. The user picks a **parent folder** (Desktop, home, Documents, wherever).

If the user cancels the picker, do not silently abort. Say: *"I need a folder to save your project. Want to try the picker again, or save without a folder for now and come back to it?"* — the latter degrades to advice-only mode (no folder, no profile.json, no marker; the agent continues in-chat).

### 6.3. Create the BeCivic folder structure

Inside the picked parent, create `BeCivic/<procedure-slug>/` where `<procedure-slug>` is derived from the matched skill_id (e.g. `nationality-application` → `nationality-application`; for `get_onboarding_form` cases where no procedure was matched, use `intake` as a placeholder).

Write the following files (in this order):

1. **`<parent>/BeCivic/.be-civic/marker`** — small text file with the project version. Use the template at `${CLAUDE_PLUGIN_ROOT}/skills/bc-onboarding/references/project-init/.be-civic/marker`.
2. **`<parent>/BeCivic/CLAUDE.md`** — only if it doesn't already exist (D52 — single shared CLAUDE.md). Copy from `${CLAUDE_PLUGIN_ROOT}/skills/bc-onboarding/references/harness-CLAUDE.md`.
3. **`<parent>/BeCivic/profile.json`** — Section 1 values + consent block:
   ```json
   {
     "region": "<value>",
     "commune": "<value or empty>",
     "civil_status": "<value>",
     "nationality_situation": "<value>",
     "conversation_language": "<value>",
     "admin_language": "<value>",
     "preferred_name": "<value or empty>",
     "has_id_card": "<value>",
     "browser_driving_preference": "<value>",
     "consent": {
       "alpha_bundle": true,
       "signed_at": "<ISO 8601 UTC timestamp>",
       "version": "<form's version hash from hidden input>"
     }
   }
   ```
4. **`<parent>/BeCivic/MEMORY.md`** — empty narrative store from `${CLAUDE_PLUGIN_ROOT}/skills/bc-onboarding/references/project-init/MEMORY.md`.
5. **`<parent>/BeCivic/privacy-attachment.md`** — copy of `${CLAUDE_PLUGIN_ROOT}/data/privacy-attachment.md` (D49 — visible to the user in their file manager).
6. **`<parent>/BeCivic/<procedure-slug>/case.json`** — Section 2 values plus any procedure-routing extras you captured pre-form. Shape is per-procedure; minimum:
   ```json
   {
     "skill_id": "<matched skill_id>",
     "<input-name>": "<value>",
     ...
   }
   ```

Do **not** pre-create empty subdirectories (`documents/`, `sessions/`, `memory/`). They get created lazily by the relevant skills when there's content.

### 6.4. Acknowledge with the locale + path

Confirm to the user, in their conversation language:

> "Saved locally at `<absolute path to BeCivic/<procedure-slug>/>`. Only the categorical fields you ticked travel — your name, address, identifiers stay in this folder."

The second sentence is **JIT trust clause 1** (anonymity — see §7 below); it fires naturally at folder-mount time.

If `locale_fallback_reason` from step 4 was non-null (server didn't have the requested locale), surface the fallback notice now:

> "I showed you the form in English — your preferred locale isn't shipped yet. Everything else works the same; we'll talk in <conversation_language> from here."

### 6.5. Decline path (D28, D51, Scenario 11)

If the user reads the consent statement and **does not submit** — typically they ask in chat *"can I turn off the telemetry?"* or *"I don't want to participate in the alpha"* — the path is:

1. Acknowledge: *"Be Civic is opt-in during alpha — telemetry and observations are part of the deal during pre-launch. Granular controls come post-alpha. If you'd rather wait until those ship, that's fine — come back when we've shipped granular controls. No project is created until you submit the form."*
2. **Do not call `request_cowork_directory`.** Do not write profile.json. Do not write the marker.
3. Exit the skill cleanly. No folder. No state. The user leaves the same surface they arrived at.

Form-submit-as-consent (D28) is structural: not submitting *is* the way to decline. There is no separate "decline" button; do not invent one.

---

## Step 7. JIT trust contract delivery (D2, D46 dropped)

Four trust clauses fire at their natural triggers. **Do not track clause-seen-state** (D46 was dropped). If a clause's teach fires again because the user re-encountered the trigger after seeing it in chat, that is fine.

| Clause | First trigger | Copy (translate to conversation language) |
|---|---|---|
| **1. Anonymity** | Step 6.4 — after folder mounts | *"Saved locally at `<path>`. Only the categorical fields you ticked travel — your name, address, identifiers stay in this folder."* |
| **2. Document discipline** | First document upload (in `bc-document-handler`, after this skill exits) | *"Got it — filed under `documents/<procedure-slug>/`. I'll read this to pull out the facts I need (dates, statuses, issuing authority), then work from those. The document itself stays in your folder."* |
| **3. Forward-only state** | First disambiguator fires (post-submit probing — see step 7.1) | *"Hold on — earlier you said single, now this reads as married. I don't silently overwrite earlier answers, so let me check which one's right before I change anything."* |
| **4. Review-before-submit** | First non-validation observation buffers (in harness §8, after this skill exits) | *"I'm noting that as a concern about the skill — I'll show you everything I've buffered at the end of the session so you can review item-by-item before any of it goes to becivic.be."* |

Inline trust callout in the form hero (D2) fires automatically — it's in the `form_html`, you don't need to add anything.

### 7.1. Post-submit probing (D21, D22)

Onboarding doesn't end at submit — the form is the **start** of high-confidence capture. Probe the cached payload from step 6.1 for these patterns:

- **"I'm not sure" answers** — ask the user about it in chat. Example: *"You marked 'Not sure' for years of legal residence — the rule is straightforward: continuous registered residence in Belgium, no interruptions. Walk me through your card history?"* If the answer turns on a document the user might have, offer the evidence path: *"Or, send me a photo of your card and I can read the type off it."*
- **Contradictions with the opener** — if a form value contradicts something the user said in chat earlier, fire trust clause 3 and ask which is right. Do not silently overwrite.
- **Load-bearing-for-procedure fields** — anything the procedure body depends on (residence dates, exact card type, exact employment status) that the form captured at low confidence. These often need a document, not just a self-report. Note for `bc-path-traversal` to follow up.

This is the "lawyer onboarding a client" pass. Spend the exchanges it takes to get the picture right before handing off to the procedure.

### 7.2. row_list hydration for sentinel payloads (W25.13)

Some form-input types (currently only `row_list` — see `specs/schemas.md` "Form-input types" and `specs/protocol.md` §23.2 sentinel-payload paragraph) support deferred-capture modes. When the user picked Mode 2 (folder drop) or Mode 3 (chat) on a `row_list` field, the submit payload carries a sentinel object instead of the structured rows:

```json
{ "<field_name>": { "__mode": "folder_drop"|"chat", "__status": "pending" } }
```

After 6.1 validation but **before** writing case.json / profile.json in step 6.3, scan every field in the submit payload for the sentinel shape and run the matching hydration. The structured value the hydration produces replaces the sentinel before the write.

#### 7.2.1. Sentinel rejection (defense layer 2 — closes B3)

Before routing to hydration, validate that the sentinel only appears on input types that declared capture modes. The procedure canonical's `inputs:` block (cached in step 4) tells you each field's `type`; the inputs catalogue declares which types support sentinels. Today that allowlist is: **`row_list` only**. If a sentinel appears on `single_choice`, `text`, `yes_no`, or any other input type:

1. **Reject.** Do not route to hydration. The server-side renderer should never have produced this shape; receiving it means either a stale client or a tampered submit.
2. **Log it** to the observation buffer as a `harness_anomaly` observation with category `sentinel_on_non_row_list` and the field name + input type recorded. The buffer goes through the normal review-before-submit flow at session close.
3. **Treat the field as missing.** Re-prompt the user for that field in chat using the input's normal copy (single AskUserQuestion or short Tier-2 elicitation), as if the form had returned `null` for it. Do not fabricate a value.

This is defense layer 2 — the server-side rejection in `specs/protocol.md` §23.2 is layer 1; this is the harness-side safety net.

#### 7.2.2. Mode 2 — folder_drop hydration

The user dropped image files into `<procedure-root>/inputs/<field_name>/` while the form was open (or is about to — the instruction panel in the form told them so). Folder polling waits for the user signal before reading; the user may not have started yet.

**Wait for the user signal.** Send a chat line in the conversation language:

> *"When you've dropped your card photos in the folder and are back here, just say 'done with cards' or anything that tells me you're back — I'll read them and walk you through what I found."*

Hold position. The next chat message from the user is the trigger — any message that reads as "I'm back" / "done" / "go ahead" / "ready" / a sigh / a single dot / etc. The agent uses judgment; the user is not required to say a magic word.

When the trigger lands, list the folder. For each image file:

1. **Run the agent's vision capability** with the prompt at `${CLAUDE_PLUGIN_ROOT}/skills/bc-document-handler/references/card-vision-prompt.md` (loaded verbatim). One vision call per image, OR one call per paired front+back set (see the prompt's pairing heuristics).
2. **Parse the JSON output.** The prompt instructs the model to return strict JSON; if parsing fails, that's fail #1 (see retry policy below).
3. **Score the read** per the prompt's pass/fail rules: valid JSON with a non-null `card_type` and at least one non-null date = pass. Anything else = fail.

**Two-fail retry policy (per design doc R5).** On the *second* consecutive failure for the same image (or paired set), stop retrying that image and surface to the user in chat:

> *"I couldn't read `<filename>` clearly — want to upload a clearer photo, or just type that row in manually? Other cards I read fine, so this is per-card, not the whole set."*

Three branches:

- **Re-upload.** User drops a new image; restart the two-attempt cycle on the new file. Discard the old image from the read-set (it stays archived per harness §7 but doesn't contribute a row).
- **Type manually.** The card hydrates as an empty/partial row pre-populated in the widget for that card — `card_type: null`, dates null, notes blank. Other readable cards still hydrate normally with their extracted values. The user fills the manual row in the re-confirmation widget (7.2.4).
- **Skip.** No row is added for that image. Other readable cards still hydrate.

Once the read-set is fully resolved (every image is a pass, a manual-entry placeholder, or a skip), assemble the structured rows array — one row per pass or manual placeholder, in chronological order by `start_month` (nulls sort last). Hand off to the re-confirmation widget (7.2.4).

**Archive note.** The dropped images stay in `documents/<procedure-id>/inputs/<field_name>/` per harness §7 archive rule. The hydration does NOT move them, rename them, or delete them — the user owns the archive.

#### 7.2.3. Mode 3 — chat hydration

Elicit conversationally. In the conversation language, send:

> *"Walk me through your card history, oldest first. For each card, tell me the type (A, F+, single permit, etc.) and the rough dates you held it. Don't worry about exact day — month and year is enough."*

The user replies in prose. Parse their reply into the structured-row shape — one row per card mentioned, in chronological order:

```json
{
  "card_type": "<one of the catalogue enum values>",
  "start_month": "<YYYY-MM>",
  "end_month": "<YYYY-MM or 'current'>",
  "notes": "<short free text, optional>"
}
```

**Parsing rules:**

- Map user-language card descriptions to the catalogue enum. The catalogue's full enum + labels lives in `bc-docs/mcp/forms/inputs/<field_name>.yml`; for `belgian_residence_card_history` the values are `orange | A | B | C | F | F_plus | K | L | H | single_permit | M | N | visa_d | visa_c | EU_citizen | other`. "F+" → `F_plus`, "Blue Card" / "Carte bleue" → `H`, "single permit" / "permis unique" / "gecombineerde vergunning" → `single_permit`, etc. Use judgment.
- Bucket dates to YYYY-MM. "Spring 2018" → ask the user to pick a month. "Around 2018" → `2018-01` if they don't refine, with a `notes` entry recording the approximation. Current card → `end_month: "current"`.
- Empty cards (`card_type: "EU_citizen"`) get null dates per the design doc D7 — EU citizens don't have residence-card dates in the same sense.
- Cap `notes` at 200 chars per the catalogue.

If the user's reply is ambiguous on a row (can't pick a card_type, or dates are vague), do NOT silently guess — ask a clarifying follow-up in chat, then update that row. Iterate until every row is parseable.

Once the rows array is assembled, hand off to the re-confirmation widget (7.2.4).

#### 7.2.4. Re-confirmation widget (Mode 2 + Mode 3)

Regardless of mode, present the parsed rows back to the user in the same `row_list` widget for in-place confirm/edit. Render via `mcp__visualize__show_widget` with the same widget HTML the server returned in step 4, but pre-populated with the rows array you assembled. (The widget supports pre-population because it's the same surface Mode 1 uses; pre-fill semantics are described in the design doc §3 Mode 2 step 3.)

Frame in chat (conversation language):

> *"Here's what I got — give it a quick look. Edit anything that's off, add rows I missed, and hit Continue. If a row's totally wrong, just clear it."*

Wait for the second submit. Validate the returned rows array against the catalogue's column types (`card_type` is one of the enum, `start_month` is `^[0-9]{4}-[0-9]{2}$` or null-for-EU-row, `end_month` matches `^([0-9]{4}-[0-9]{2}|current)$` or null-for-EU-row, `notes` ≤ 200 chars). On validation failure, re-render with an inline error per row.

On approve (clean validation), proceed to the scrub + write (7.2.5).

#### 7.2.5. Notes Layer-1 scrub (closes R3) + write

Before writing the final array to its target store, run `scripts/scrub-layer1.py` against the `notes` field of each row:

```bash
scripts/scrub-layer1.py --stdin --field notes
```

For each row whose notes field returns `status: "rejected"` (high-severity hit — identity, biometric, document_number):

1. **Do not write the array yet.** Surface to the user in chat, citing the row by index + the redaction category:

   > *"The note on row <N> tripped the scrub check — something in there reads as identity-shaped (<category>). Want to rewrite it more abstractly, or just clear that note?"*

2. **User picks via AskUserQuestion:** rewrite, or clear. On rewrite, capture the new value, re-scrub, loop until clean or cleared.
3. **Do not silently redact and proceed.** The scrub is load-bearing for the privacy contract; every hit goes through the user.

Rows with `status: "redacted"` (medium severity, regex made a safe substitution) write the redacted version without prompting — same policy as `bc-document-handler`'s scrub-failure abort.

Once every row's notes field is clean, write the array to its target store:

- `render: profile` (the design's default for `belgian_residence_card_history`) → write to `<BeCivic-root>/profile.json` under the field name.
- `render: case` (other future row_list inputs may declare this) → write to `<BeCivic-root>/<procedure-slug>/case.json` under the field name.

Read the input's `render:` directive from the procedure canonical's `inputs:` block (cached in step 4) — do not hardcode by field name.

#### 7.2.6. Hydration completes — step 7.1 probing continues

After the row_list field hydrates, return to step 7.1 probing for any remaining "I'm not sure" / contradiction / low-confidence-load-bearing patterns in the rest of the payload. The row_list hydration may itself surface new probes (e.g. card history reveals a residence gap the procedure body cares about); flag those for `bc-path-traversal` to follow up post-handoff.

---

## Step 8. Hand off to `bc-path-traversal`

Once the folder is mounted, profile.json is written, and post-submit probing has cleaned up uncertain answers, hand control to `bc-path-traversal`. That skill takes the cached canonical from step 4 plus the case.json from step 6.3 and walks the procedure's required documents.

Hand-off line (in conversation language):

> "Setup is done. Let me walk you through what you'll need for the <procedure name>."

If this skill is running in `new-project` mode where the user is in a transient setup conversation (the legacy mode), close with:

> "Setup is done. From here, open this folder in Cowork to continue — the next conversation you open from this folder will have the Be Civic harness loaded automatically."

In the post-`request_cowork_directory` Cowork pattern (the V1 default for first-contact), the folder is already mounted in the current conversation and the harness CLAUDE.md is being loaded by Cowork's ancestor-walk. Proceed directly into `bc-path-traversal` in the same conversation.

Exit this skill cleanly. Do not loop. Subsequent procedure work (path traversal, document handling, observation buffering, session close) runs against the harness, not this skill.

---

## Fallback path — MCP unreachable (D44, §11 of phase-2-contracts)

The Step 4 two-call pattern is the primary path. Each call has its own fallback chain. On any failure in any leg, try the next rung; if all rungs fail for the form fetch, drop to local-locale-HTML + chat-driven Section-2 capture.

**Canonical fetch fallback chain** (Step 4 (a)):

1. **MCP**: `mcp__becivic__read_skill { skill_id }`.
2. **HTTP parity**: `GET https://becivic.be/api/skills/<skill_id>` via WebFetch. Returns the canonical markdown directly.
3. **Direct canonical**: `WebFetch https://becivic.be/skills/<skill_id>/canonical.md`. Last-resort if the api Worker is down too.

If all three fail: continue without the cached canonical. Section 2 validation degrades to a server-side-only check (the form composer already validated the inputs); post-submit sentinel-payload validation reads `data-rowlist="*"` attributes off the rendered form_html to identify which fields support sentinels.

**Form fetch fallback chain** (Step 4 (b)):

1. **MCP**: `mcp__becivic__get_onboarding_form { skill_id, ... }`.
2. **HTTP parity**: `GET https://becivic.be/api/onboarding-form?skill_id=<id>&app=cowork&locale=<locale>&mode=first-contact` via WebFetch. Same response shape as MCP. Use `POST` to ride `pre_selected` and `profile_snapshot` if they're too large for query strings.
3. **Local locale fallback HTML**: read `${CLAUDE_PLUGIN_ROOT}/skills/bc-onboarding/references/onboarding.<locale>.html` directly from disk. Pass to `mcp__visualize__show_widget`. **Section 1 only — no Section 2** (D45). After submit, run procedure-routing via AskUserQuestion (≤4 simple categorical prompts) or a Tier-2 elicitation form.

**Surface the fallback notice to the user** (G24, Sc 20). In conversation language:

> "My full Be Civic library isn't reachable right now — there's a network blip on the server side. I can still set you up with the core profile form locally and ask the procedure-specific questions in chat. Want to keep going, or wait and come back?"

If the local locale file is also missing or unreadable (last-resort degradation), collect Section 1 in chat via AskUserQuestion only — region, civil status, nationality_situation, has_id_card, conversation language, admin language, browser_driving_preference, preferred name. Still write profile.json. Still write the marker. The folder mount + harness handoff still happens. Tell the user honestly: *"All my normal surfaces are down today — I'm asking you these in chat. Same data, less polish."*

---

## Returning-user mode (short-circuit)

`bc-onboarding` **does not handle returning users**. The harness CLAUDE.md owns the returning flow (per harness §3 step 1 and §13).

If you are somehow invoked when a `.be-civic/marker` already exists (shouldn't happen — gate skill checks this first), refuse and route back:

> "You already have a Be Civic project at <path>. The harness will pick up automatically — close this conversation and open the project folder."

Do not re-run onboarding. Do not overwrite profile.json. Do not re-write CLAUDE.md.

---

## Multi-active mode (short-circuit)

`bc-onboarding` **does not handle multi-active pivots**. When a returning user with existing active projects opens a new procedure mid-session, the harness CLAUDE.md handles it (per harness §9, §13). The harness calls `get_onboarding_form` with the new `skill_id`, `mode: multi-active`, and `profile_snapshot: <existing profile.json>`, gets back Section-2-only HTML, renders it, creates a new procedure subfolder under the existing BeCivic root. No Section 1, no consent, no new CLAUDE.md. (Canonical for the new procedure is fetched via `read_skill` in parallel, same two-call pattern as first-contact.)

If you are invoked when active projects exist (again, shouldn't happen — gate skill checks first), refuse and route back to the harness:

> "You're already in a Be Civic project. The harness handles new procedures — pass control back."

---

## Meta-question handling (D31, D47)

`bc-onboarding` **does not handle meta questions**. The `be-civic` gate skill answers meta questions in chat from `${CLAUDE_PLUGIN_ROOT}/data/privacy-snippet.md` **verbatim** (D47 — canonical privacy answer).

If the user asks a meta question mid-onboarding (between step 3 and step 5, before they submit the form), pause the form flow, answer from `privacy-snippet.md` verbatim, then offer:

> "Want me to continue with the onboarding form, or keep talking about the data side first?"

If they want to keep talking about the data side, hold the form open in the background. If they decide not to proceed, follow the decline path (§6.5). **Never paraphrase the privacy snippet** — load it from the file and quote it.

---

## Belgium-not-yet-arrived path (D29)

When the user has not yet moved to Belgium, the form's `region` field includes a `not_yet_arrived` option (5th pill in the region row). When that's selected:

- The `commune` field **hides entirely** (the user doesn't know yet).
- The `nationality_situation` pills include `non_eu_no_card` and the form's friendly variant *"Third-country, applying from abroad."*
- The `admin_language` pills stay present; the hint adapts: *"Pick the language for the region you're considering: Brussels — French or Dutch; Wallonia — French; Flanders — Dutch; German-speaking community — German. If you really don't know, pick French or Dutch for now — you can change this later."*

No special branching in this skill. The pre-move user goes through normal skill-matching, normal Section 2 routing (if a procedure was matched), normal post-submit probing, normal folder mount. The form just doesn't trap them at "what commune?" and doesn't force a region choice that doesn't apply yet.

In `profile.json` the saved values are `region: "not_yet_arrived"`, `commune: ""` (empty string, not null). The harness reads these and adapts downstream.

---

## What this skill does NOT own

- The harness rules (Iron Law, situation assessment, observation handling, document handling, session close). Those live in the project's `CLAUDE.md` after this skill writes it.
- Procedure walking, document extraction, path traversal. Those are peer skills (`bc-path-traversal`, `bc-document-handler`) invoked by the harness.
- Returning sessions, multi-active pivots. The harness handles those (§13 / §9).
- Meta-question answering. The `be-civic` gate skill handles those from `privacy-snippet.md`.
- Off-topic redirect or no-intent tour. The `be-civic` gate skill handles those.

This skill exists for one thing: take a user who said yes at the gate's confirmation prompt → produce a mounted Be Civic project with a clean profile.json, a shared root CLAUDE.md, a per-procedure subfolder with case.json, and a clean handoff to `bc-path-traversal`.
