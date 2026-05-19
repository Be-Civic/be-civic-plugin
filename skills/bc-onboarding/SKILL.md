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

## Step 4. MCP `read_skill --with_form` call (D30, D33, D34, D42, D43)

Pick one of two MCP tools based on whether the gate skill produced a candidate procedure.

### 4.1. With a candidate procedure (most cases)

Call `mcp__becivic__read_skill` with `with_form: true`. Single round-trip — returns canonical body + form HTML together (D43, §1 of phase-2-contracts).

Request shape:

```json
{
  "skill_id": "<gate-skill's match, e.g. 'nationality-application' or 'apostille-foreign-document-hague'>",
  "with_form": true,
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

Response shape (per phase-2-contracts §1):

```json
{
  "skill_id": "nationality-application",
  "canonical": "<markdown body — cache in your context; bc-path-traversal will use it>",
  "form_html": "<branded HTML — pass directly to show_widget>",
  "locale_actual": "en",
  "locale_fallback_reason": null,
  "version": "<sha256-first-12>"
}
```

- **`mode: first-contact` is the only value this skill ever sends.** Returning and multi-active modes are owned by the harness, not by this skill (D34).
- **`pre_selected` derivation (D33):** scan the opener (and any preceding chat context) for the fields above. Extract conservatively — categorical fields only, never names / NN/NISS / addresses / document numbers. If unsure about a value, omit the key (the form will leave it blank). Procedure-specific fields go in `pre_selected` too if the opener volunteered them — e.g. `years_legal_residence_bucket: "5_to_10"` when the user said "I've been here 6 years."
- **`locale`** = the language the user opened in. Detect from the opener text. Mapping: EN → `en`, FR → `fr`, NL → `nl`, DE → `de`, Arabic → `ar`, Ukrainian → `uk`. Anything else → `en` (server returns `locale_fallback_reason` so you can surface the fallback note to the user — see step 6.4).
- **Cache the `canonical` field in your context** — `bc-path-traversal` will need it when this skill exits. Do not re-fetch.
- **Cache the `version` field** — it lands in the form's hidden inputs and must match on submit (§5 of phase-2-contracts).

### 4.2. Without a candidate procedure (low-confidence intent, "let's figure it out")

When the gate skill's intent classification was procedure-intent-vague AND no skill matched (zero hits on `find_skill`), call `mcp__becivic__get_onboarding_form` instead:

```json
{
  "app": "cowork",
  "locale": "<detected>",
  "pre_selected": { "region": "<...>", "civil_status": "<...>" }
}
```

Returns Section-1-only HTML (`form_html`). After submit, the agent runs procedure-routing in chat via AskUserQuestion or a Tier-2 elicitation form once enough is known to pick a procedure.

### 4.3. Failure handling

If either MCP call fails (timeout, connection error, HTTP 5xx, malformed response), drop straight to the fallback path in §11. Do not retry more than once; one retry max, then fallback.

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

---

## Step 8. Hand off to a new Cowork session

Once the folder is mounted, `profile.json` is written, and post-submit probing has cleaned up uncertain answers, end **this** conversation with the handoff line and let the user open the procedure subfolder in a **new** Cowork chat. Per `specs/cowork-plugin.md` §2.3 line 167, Cowork's CLAUDE.md auto-load convention walks ancestors at session-start and picks up the BeCivic-root CLAUDE.md, loading the harness as Project Instructions for the procedure-walking session. The new-session handoff is the only supported mode.

Hand-off line (in conversation language):

> "Setup is done. Open the project folder in a new Cowork conversation to continue — your new chat will have the Be Civic harness loaded automatically, and we'll walk through the <procedure name> from there."

If your Cowork client surface offers a click-through (e.g. "Open in new chat"), name the action plainly: *"Click here when you're ready and I'll be waiting in the new chat."* If no click-through exists, instruct the user to open the project folder manually (Cowork sidebar → Open folder → pick `<picked-parent>/BeCivic/<procedure-slug>/`).

**Do NOT proceed directly into `bc-path-traversal` in this conversation.** Cowork's ancestor-walk loads CLAUDE.md at session-start, not mid-conversation, so the harness would not be in context if you continued here. The 2026-05-19 dogfood session confirmed that attempting same-conversation continuation produces uninstrumented agent behaviour (six rule violations against clear harness instructions in a single session). See [`docs/agent-ux/handoff-spec-compliance-2026-05-19.md`](../../../bc-operations/docs/agent-ux/handoff-spec-compliance-2026-05-19.md) for the diagnosis.

### 8.1 If the user keeps chatting after the handoff line

The user may not immediately switch chats. If they ask follow-up questions in the onboarding conversation after you've delivered the handoff line:

- **Procedure questions** ("what document do I need first?", "do I need to apostille my birth certificate?") — do NOT walk the procedure here. Reply with: *"I'd love to walk you through that, but the Be Civic library only loads properly in a new chat opened from the project folder. Open `<path>` in a new Cowork conversation and ask me the same question there — I'll have the full procedure loaded."*
- **Quick clarifying questions about the setup itself** ("where is the folder again?", "is my profile.json correct?") — answer briefly here, then re-deliver the handoff line.
- **The user explicitly declines to switch** ("can we just keep going here?") — explain the constraint once more, plainly: *"I can answer general questions, but I can't walk the actual procedure here — the harness that drives the walk needs to load at the start of the session. The procedure work will be much better in a fresh chat."* If they still insist, fall back to advice-only mode (general procedure context from training knowledge, no document handling, no path traversal, no observation buffering) and flag this to the user.

Exit this skill cleanly otherwise. Subsequent procedure work (path traversal, document handling, observation buffering, session close) runs against the harness in the new session, not this skill.

---

## Fallback path — MCP unreachable (D44, §11 of phase-2-contracts)

Selection rule, in order:

1. **Primary**: `mcp__becivic__read_skill --with_form` (step 4).
2. **HTTP parity** (per phase-2-contracts §3): if MCP errors, `GET https://becivic.be/api/skills/<skill_id>?with_form=1&app=cowork&locale=<locale>&mode=first-contact` via WebFetch. Same response shape as MCP. Use `POST` if `pre_selected` or `profile_snapshot` need to ride along.
3. **WebFetch the canonical**: `https://becivic.be/skills/<skill_id>/canonical.md`. No form HTML; agent runs the form-equivalent inline.
4. **Local locale fallback HTML**: read `${CLAUDE_PLUGIN_ROOT}/skills/bc-onboarding/references/onboarding.<locale>.html` directly from disk. Pass to `mcp__visualize__show_widget`. **Section 1 only — no Section 2** (D45). After submit, run procedure-routing via AskUserQuestion (≤4 simple categorical prompts) or a Tier-2 elicitation form.

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

`bc-onboarding` **does not handle multi-active pivots**. When a returning user with existing active projects opens a new procedure mid-session, the harness CLAUDE.md handles it (per harness §9, §13). The harness calls `read_skill --with_form` with `mode: multi-active` and `profile_snapshot: <existing profile.json>`, gets back Section-2-only HTML, renders it, creates a new procedure subfolder under the existing BeCivic root. No Section 1, no consent, no new CLAUDE.md.

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
