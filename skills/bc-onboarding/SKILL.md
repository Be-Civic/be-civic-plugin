---
id: bc-onboarding
name: bc-onboarding
description: First-contact onboarding for Be Civic. Runs the verified flow — taste (explain the plan from the public manifest) before any email ask, then an email→code access widget (start-verification emails a 6-digit code → verify with the code), then state-shape activation across the hidden and visible substrate surfaces — and ends with a clean handoff into a fresh chat opened inside the project folder, where the working session begins. Falls back to anonymous read-only mode if the user declines verification. Owns first-contact only; returning and multi-active modes are owned by the harness.
version: 3.2.0
requires_capabilities:
  - cowork_directory_tool: mcp__cowork__request_cowork_directory
  - cowork_widget_tool: mcp__visualize__show_widget
  - web_fetch: WebFetch
peer_skills:
  - be-civic                   # gate skill — classifies opener, decides whether to invoke this skill
  - bc-path-traversal          # next step after onboarding exits
  - bc-document-handler        # invoked downstream by bc-path-traversal; not by this skill directly
  - bc-session-close
---

# Be Civic — Onboarding (first-contact)

## Preamble

Be Civic is a tool for the user's agent, not an agent itself. The user already has an agent (you, running inside Cowork); Be Civic gives that agent a verified library of Belgian administrative procedures. This skill is the brand-impression beat where the user first sees Be Civic do something useful — *before* it asks for anything in return.

This skill owns **first-contact only** — the "get set up" conversation (Chat 1). It runs once per Be Civic substrate: show the user product taste, capture and verify their email, mint their pseudonymous identity, write the two-surface state shape, then **end this conversation by moving the user into one fresh chat opened inside their project folder** where the work begins. Returning sessions (marker already exists) and mid-session pivots to a second procedure are handled by the harness `CLAUDE.md`, not here.

This conversation is **setup only**: taste, email, verification, and writing the project to disk. The procedure interview — the about-you form and the real walk-through — happens in the *next* chat, after the user opens their project folder and the harness loads. Do **not** ask the user about their situation here, and do **not** render the about-you onboarding form here. Setting up the project, then handing the user cleanly into it, is the whole job.

The crux is **taste before gate**. The first thing the user sees is what Be Civic does, never an email field. Onboarding that opens with an email ask is non-compliant.

### Two substrate surfaces

Everything this skill writes lands on one of two surfaces. Read their paths from the preamble's session-state lines — never hardcode.

| Surface | Var | What it holds |
|---|---|---|
| Hidden, agent-managed | `${SUBSTRATE_STATE}` (= `${CLAUDE_PLUGIN_DATA}`) | `.env` (harness_key only), `user-id`, `profile.json`, `preferences.json`, `procedures.json`, `version.json`, `sessions/`, `.be-civic/marker` (pointer → visible path), `.pending-verification` (transient) |
| Visible, user-picked | `${SUBSTRATE_DATA}` (= `<picked-parent>/BeCivic/`) | `CLAUDE.md`, `MEMORY.md`, `.be-civic/marker` (version stamp), `documents/`, `<procedure-slug>/` |
| Read-only install | `${SUBSTRATE_ROOT}` (= `${CLAUDE_PLUGIN_ROOT}`) | the shipped plugin (templates, schemas, data, scripts) |

**Identity rule.** The harness key in `.env` is NEVER committed, echoed to chat, or logged. It is excluded from git structurally — it is simply absent from the hidden-surface `.gitignore` allowlist. Do not print it back to the user, ever.

---

## Step 1. Taste first — explain the plan before any email ask

The gate (`be-civic`) invoked you on confirmed procedure intent + absent marker. It passed you the classified intent shape (`procedure_intent_clear` or `procedure_intent_vague`), a candidate Process id if it matched one, the conversation language, and the opener text.

**Before you ask for anything, show the user what Be Civic does — by explaining the plan for their procedure.** The taste is not a half-performed run of their case and it is not a generic brochure: it is an honest preview of the procedure they came for — the stages they'll go through, the documents they'll gather, and what they'll walk away with. At this point the harness has only the anonymous-read tier (`corpus:read:public`) — no Bearer, no local state.

Read the plan from the **public manifest outline** via the **`WebFetch`** tool (no `Authorization` header — anonymous-read tier):

1. `GET https://becivic.be/api/manifest` → `{ version, generated_at, entries }`. The entity graph is in `.entries` (top-level — there is no `.data` wrapper). Search the entries client-side by `title` / `summary` / `applies_to` against the user's intent to find the Process the gate matched (or the closest match).
2. Read that entry's **`outline`** object — `.entries[].outline` — which may carry up to three lists:
   - `outline.outcomes` — what the user ends up with when it's done. **Always present.**
   - `outline.stages` — the phases the procedure moves through, in order. Present only on flagship Processes; empty array otherwise.
   - `outline.documents` — the documents the user will need to gather. Present only on flagship Processes; empty array otherwise.
3. Explain the outline back to the user in their conversation language, in plain prose. **Render only what is present — do not print empty "Stages:" or "Documents:" sections.** If `stages` and `documents` are empty, lead with `outcomes` plus a brief general framing (e.g. "I have the key milestones and what you'll walk away with — once we're set up I'll walk you step by step through each one"). If all three are present, explain the stages they'll go through, the documents they'll line up, and the outcome. This is the "oh, that's exactly my situation" moment.

The outline is a **preview, never instructions** — it tells the user the shape of the journey, not the step-by-step of how to do it. Do not present fees, deadlines, or per-step detail at this beat: those are full-procedure content that comes after verification. Keep dates and amounts out of the taste entirely.

**Do NOT fetch a Process body at this beat.** No Process is public; an anonymous `GET https://becivic.be/api/processes/<id>` without a Bearer returns `401`. The taste reads only the manifest `outline`. If the manifest entry has no `outline` yet, or nothing in the manifest matches the user's intent, fall back to a short branded framing of what Be Civic is and what it covers in plain language:

- **Branded framing via `mcp__visualize__show_widget`** — a short branded panel that says what Be Civic is (a verified library of Belgian procedures, run by the user's own agent, kept on the user's own machine) and what's about to happen. Use the brand palette documented in `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/onboarding.<locale>.html` (gold `#fae042`, red `#ed2939`, cream `#f5f4ee`, ink `#1a1a18`; remember Cowork's `all: unset` rule for bare form elements).

Keep this beat short. The goal is one clear "that's my procedure" moment, then the email ask — not an exhaustive walkthrough before the user has opted in.

### 1.1. Anonymous-read fallback (user declines verification)

If at any point the user declines to verify by email — "I don't want to give my email", "can I just look around?", "not yet" — **do not push.** Skip steps 2–6 entirely and operate read-only:

- Reads run against `corpus:read:public` with **no Bearer** — the manifest and its per-Process `outline` (the `WebFetch` calls above). Process bodies stay gated (anonymous `GET /api/processes/<id>` returns `401`).
- **No submissions are possible** — Issues, Validations, Feedback, Ratings all require the pseudonymous tier. No folder is mounted; no `${SUBSTRATE_STATE}` state is written; no marker.
- Frame the limit kindly, in conversation language: *"No problem — I can show you what's in the library and walk you through procedures right now, without an email. The thing email unlocks is saving your progress to a folder on your machine and contributing anonymous notes back so the next person has it easier. Say the word whenever you'd like to set that up."*
- The mode persists for the session. The user can opt in later by re-stating intent — pick back up at step 2.

---

## Step 2. Email + code — the access widget

When the user signals they want to proceed (after the taste beat, or a "yes, set me up"), render the **shipped access widget** via `mcp__visualize__show_widget`, passing the contents of `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/onboarding-access.<locale>.html` as `widget_code`. (EN ships today; for a locale not yet authored, fall back to the EN file.)

This is **one widget, two steps** — you do not render a second widget:

- **Email step.** A single email field with live validation, plus a required one-time tick acknowledging the Privacy Statement + Terms of Use (`becivic.be/privacy` and `/terms`). Continue stays disabled until the email is valid **and** the box is ticked; on submit the widget reveals the code field in place. (Filling the email still *is* the consent to use it for verification; the tick is the separate Privacy/Terms acknowledgement.)
- **Code step.** The user types the 6-digit code emailed to them (the service sends it when you call Step 3) and submits.

The widget talks back to you via `sendPrompt`, as plain chat messages with three prefixes:

| Message you receive | Meaning | Your action |
|---|---|---|
| `[Be Civic access] email: <addr>` | User submitted their email | Step 3 — start verification for `<addr>` |
| `[Be Civic access] code: <digits>` | User entered the code | Step 5 — verify with the held `verification_id` + `<digits>` |
| `[Be Civic access] resend` | User asked to resend | Re-run Step 3 for the held email; a fresh code is emailed |

Hold the email address and the `verification_id` (from Step 3) in working memory across these messages.

If the user **closes the widget without submitting**, treat it as a decline and fall to the anonymous-read fallback (§1.1).

---

## Step 3. Start verification — `POST /api/auth/start-verification`

On the `[Be Civic access] email: <addr>` message, validate the address shape locally (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`), then call the start endpoint via **`WebFetch`**. **No auth header** — the user has no key yet.

```
POST https://becivic.be/api/auth/start-verification
Content-Type: application/json

{ "email": "<address>" }
```

**Response is UNWRAPPED** (auth endpoints carry the payload directly, not a `{status,data}` envelope). On HTTP `202`:

```json
{ "verification_id": "<id>", "expires_at": "<RFC3339>" }
```

This emails the user a **6-digit code**. The widget is already showing the code field, so just hold the `verification_id` and wait for the `code:` message.

- **`202`** — hold `verification_id`; write `${SUBSTRATE_STATE}/.pending-verification` with `verification_id`, `email`, and `expires_at` (one line) so a half-finished ceremony resumes on next session. Transient; never committed (absent from the hidden-surface `.gitignore` allowlist).
- **Network failure / timeout** — retry with exponential backoff (250 ms → 500 ms → 1 s → 2 s). On persistent failure, tell the user the verification service is unreachable and fall to anonymous-read mode (§1.1); offer to retry later.
- **Address rejected** — surface plainly: *"I couldn't send to that address — want to try another?"* and re-render the access widget.

On a `[Be Civic access] resend` message, re-run this step for the held email; a fresh `verification_id` + code are issued (replace the held one).

---

## Step 4. Receive the code

The user reads the 6-digit code from the email and enters it in the widget; you receive `[Be Civic access] code: <digits>`. That is the trigger for Step 5 — no link, no paste-back, no polling.

If a `code:` message arrives but you have no held `verification_id` (e.g. a stale session resumed from `.pending-verification` that has since expired), re-run Step 3 first, then ask the user — in chat — for the fresh code.

---

## Step 5. Verify the code — `POST /api/auth/verify`

Redeem the code via **`WebFetch`**. **No auth header** — the key is what this call mints.

```
POST https://becivic.be/api/auth/verify
Content-Type: application/json

{ "verification_id": "<held id>", "code": "<6-digit code>" }
```

**Response is UNWRAPPED.** On HTTP `200`:

```json
{ "user_id": "<id>", "harness_key": "<secret>", "tier": "pseudonymous" }
```

Branch on the **HTTP status code first**:

- **`200`** — capture `user_id`, `harness_key`, `tier`; delete `.pending-verification`; proceed to Step 6 (state activation).
- **`400` with `detail` "Incorrect code"** — wrong code. Tell the user plainly (*"That code didn't match — what's the 6-digit code from the email?"*) and re-call this step with the **same** `verification_id` and the new code. The server caps attempts at 5.
- **`400` with `detail` "Verification expired"** — the code timed out. Re-run Step 3 (fresh `verification_id` + code), then ask the user for the new code.
- **`429` `{ "error": "rate_limit_exceeded" }`** — too many wrong attempts; this verification is burned. Re-run Step 3 to send a fresh code, then ask for it.
- **Network failure** — retry with the Step 3 backoff; keep `.pending-verification` in place so the next session can resume.

**Never echo `harness_key` to chat.** From here it lives only in `.env` (Step 6).

---

## Step 6. State-shape activation

A confirmed verification with absent marker triggers the full two-surface write. The folder picker fires here if it has not already.

### 6.1. Pick the visible parent

Call `mcp__cowork__request_cowork_directory`. The user picks a **parent folder**; the visible surface is `<picked-parent>/BeCivic/` (this becomes `${SUBSTRATE_DATA}`).

If the user **cancels the picker**, do not silently abort. The hidden surface (`${SUBSTRATE_STATE}`) is already allocated by Cowork without a picker, so the identity is mintable — but without a visible folder there is nowhere user-facing to save progress. Say: *"I need a folder to save your project in. Want to try the picker again, or carry on in chat for now and set the folder up later?"* The latter degrades to advice-only: write the hidden-surface identity (6.2) so submissions work, skip the visible-surface writes (6.4), and tell the user their progress isn't being saved to disk yet.

### 6.2. Write the hidden-surface identity (`${SUBSTRATE_STATE}`)

In this order:

1. **`git init`** the hidden surface if it is not already a repo. **Write `${SUBSTRATE_STATE}/.gitignore` FIRST**, copied verbatim from `${SUBSTRATE_ROOT}/data/gitignore-hidden.txt`. The allowlist is what keeps `.env`, `sessions/`, and `.pending-verification` out of every commit — it must exist before any other file is written or the monitor's first `git add -A` could stage the key.
2. **`${SUBSTRATE_STATE}/.env`** — the harness key only: `BECIVIC_HARNESS_KEY=<harness_key>`. Nothing else in this file. It is structurally excluded from git by the allowlist. Never echo it.
3. **`${SUBSTRATE_STATE}/user-id`** — the raw `user_id` string, no wrapper.
4. **`${SUBSTRATE_STATE}/profile.json`** — copy the template from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/project-init/profile.json` **verbatim, unchanged**. Do **not** populate `last_updated_at` and do **not** pre-fill any routing fields here, even ones you could guess from the opener. The profile must stay at its template defaults (`last_updated_at: null`, every routing field `null` / `[]`) so the next chat can use "profile still at defaults" as the reliable signal that the about-you form has not run yet (the next chat's harness keys the about-you-form decision on exactly this). The about-you form in the working session is the **first** writer of routing fields and `last_updated_at`; leave that to it.
5. **`${SUBSTRATE_STATE}/preferences.json`** — a minimal preferences object (e.g. `{ "conversation_language": "<locale>" }`); start with the conversation language so the harness speaks it from turn one.
6. **`${SUBSTRATE_STATE}/procedures.json`** — the procedure registry, validated against `${SUBSTRATE_ROOT}/schemas/procedures.registry.schema.json`. Seed one entry for the procedure the user is about to start:
   ```json
   {
     "schema_version": 1,
     "procedures": [
       {
         "slug": "<procedure-slug>",
         "process_id": "<matched process id, or the slug if discovery-bound>",
         "process_version": "<version from the manifest entry, or '0' if unknown>",
         "status": "active",
         "started_at": "<RFC3339 UTC>",
         "updated_at": "<RFC3339 UTC>"
       }
     ]
   }
   ```
   If the gate matched no Process (`procedure_intent_vague`, zero manifest hits), use `intake` as the slug and `process_id`, and let `bc-discovery` rename it after routing.

`.pending-verification` is now redundant — delete it (verification is complete).

### 6.3. Write the hidden→visible pointer marker

Write **`${SUBSTRATE_STATE}/.be-civic/marker`** containing the absolute path to the visible surface (`${SUBSTRATE_DATA}`), one line. This is the pointer the auto-commit monitor and `preamble.py` read to locate the user-picked folder (`_resolve_substrate_data` in `preamble.py` reads exactly this file). Without it, the monitor watches the hidden surface only.

### 6.4. Write the visible surface (`${SUBSTRATE_DATA}`)

In this order:

1. Create `${SUBSTRATE_DATA}` (= `<picked-parent>/BeCivic/`).
2. **`git init`** it if not already a repo, and **write `${SUBSTRATE_DATA}/.gitignore` FIRST**, copied verbatim from `${SUBSTRATE_ROOT}/data/gitignore-visible.txt`.
3. **`${SUBSTRATE_DATA}/.be-civic/marker`** — the version-stamp marker, copied from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/project-init/.be-civic/marker`. (This is the visible-surface marker the gate walks the cwd to find; distinct from the hidden pointer in 6.3.)
4. **`${SUBSTRATE_DATA}/CLAUDE.md`** — the harness ambient-instruction template, copied from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/harness-CLAUDE.md`. Cowork's ancestor-walk auto-loads this when the user opens any procedure subfolder. **Do NOT write a CLAUDE.md inside per-procedure subfolders.** Then **append the carry-over block** described in 6.4a to the end of this file before you finish.
5. **`${SUBSTRATE_DATA}/MEMORY.md`** — the empty narrative store, copied from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/project-init/MEMORY.md`.

**Do not pre-create empty subdirectories.** No `documents/`, no `sessions/`, no per-procedure folder upfront — they are created lazily by the relevant skills when there is real content.

### 6.4a. Carry-over — pass the chosen procedure + language into the next chat

The next chat (the working session) loads only the project `CLAUDE.md` and the preamble's state lines. It has none of *this* conversation's context — it does not know which procedure the user came for or what language you've been speaking. You must hand both forward in concrete files so the next chat reads them and does **not** re-ask.

Two places, both required:

1. **Structured state (already written above):**
   - The conversation language is in `${SUBSTRATE_STATE}/preferences.json` as `conversation_language` (written in 6.2 step 5).
   - The chosen procedure is in `${SUBSTRATE_STATE}/procedures.json` as the single active entry's `slug` + `process_id` (written in 6.2 step 6).
   - Confirm both are present before handing off. These are the authoritative carry-over.

2. **A human-readable carry-over block appended to `${SUBSTRATE_DATA}/CLAUDE.md`.** After copying the template (6.4 step 4), append a short fenced block at the very end of the file so the carry-over is visible in the always-loaded ambient instructions, not only in hidden state:

   ```markdown
   ## Carry-over (written at setup — read on first load, do not re-ask)

   - Chosen procedure: <procedure title> (`<process_id>`, slug `<procedure-slug>`)
   - Conversation language: <language name> (`<locale>`)

   The working session greets the user about this procedure in this language on its
   first message, then captures the about-you form. It does not re-ask which procedure
   or which language.
   ```

   Fill `<procedure title>`, `<process_id>`, `<procedure-slug>`, `<language name>`, and `<locale>` from what you matched at the taste beat and the registry entry you just wrote. If the gate matched no Process (`intake` slug), write `Chosen procedure: to be routed (slug `intake`)` and the next chat will route it before the form.

The next chat's first job is to read this carry-over and the preferences/registry, greet the user about their procedure in their language, then surface the about-you form. If either value is missing when the next chat loads, it asks the user rather than guessing — so writing both, correctly, here is what keeps the next chat from defaulting to the wrong procedure or the wrong language.

### 6.5. Acknowledge with the path (JIT trust clause)

Confirm to the user, in conversation language:

> "You're set up — saved locally at `<absolute path to BeCivic/>`. Everything you tell me stays in this folder on your machine. The only thing that ever leaves is the anonymous notes you approve at the end of a session, and you see every one before it's sent."

This is the anonymity trust clause; it fires naturally at folder-mount time. Keep it to one beat.

---

## Step 7. Hand the user into their project — one clean context switch

This is the one moment the user changes chats, and it is the only one. **Do NOT walk the procedure in this conversation.** Cowork only loads a project's harness `CLAUDE.md` when a chat is opened *inside* that project folder — so the procedure work must run in a fresh chat opened in `${SUBSTRATE_DATA}`, not here. Staying in this chat is the bug this flow fixes: the harness gets written to disk but never loads, and the user ends up talking to a generic agent that has none of the harness rules.

So Chat 1 ends here. Hand the user a clickable link into their project, tell them exactly what they should see when the new chat opens, and then stop.

### 7.0. Only hand off if a visible project folder exists

The handoff below requires a real `${SUBSTRATE_DATA}` folder to open. If the user cancelled the folder picker (the advice-only branch in 6.1), there is **no** visible surface — `CLAUDE.md` was never written, so there is nothing for a fresh chat to auto-load, and a handoff link would point nowhere. In that case **do not run the handoff (7.1–7.3).** Instead, stay in this conversation in advice-only mode: the identity is minted and submissions work, but progress isn't saved to disk. Offer the user the choice again: *"I can keep helping you here, but nothing's being saved to a folder yet. Want to pick a folder now so I can save your project and pick it up cleanly next time?"* If they pick a folder, complete **the full visible-surface write — 6.3 (the hidden→visible pointer marker) AND 6.4 (the visible surface + carry-over)** — then run the handoff. The 6.3 pointer is not optional here: `preamble.py` resolves `SUBSTRATE_DATA` only from `${SUBSTRATE_STATE}/.be-civic/marker`, so without it the fresh chat sees `SUBSTRATE_DATA: absent` and treats the user as first contact even though the folder exists. If they decline, continue in advice-only — no context switch.

Only when `${SUBSTRATE_DATA}` exists AND its hidden pointer is written (the picker succeeded and 6.3 + 6.4 ran: the `.be-civic/marker` pointer, `CLAUDE.md`, and the carry-over are all in place) do you run the handoff below.

### 7.1. Tell the user what success looks like (before they switch)

The new chat will auto-load the harness and greet the user about their procedure. But that greeting only appears if the chat opens *inside* the project folder. If the user opens the wrong folder, nothing loads and there is no harness to catch the mistake — so you must tell them, **now, while you still have the floor**, what the greeting looks like and how to recover if it's missing.

Say this, in conversation language, filling `<procedure name>` and the absolute path to the **BeCivic project root** (`${SUBSTRATE_DATA}`, i.e. `<picked-parent>/BeCivic/`):

> "You're all set up. The last step is to open your project in a fresh chat — that's where I pick up your saved setup and we do the actual work.
>
> [Open your <procedure name> project →](<deeplink or path>)
>
> When the new chat opens you should see me greet you about your **<procedure name>** straight away. If you don't see that greeting, the chat isn't inside your project folder — close it and reopen it inside your `BeCivic` folder, and I'll be there."

The recovery sentence is mandatory, not optional. It is the only safety net if the auto-load misses, because a chat opened in the wrong folder has no harness to self-correct.

### 7.2. Make the link clickable

Render the open-project action as a **markdown link**, never a bare path or a code block. The link must point at the **BeCivic root** (`${SUBSTRATE_DATA}`), not a per-procedure subfolder — you did not create a `<procedure-slug>/` folder during setup (§6.4 leaves it for the relevant skill to create lazily), and Cowork's ancestor-walk loads the harness `CLAUDE.md` from the BeCivic root, so the root is the correct target. On Cowork, prefer a `claude://` deeplink that opens a new chat in `${SUBSTRATE_DATA}` if you can construct one; otherwise give the user the plain instruction "open a new chat inside the folder at `<absolute path to BeCivic/>`" as a fallback, still phrased so the path is easy to copy.

### 7.3. End this conversation

Once you've delivered 7.1 + 7.2, **stop.** Do not invoke `bc-path-traversal`, do not invoke `bc-discovery`, do not start the situation assessment, do not render the about-you form. Those all belong to the next chat, driven by the harness `CLAUDE.md` you just wrote. This skill's job is finished the moment the user has a clickable way into their project and knows what to look for.

**If `procedure_intent_vague` with zero manifest hits:** the carry-over (6.4a) records the `intake` slug; the next chat's harness routes the user via `bc-discovery` in `process` mode before the about-you form. You still hand off the same way — the routing happens after the switch, not here.

**Exit this skill cleanly. Do not loop.** Subsequent procedure work (the about-you form, path traversal, document handling, observation buffering, session close) runs in the next chat against the harness, not in this conversation and not in this skill.

---

## Returning-user mode (short-circuit)

`bc-onboarding` **does not handle returning users with a complete setup.** The gate (`be-civic`) detects the marker and routes to `bc-path-traversal` (continuing) or surfaces the inline framing (returning / multi_active) itself.

If you are invoked when a `.be-civic/marker` already exists **and the harness key is present** in `${SUBSTRATE_STATE}/.env` (check presence only — never read the value) **and the visible `${SUBSTRATE_DATA}/CLAUDE.md` exists**, this is a genuine, fully set-up returning user; refuse and route back:

> "You already have a Be Civic project at `<path>`. Open it in a fresh chat from inside the folder and I'll pick up where we left off — no need to set anything up again."

Do not re-run onboarding. Do not overwrite `profile.json`. Do not re-mint identity or re-write `.env`.

**Two carve-outs — a marker can exist over a half-written project.** A marker present does not always mean setup finished. Two crash windows leave a marker over an incomplete project, and in BOTH you ARE allowed to write the missing piece (the blanket "don't touch anything" refusal does not apply):

- **Key absent** (`HARNESS_KEY: absent`, or no `BECIVIC_HARNESS_KEY=` line in `.env`) → the keyless half-state. Run the **verification-only mode** below to mint + write the key.
- **Visible `${SUBSTRATE_DATA}/CLAUDE.md` absent** (setup crashed after the marker but before the harness file — recall 6.4 writes the marker in step 3, then `CLAUDE.md` in step 4) → the harness can never auto-load. Run the **harness-repair mode** below to write the missing harness file (and carry-over) from the state that already exists.

If both gaps are present, fix the key first (verification-only mode), then the harness file (harness-repair mode).

---

## Verification-only mode (keyless half-state recovery)

The harness routes here when a project folder exists (marker present) but verification never completed, so `${SUBSTRATE_STATE}/.env` has no harness key. The user installed and set up the folder, then abandoned before entering their code — or returned to a project that never got a key. **Do NOT silently 401 against the wire; do NOT re-run the whole flow.** Just finish the one missing piece: minting and writing the key.

1. **Confirm the gap.** A marker exists (so the project is real) but the key is absent (presence check on `${SUBSTRATE_STATE}/.env` — never read the value). If a `${SUBSTRATE_STATE}/.pending-verification` file is present, read its `email` / `verification_id` / `expires_at` to resume mid-ceremony.
2. **Re-open the access widget at the right step.** Render the shipped access widget (Step 2) so the user can complete verification. If `.pending-verification` is still valid, you can go straight to the code step (tell the user a code was already emailed; offer resend). If it is expired or absent, start fresh from the email step. Frame it plainly: *"Your project's here, but your access wasn't finished setting up — let's complete that now so I can pull your procedure."*
3. **Run Steps 3 → 5** (start-verification → receive code → verify) exactly as in first-contact. On `verify` success you get `{ user_id, harness_key, tier }`.
4. **Write the key (and only what's missing).** Write `harness_key` to `${SUBSTRATE_STATE}/.env` per Step 6.2 item 2 (ensure the hidden-surface `.gitignore` allowlist exists first, per 6.2 item 1, so the key is never staged). Write `user-id` if it is absent. **Do NOT overwrite an existing `profile.json`, `preferences.json`, `procedures.json`, the markers, or the visible surface** — those were already written when the folder was set up. Delete `.pending-verification` once `verify` succeeds.
5. **Return control to the harness.** The key is now present; the harness self-check (its §3.0) passes and it proceeds with the carry-over it already has. Do not run the about-you form here — that is the harness's job in the working session.

If the user declines verification again, fall to anonymous-read mode (§1.1): the project stays on disk, but wire-gated work (full Process bodies, submissions) stays unavailable until they verify.

---

## Harness-repair mode (missing CLAUDE.md recovery)

The gate routes here when a project marker exists but the visible `${SUBSTRATE_DATA}/CLAUDE.md` does not — setup wrote the marker (6.4 step 3) then crashed before writing the harness file (6.4 step 4). Without `CLAUDE.md` the substrate's ancestor-walk has nothing to load, so no harness comes up and no canary fires. **Do NOT re-run the whole flow and do NOT re-mint identity.** Write only the missing harness file and the carry-over, reusing the state already on disk.

1. **Confirm the gap.** A `.be-civic/marker` exists (the project is real) but `${SUBSTRATE_DATA}/CLAUDE.md` is missing. Resolve `${SUBSTRATE_DATA}` from the hidden pointer `${SUBSTRATE_STATE}/.be-civic/marker` (the same file `preamble.py` reads). If the key is also absent, do the verification-only mode first, then return here.
2. **Write the harness file.** Copy `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/harness-CLAUDE.md` to `${SUBSTRATE_DATA}/CLAUDE.md` (per 6.4 step 4). Do not write a CLAUDE.md inside any per-procedure subfolder.
3. **Re-write the carry-over block** (6.4a) at the end of the new `CLAUDE.md`, reconstructed from the existing hidden state: the chosen procedure from the active entry in `${SUBSTRATE_STATE}/procedures.json`, and the language from `${SUBSTRATE_STATE}/preferences.json`. If `procedures.json` has exactly one active entry, use it; if it has more than one, write the carry-over for whichever the user names when they next pick (or omit the single-procedure line and let the harness's `multi_active` framing choose). If `procedures.json` is empty too (a deeper crash), this is effectively a fresh setup — re-run from Step 6.2.
4. **Do not touch anything else.** Leave `profile.json`, `preferences.json`, `procedures.json`, `.env`, `user-id`, and both markers as they are. You are filling a single missing file, not rebuilding the project.
5. **Hand the user into the project.** The harness file now exists, so run the Step 7 handoff: tell the user the canary to expect, give them the clickable open-project link to `${SUBSTRATE_DATA}`, and end. On the next chat the ancestor-walk loads the now-present `CLAUDE.md` and the harness self-check + canary run normally.

---

## Imported-state branch (returning user, new machine)

A returning user may arrive with a `bc-import` bundle from another machine. When the gate flags an import bundle in scope, it routes here to the imported-state branch instead of first-contact:

1. **Validate the bundle** — confirm the visible/hidden split is preserved and the bundle's `state_version` is not newer than this plugin (if it is, tell the user to upgrade the receiving plugin first; do not activate).
2. **Activate both surfaces** — write the hidden side (including its `.env` key slot) into the current `${SUBSTRATE_STATE}`, and the visible side into a newly-picked parent as `${SUBSTRATE_DATA}`. Write/update both markers (hidden pointer + visible version-stamp) to cross-reference them.
3. **Frame as a returning user**, not a new one — no taste beat, no email gate, no re-mint. Hand off to `bc-path-traversal` (or the inline framing) as if the user were returning natively.

---

## Anonymous-read mode (recap)

If the user never verifies (declined at §1.1, closed the email widget at §2, or the verification service was unreachable), the session runs read-only on `corpus:read:public`:

- `WebFetch` reads of the manifest and its per-Process `outline`, **no Bearer** (Process bodies stay gated — anonymous `GET /api/processes/<id>` returns `401`).
- No submissions. No folder. No `${SUBSTRATE_STATE}` writes. No marker.
- The mode resets each session — the next session starts anonymous again until the user opts in.

Frame the limit as a choice the user can reverse any time, never as a failure.

---

## Meta-question handling

`bc-onboarding` **does not own meta questions.** The `be-civic` gate answers them in chat from `${SUBSTRATE_ROOT}/data/privacy-snippet.md` **verbatim**.

If the user asks a meta question mid-onboarding (between the taste beat and the email submit), pause the flow, quote `privacy-snippet.md` verbatim (load it from the file — **never paraphrase**), then offer:

> "Want me to carry on setting you up, or keep talking about the data side first?"

If they want to keep talking about data, hold position. If they decide not to proceed, fall to the anonymous-read fallback (§1.1).

---

## What this skill does NOT own

- The harness rules (Iron Law, situation assessment, observation handling, document handling, session close). Those live in `${SUBSTRATE_DATA}/CLAUDE.md` after this skill writes it.
- Procedure walking, document extraction, path traversal. Peer skills (`bc-path-traversal`, `bc-document-handler`) invoked by the harness.
- Returning sessions, multi-active pivots. The gate + harness handle those.
- Meta-question answering, off-topic redirect, no-intent tour. The `be-civic` gate handles those.
- The auto-commit monitor (`hooks/auto-commit-monitor.js`) and the recovery sweep (`preamble.py`). This skill writes the markers and `.gitignore` files they depend on, then gets out of the way.

This skill exists for one thing: take a user who said yes at the gate → explain the plan for their procedure → verify their email → mint their pseudonymous identity → write the two-surface state shape with the carry-over → hand the user cleanly into a fresh chat inside their project folder, where the harness takes over. It does not run the procedure, and it does not render the about-you form — those are the next chat's job.
