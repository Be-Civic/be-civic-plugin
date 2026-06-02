---
id: bc-onboarding
name: bc-onboarding
description: First-contact onboarding for Be Civic. Runs the verified flow — taste before any email ask, then an email→code access widget (start-verification emails a 6-digit code → verify with the code), then state-shape activation across the hidden and visible substrate surfaces — and hands off to bc-path-traversal. Falls back to anonymous read-only mode if the user declines verification. Owns first-contact only; returning and multi-active modes are owned by the harness.
version: 3.1.0
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

This skill owns **first-contact only**. It runs once per Be Civic substrate: show the user product taste, capture and verify their email, mint their pseudonymous identity, write the two-surface state shape, hand off to `bc-path-traversal`. Returning sessions (marker already exists) and mid-session pivots to a second procedure are handled by the harness `CLAUDE.md`, not here.

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

## Step 1. Taste first — product context before any email ask

The gate (`be-civic`) invoked you on confirmed procedure intent + absent marker. It passed you the classified intent shape (`procedure_intent_clear` or `procedure_intent_vague`), a candidate Process id if it matched one, the conversation language, and the opener text.

**Before you ask for anything, show the user what Be Civic does.** At this point the harness has only the anonymous-read tier (`corpus:read:public`) — no Bearer, no local state. You have two surfaces for the taste beat; pick whichever fits the opener, in the user's conversation language:

- **Branded framing via `mcp__visualize__show_widget`** — a short branded panel that says what Be Civic is (a verified library of Belgian procedures, run by the user's own agent, kept on the user's own machine) and what's about to happen. Use the brand palette documented in `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/onboarding.<locale>.html` (gold `#fae042`, red `#ed2939`, cream `#f5f4ee`, ink `#1a1a18`; remember Cowork's `all: unset` rule for bare form elements).
- **Chat walkthrough of a real Process** — if the gate matched a candidate Process, fetch its `public: true` body and walk the user through a slice of it so they see real, concrete content. This is the strongest taste: the user sees the actual procedure they came for.

To fetch a `public: true` Process body anonymously, use the **`WebFetch`** tool against the manifest then the process endpoint (no `Authorization` header — anonymous-read tier):

1. `GET https://becivic.be/api/manifest` → `{ status, data }`; the entity graph is in `.data`. Search the entries client-side by `title` / `summary` / `applies_to` against the user's intent.
2. `GET https://becivic.be/api/processes/<id>` → `{ status, data }`; the rendered body is in `.data.body` (MDX, inline slots resolved). Surface a readable slice — do not dump the whole thing.

Only `public: true` entities are visible without a Bearer. If nothing public matches, fall back to the branded-framing surface and describe what Be Civic covers in plain language.

Keep this beat short. The goal is one clear "oh, that's what this is" moment, then the email ask — not a full procedure walkthrough before the user has opted in.

### 1.1. Anonymous-read fallback (user declines verification)

If at any point the user declines to verify by email — "I don't want to give my email", "can I just look around?", "not yet" — **do not push.** Skip steps 2–6 entirely and operate read-only:

- Reads run against `corpus:read:public` with **no Bearer** (the `WebFetch` calls above, public entities only).
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
4. **`${SUBSTRATE_STATE}/profile.json`** — copy the template from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/project-init/profile.json`, then populate `last_updated_at` and any categorical routing fields you can derive conservatively from the opener (region, civic/residency status, languages — categorical only; never names, NN/NISS, addresses, document numbers). Leave the rest at their `null` / `[]` defaults for the situation-assessment beat to fill.
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
4. **`${SUBSTRATE_DATA}/CLAUDE.md`** — the harness ambient-instruction template, copied from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/harness-CLAUDE.md`. Cowork's ancestor-walk auto-loads this when the user opens any procedure subfolder. **Do NOT write a CLAUDE.md inside per-procedure subfolders.**
5. **`${SUBSTRATE_DATA}/MEMORY.md`** — the empty narrative store, copied from `${SUBSTRATE_ROOT}/skills/bc-onboarding/references/project-init/MEMORY.md`.

**Do not pre-create empty subdirectories.** No `documents/`, no `sessions/`, no per-procedure folder upfront — they are created lazily by the relevant skills when there is real content.

### 6.5. Acknowledge with the path (JIT trust clause)

Confirm to the user, in conversation language:

> "You're set up — saved locally at `<absolute path to BeCivic/>`. Everything you tell me stays in this folder on your machine. The only thing that ever leaves is the anonymous notes you approve at the end of a session, and you see every one before it's sent."

This is the anonymity trust clause; it fires naturally at folder-mount time. Keep it to one beat.

---

## Step 7. Hand off to `bc-path-traversal`

Once the two-surface state is written and the identity is live, hand control to `bc-path-traversal`. This is the clean, explicit handoff — onboarding does not walk the procedure itself.

- **Matched Process** (`procedure_intent_clear`, or `procedure_intent_vague` with a manifest hit): invoke `bc-path-traversal` with the matched `process_id`. It fetches the canonical via `GET /api/processes/<id>` (with the Bearer, now that the key is provisioned) and walks the required documents.
- **No matched Process** (`procedure_intent_vague`, zero manifest hits): invoke `bc-discovery` in `process` mode instead, to route the user to the right procedure before traversal.

Hand-off line (conversation language):

> "Setup's done. Let me walk you through what you'll need for the <procedure name>."

The folder is already mounted in this conversation and the harness `CLAUDE.md` is being picked up by Cowork's ancestor-walk, so proceed directly into the next skill in the same conversation. **Exit this skill cleanly. Do not loop.** Subsequent procedure work (path traversal, document handling, observation buffering, session close) runs against the harness, not this skill.

---

## Returning-user mode (short-circuit)

`bc-onboarding` **does not handle returning users.** The gate (`be-civic`) detects the marker and routes to `bc-path-traversal` (continuing) or surfaces the inline framing (returning / multi_active) itself.

If you are somehow invoked when a `.be-civic/marker` already exists (shouldn't happen — the gate checks first), refuse and route back:

> "You already have a Be Civic project at `<path>`. The harness picks up automatically — carry on in this conversation, or open the project folder."

Do not re-run onboarding. Do not overwrite `profile.json`. Do not re-mint identity or re-write `.env`.

---

## Imported-state branch (returning user, new machine)

A returning user may arrive with a `bc-import` bundle from another machine. When the gate flags an import bundle in scope, it routes here to the imported-state branch instead of first-contact:

1. **Validate the bundle** — confirm the visible/hidden split is preserved and the bundle's `state_version` is not newer than this plugin (if it is, tell the user to upgrade the receiving plugin first; do not activate).
2. **Activate both surfaces** — write the hidden side (including its `.env` key slot) into the current `${SUBSTRATE_STATE}`, and the visible side into a newly-picked parent as `${SUBSTRATE_DATA}`. Write/update both markers (hidden pointer + visible version-stamp) to cross-reference them.
3. **Frame as a returning user**, not a new one — no taste beat, no email gate, no re-mint. Hand off to `bc-path-traversal` (or the inline framing) as if the user were returning natively.

---

## Anonymous-read mode (recap)

If the user never verifies (declined at §1.1, closed the email widget at §2, or the verification service was unreachable), the session runs read-only on `corpus:read:public`:

- `WebFetch` reads of `public: true` Processes and the manifest, **no Bearer**.
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

This skill exists for one thing: take a user who said yes at the gate → show them what Be Civic does → verify their email → mint their pseudonymous identity → write the two-surface state shape → hand off cleanly to `bc-path-traversal`.
