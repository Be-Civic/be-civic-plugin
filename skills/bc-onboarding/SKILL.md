---
id: bc-onboarding
name: bc-onboarding
description: Onboarding for Be Civic. First-contact mode runs the verified flow — an email→code access widget (start-verification emails a 6-digit code → verify with the code), then state-shape activation inside the user-picked project folder (one folder, one git repo, with agent-managed state in a hidden .be-civic/state subdir) — and ends with a clean handoff into a fresh chat opened inside the project folder, where the working session begins. First-working-session mode (the next chat, after the harness loads and greets) fetches the carried-over canonical, renders the about-you form, and commits the profile sentinel. Falls back to anonymous read-only mode if the user declines verification. Returning and multi-active framings are owned by the harness.
version: 3.4.1
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

Be Civic is a tool for the user's agent, not an agent itself. The user already has an agent (you, running inside Cowork); Be Civic gives that agent a verified library of Belgian administrative procedures. This skill is the "get set up" beat: the user has already said yes, and your job is to get them set up quickly and cleanly.

This skill spans two moments in the onboarding lifecycle:

- **First-contact mode** — the "get set up" conversation (Chat 1), covered by Steps 1–7 below. It runs once per Be Civic project: capture and verify the user's email, pick the project folder, mint their pseudonymous identity, write the project state shape (one folder, one git repo), then **end this conversation by moving the user into one fresh chat opened inside their project folder** where the work begins.
- **First-working-session mode** — the next chat (Chat 2), after the harness loads and greets the user about their procedure. The harness invokes this skill (because the about-you form has not run yet) to render the about-you form, validate it, and commit the profile sentinel. Covered in its own section below.

Returning sessions (marker already exists) and mid-session pivots to a second procedure are framed by the harness `CLAUDE.md`, not here.

**First-contact (Chat 1) is setup only**: email, verification, and writing the project to disk. The procedure interview — the about-you form and the real walk-through — happens in the *next* chat. So during first-contact (Steps 1–7) do **not** ask the user about their situation, and do **not** render the about-you onboarding form: that is first-working-session mode's job, in Chat 2. Setting up the project, then handing the user cleanly into it, is the whole of first-contact.

### Substrate surfaces — one folder, one repo

Everything this skill writes lands inside the user-picked project folder. There is one git repo at the folder root; the agent-managed state lives in a hidden subdirectory of that same folder. Read the resolved paths from the preamble's session-state lines — never hardcode.

| Surface | Var | What it holds |
|---|---|---|
| Project folder (user-picked) | `${SUBSTRATE_DATA}` (= `<picked-parent>/BeCivic/`) | `CLAUDE.md`, `MEMORY.md`, the single `.gitignore`, `.be-civic/marker` (detection), `documents/`, `<procedure-slug>/` |
| Agent-managed state | `${SUBSTRATE_STATE}` (= `${SUBSTRATE_DATA}/.be-civic/state`) | `.env` (harness_key only — at `.be-civic/state/.env`), `user-id`, `profile.json`, `preferences.json`, `procedures.json`, `version.json`, `sessions/`, `.pending-verification` (transient) |
| Read-only install | `${SUBSTRATE_ROOT}` (resolve via the discovery step below — `$CLAUDE_PLUGIN_ROOT` is unset in the Cowork VM shell) | the shipped plugin (templates, schemas, data, scripts) |

`${SUBSTRATE_STATE}` is a pure child of `${SUBSTRATE_DATA}` — the hidden `.be-civic/state/` folder inside the user's project. The harness key file lives at `${SUBSTRATE_STATE}/.env` = `${SUBSTRATE_DATA}/.be-civic/state/.env`.

**Identity rule.** The harness key in `${SUBSTRATE_STATE}/.env` is NEVER committed, echoed to chat, or logged. It is excluded from git structurally — the project's single `.gitignore` allowlist does not list `.be-civic/state/.env`, and a belt-and-braces `.env` deny line covers it too. Do not print it back to the user, ever.

### Resolve the install root — do this before any plugin-asset read

This skill reads shipped assets (the access widget, `setup_project.py`, `gitignore.txt`, `harness-CLAUDE.md`) from `${SUBSTRATE_ROOT}`. **You cannot assume `${SUBSTRATE_ROOT}`/`$CLAUDE_PLUGIN_ROOT` expands in bash** — on the CLI it is set, but **in the Cowork VM shell it is unset**, so a literal `${SUBSTRATE_ROOT}/…` collapses to `/…` and fails with "No such file." Resolve it **once**, at the start of setup, and reuse the value (the plugin is mounted in the VM — it *is* reachable via bash once you have the path; the `/var/folders/…` path you may see as a skill "Base directory" is a host path the VM bash can't see):

```bash
# Locate the Be Civic plugin install by its manifest (the Cowork mount dir is
# plugin_<hash>/, which does NOT contain "be-civic" — match the manifest, not the path).
BC_ROOT="$CLAUDE_PLUGIN_ROOT"
if [ ! -f "$BC_ROOT/scripts/setup_project.py" ]; then
  m="$(find /sessions "$HOME/.claude/plugins" /root/.claude/plugins -maxdepth 8 \
    -path '*/.claude-plugin/plugin.json' -exec grep -l '"name": "be-civic"' {} + 2>/dev/null | head -1)"
  BC_ROOT="$(dirname "$(dirname "$m")")"
fi
echo "$BC_ROOT"   # sanity: a non-empty path ending in the plugin dir
```

Use `$BC_ROOT` wherever the steps below write `${SUBSTRATE_ROOT}` in a bash command. (If `$BC_ROOT` comes back empty, the install couldn't be located — tell the user setup can't proceed and retry; do **not** silently reconstruct shipped files from memory.)

---

## Step 1. Match the procedure, then go to the email ask

The gate (`be-civic`) invoked you on confirmed procedure intent + absent marker. It passed you the classified intent shape (`procedure_intent_clear` or `procedure_intent_vague`), a candidate Process id if it matched one, the conversation language, and the opener text.

The user has already said yes — they came to be set up. **Do not introduce or pitch the plan here.** The introduction (what the procedure involves, the documents, the outcome) is the cold agent's job at `becivic.be/agents`, before install; an installed user has already had it, and re-introducing it stalls the set-up they asked for. Your first beat is a short, honest framing and the email ask — nothing more.

First, **silently identify which procedure the user came for** so the rest of setup can seed it correctly. This is internal bookkeeping, not something you narrate to the user. At this point the harness has only the anonymous-read tier (`corpus:read:public`) — no Bearer, no local state. Read the **public manifest** via the **`WebFetch`** tool (no `Authorization` header — anonymous-read tier):

1. `GET ${BASE}/api/manifest` → `{ version, generated_at, entries }`. The entity graph is in `.entries` (top-level — there is no `.data` wrapper). Search the entries client-side by `title` / `summary` / `applies_to` against the user's intent to find the Process the gate matched (or the closest match).
2. Hold the matched entry's `title`, its Process `id`, and its `version`. These feed the procedures registry seed (§6.2) — the active entry in `procedures.json`, which the preamble reads next chat as `CARRYOVER_PROCEDURE`. If nothing in the manifest matches the user's intent (or the gate classified `procedure_intent_vague` with zero hits), hold the `intake` slug instead — `bc-discovery` resolves it in the next chat.

**Do NOT fetch a Process body here** — no Process is public today; an anonymous `GET ${BASE}/api/processes/<id>` without a Bearer returns `401`. The match runs off the manifest only. **Do not present the procedure's stages, documents, fees, deadlines, or per-step detail** — none of that is introduced in the plugin; it belongs to the working session after verification.

Then go straight to the email ask (Step 2). Keep your framing to one short beat — who you are and what's about to happen — for example, in the conversation language: *"Let's get you set up. First I'll take your email to get you authenticated — that's what lets me open Be Civic's verified guides and save your progress. Then we're into it."* Do not render a branded introduction panel.

### 1.1. Anonymous-read fallback (user declines verification)

If at any point the user declines to verify by email — "I don't want to give my email", "can I just look around?", "not yet" — **do not push.** Skip steps 2–6 entirely and operate read-only:

- Reads run against `corpus:read:public` with **no Bearer** — the manifest (which includes a short outline per procedure) via `WebFetch`. Process bodies stay gated (anonymous `GET /api/processes/<id>` returns `401`).
- **No submissions are possible** — Issues, Validations, Feedback, Ratings all require the pseudonymous tier. No folder is mounted; no `${SUBSTRATE_STATE}` state is written; no marker.
- Frame the limit kindly, in conversation language: *"No problem. Without your email I can't open Be Civic's verified guides, but I'll do my best to help from what I know in the meantime. If you change your mind, just say so."*
- The mode persists for the session. The user can opt in later by re-stating intent — pick back up at step 2.

---

## Step 2. Email + code — the access widget

After the Step 1 framing (or on a direct "yes, set me up"), render the **shipped access widget** via `mcp__visualize__show_widget`, passing the contents of `$BC_ROOT/skills/bc-onboarding/references/onboarding-access.<locale>.html` as `widget_code` (where `$BC_ROOT` is the install root resolved above). (EN ships today; for a locale not yet authored, fall back to the EN file.) Read the file via `bash` `cat "$BC_ROOT/skills/…"` — it is a plugin-install asset; the host `Read` tool can't see it, and `${SUBSTRATE_ROOT}` is not a live shell variable, so use the resolved `$BC_ROOT`.

**This is shipped, fully-branded HTML — do NOT call `mcp__visualize__read_me` first.** `read_me` returns widget-*authoring* design guidance (palette, icons, spacing) for building a widget from scratch; this widget is already built and self-contained. Pass its contents verbatim as `widget_code` and render. Calling `read_me` here is wasted work (one run loaded the wrong module and burned ~7k tokens for output that is ignored). The same rule holds for every shipped Be Civic widget (this access widget and the Chat-2 about-you form).

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

On the `[Be Civic access] email: <addr>` message, validate the address shape locally (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`).

**Envelope-mismatch check (do this once, before verifying).** If you can see the user's account email — e.g. the Cowork session envelope exposes one — and it differs from the `<addr>` they typed, ask once, in conversation language, before calling the endpoint: *"You're signed in as `<envelope-email>` but you typed `<typed-email>`. The code goes to whichever address you verify, and that becomes your account — which do you want to use?"* This is cheap and prevents a whole class of typos that mint an identity against an inbox the user can't actually read (so they can never receive the code, or recover the key later). If you have no envelope email to compare against, skip this and proceed.

Then call the start endpoint via the bundled **`wire.py`** (a POST — `WebFetch` is GET-only and cannot carry a request body, so writes go through `wire.py` over `bash`). **No auth header is needed** — the user has no key yet, and `wire.py` sends none when `${SUBSTRATE_STATE}/.env` has no key (this is the anonymous-tier bootstrap call). `$BC_ROOT` is the install root resolved in the discovery step above:

```bash
python3 "$BC_ROOT/scripts/wire.py" POST /api/auth/start-verification \
  --json '{"email":"<address>"}'
```

`wire.py` prints `http_status:` then `result: ok|error` plus the parsed `body:`, and exits 0 on a 2xx. **Response is UNWRAPPED** (auth endpoints carry the payload directly, not a `{status,data}` envelope). On HTTP `202` the body is:

```json
{ "verification_id": "<id>", "expires_at": "<RFC3339>" }
```

This emails the user a **6-digit code**. The widget is already showing the code field, so just hold the `verification_id` and wait for the `code:` message.

- **`202`** — hold `verification_id`. **Do not write `.pending-verification` yet** — no durable write happens before the folder is picked (Step 6.1), and `${SUBSTRATE_STATE}` does not exist until then. Hold `verification_id`, `email`, and `expires_at` in working memory. Once the folder is picked and state exists, write `${SUBSTRATE_STATE}/.pending-verification` (one line) so a half-finished ceremony resumes on next session; it is transient and never committed (denied by the single `.gitignore` allowlist). (In **verification-only recovery mode** the folder already exists, so write it immediately.)
- **Network failure / timeout** (`wire.py` exits with `result: network`) — `wire.py` already retried once internally; on a second failure re-run the same command at most once more, then tell the user the verification service is unreachable and fall to anonymous-read mode (§1.1); offer to retry later. If `wire.py` instead prints `result: blocked` (exit 4 — `blocked-by-allowlist`), `becivic.be` is not reachable in this sandbox; surface that the verified library can't be reached right now and fall to anonymous-read mode.
- **Address rejected** — surface plainly: *"I couldn't send a code to that address — want to try another?"* and re-render the access widget.

On a `[Be Civic access] resend` message, re-run this step for the held email; a fresh `verification_id` + code are issued (replace the held one).

---

## Step 4. Receive the code

The user reads the 6-digit code from the email and enters it in the widget; you receive `[Be Civic access] code: <digits>`. **Act on it in the same turn — your response to the `code:` message IS the Step 5 verify call.** Do not emit an empty acknowledgement turn ("Got it, checking that now…") and then wait: that burns a round-trip and leaves the user watching a spinner. The `code:` message is itself the trigger — no link, no paste-back, no polling, no holding turn.

If a `code:` message arrives but you have no held `verification_id` (e.g. a stale session resumed from `.pending-verification` that has since expired), re-run Step 3 first, then ask the user — in chat — for the fresh code.

---

## Step 5. Verify the code — `POST /api/auth/verify`

Redeem the code via the bundled **`wire.py`** (a POST — not a `WebFetch`, which is GET-only). **No auth header** — the key is what this call mints, and `wire.py` sends none until `.env` has one. Pipe the body on **stdin** so the code is not exposed in the process table / shell history:

```bash
printf '%s' '{"verification_id":"<held id>","code":"<6-digit code>"}' \
  | python3 "$BC_ROOT/scripts/wire.py" POST /api/auth/verify --stdin
```

**Response is UNWRAPPED.** Branch on the `http_status:` line `wire.py` prints. On HTTP `200` the body is:

```json
{ "user_id": "<id>", "harness_key": "<secret>", "tier": "pseudonymous" }
```

Branch on the **HTTP status code first**:

- **`200`** — capture `user_id`, `harness_key`, `tier`; delete `.pending-verification`; proceed to Step 6 (state activation).
- **`400` with `detail` "Incorrect code"** — wrong code. Tell the user plainly (*"That code didn't match — what's the 6-digit code from the email?"*) and re-call this step with the **same** `verification_id` and the new code. The server caps attempts at 5.
- **`400` with `detail` "Verification expired"** — the code timed out. Re-run Step 3 (fresh `verification_id` + code), then ask the user for the new code.
- **`429` `{ "error": "rate_limit_exceeded" }`** — too many wrong attempts; this verification is burned. Re-run Step 3 to send a fresh code, then ask for it.
- **Network failure** (`wire.py` `result: network`, after its internal retry) — re-run the verify command at most once more; keep `.pending-verification` in place so the next session can resume.

**Never echo `harness_key` to chat.** From here it lives only in `.env` (Step 6).

---

## Step 6. State-shape activation

A confirmed verification with absent marker triggers the full project write. **The folder picker fires FIRST — strictly before any durable write.** No key, no `.env`, no identity, no profile, no marker, no file of any kind lands on disk until the user has picked the folder and `${SUBSTRATE_DATA}` exists. Pick the folder (6.1) → run the `setup_project.py` call (6.2), which inits the one repo and writes the single `.gitignore` first, then the state and the rest of the folder (per the Step 6.2 reference).

### 6.1. Pick the project folder (before any durable write)

Call `mcp__cowork__request_cowork_directory`. The user picks a **parent folder**; the project folder is `<picked-parent>/BeCivic/` (this becomes `${SUBSTRATE_DATA}`).

If the user **cancels the picker**, do not write anything. There is no separate surface that exists without a picked folder — the whole project (key included) lives inside `${SUBSTRATE_DATA}`, so with no folder there is nowhere durable to write. Say: *"I need a folder to save your progress in. Want to try the picker again, or carry on here for now and set it up later?"* The latter degrades to **advice-only with ZERO durable writes** — no key, no identity, no files at all. The minted `harness_key` from Step 5 is held in working memory only this session; nothing is written. Tell the user nothing is being saved to disk yet, and that picking a folder later will save everything.

### 6.2. Write the whole project in one call — `setup_project.py`

The entire project write — the one git repo, the single `.gitignore`, all of `.be-civic/state/`, the marker, `CLAUDE.md` (the canonical harness, written verbatim — no carry-over block), `MEMORY.md`, and the first commit — is performed by **one deterministic script call**, not a sequence of hand-written files. Writing it by hand previously hardlinked the read-only `CLAUDE.md` template and risked transcription drift; the script writes fresh bytes and is the single source of truth.

Run it once, **piping the harness key on stdin** — never on the command line (the process table and shell history would expose it):

```bash
printf '%s' "<harness_key>" | python3 "$BC_ROOT/scripts/setup_project.py" \
  --data-root      "<picked-parent>" \
  --substrate-root "$BC_ROOT" \
  --user-id        "<user_id>" \
  --locale         "<locale>" \
  --language-name  "<language display name, e.g. French>" \
  --process-id     "<matched process id, or 'intake'>" \
  --process-slug   "<procedure slug, or 'intake'>" \
  --process-title  "<procedure title, or 'to be routed'>" \
  --process-version "<version from the manifest entry, or '0'>" \
  --plugin-version "<this plugin's version>" \
  --key-stdin
```

`<picked-parent>` is the folder the user picked in 6.1; the script creates `<picked-parent>/BeCivic/` as `${SUBSTRATE_DATA}`. (`$BC_ROOT` is the resolved plugin-install path from the discovery step — pass it through; the script reads its own templates from there. Run this via `bash`; the install dir is reachable from bash at the resolved path, not via the host `Read` tool.)

**Nested-repo guard.** If the script exits non-zero with `SETUP_ERROR: nested_repo_needs_confirmation`, the picked parent sits inside another git project and nothing was written. Warn the user plainly: *"The folder you picked sits inside another project folder that has git enabled. I'd normally give your Be Civic files their own space so your progress is saved cleanly. Want me to set it up here anyway, or pick a different folder?"* On confirmation, re-run the **same** command with `--allow-nested`; if they repick, re-run with the new `--data-root`.

**Verify before handing off.** Read the script's `KEY: VALUE` stdout. Proceed to §6.5 only when you see `SETUP_RESULT: ok` **and** a real `COMMIT_SHA`. On `partial` / `failed`, surface the `SETUP_ERROR` / `OPERATOR_ALERT` line and do **not** hand off — re-run, or fall back to the manual write in the reference below. You do **not** need to Read any of the written files back: the output lines (`ENV_WRITTEN`, `PROCEDURES_WRITTEN`, `CLAUDE_MD_WRITTEN`, `COMMIT_SHA`, …) report each step. The script never echoes the key (`HARNESS_KEY: present`, value-only).

The script also deletes the now-redundant `.pending-verification` and runs the `.env` git-safety guard (refuses to commit if `.env` would be tracked) — the same guard `preamble.py` uses.

#### What `setup_project.py` writes (reference — the script is authoritative)

The script reproduces the full project write below exactly. This is the ground-truth shape, kept for review and for the manual fallback; you do not perform these steps by hand on the happy path.

- **`.gitignore` first** (verbatim from `${SUBSTRATE_ROOT}/data/gitignore.txt`) — the merged allowlist, written before `git init` so the key is never staged. Then `git init`.
- **`.be-civic/state/`** (in order): **`.env`** = `BECIVIC_HARNESS_KEY=<harness_key>` and nothing else (gitignored; never echoed); **`user-id`** = the raw id; **`profile.json`** = the template **verbatim** (`last_updated_at` stays `null`, every routing field default — this "profile still at defaults" state is the signal the next chat keys the about-you form on; do not pre-fill); **`preferences.json`** = `{ "conversation_language": "<locale>" }`; **`procedures.json`** = the seeded registry:
  ```json
  {
    "schema_version": 1,
    "procedures": [
      { "slug": "<procedure-slug>", "process_id": "<matched id, or slug if discovery-bound>",
        "process_title": "<human title — OPTIONAL, omitted when no real title>",
        "process_version": "<version, or '0'>", "status": "active",
        "started_at": "<RFC3339 UTC>", "updated_at": "<RFC3339 UTC>" }
    ]
  }
  ```
  (`process_title` comes from the matched manifest entry and is what lets the next chat's load canary name the real title; it is OPTIONAL — when `--process-title` is empty the field is omitted and readers fall back to the slug. If the gate matched no Process — `procedure_intent_vague`, zero hits — pass `intake` for id/slug, omit the title; `bc-discovery` renames it after routing.)
- **`.be-civic/marker`** (template with `user_id` / `plugin_version` / `created_at` filled) — detection-only.
- **`CLAUDE.md`** = the harness template (`harness-CLAUDE.md`) written **byte-for-byte, with NO `## Carry-over` block appended**. The carry-over (chosen procedure + conversation language) is NOT prose in CLAUDE.md — it lives entirely in the state files above: `procedures.json` (the active entry's `slug` / `process_id`) and `preferences.json` (`conversation_language`). The preamble reads those and surfaces them as `CARRYOVER_PROCEDURE` / `CARRYOVER_LANG`, and emits the matched `SESSION_OPENING_INSTRUCTION` for the next chat's load canary. Appending a prose block was pure redundancy AND mutated the always-on harness (breaking the byte-identical-to-canonical fidelity the JIT instruction-surface doctrine depends on), so it is gone. (`--process-title` is written into the `procedures.json` entry as the optional `process_title` field, so the next chat's load canary names the real Process title rather than the kebab-case slug; the preamble surfaces it as `CARRYOVER_PROCEDURE: <slug> | <title>`. `--language-name` is accepted but unused — the conversation language is written from `--locale` into `preferences.json`.)
- **`MEMORY.md`** (verbatim template). No empty subdirectories (`documents/`, `sessions/`, per-procedure folders) are pre-created — they are made lazily.

### 6.5. Acknowledge with the path (JIT trust clause)

Confirm to the user, in conversation language:

> "You're set up — saved locally at `<absolute path to BeCivic/>`. Everything you tell me stays in this folder on your machine, and nothing that identifies you is ever sent to Be Civic. I use details like your region and commune to find the right guidance for you — that stays here too. At the end of each session I'll propose any anonymous feedback worth sending back (say, a fee that changed); it includes your region and commune so it's useful to others in the same place, but never your name, documents, or ID numbers — and nothing goes without your say-so. During the alpha, Be Civic also gets anonymous usage stats — which procedures get used, where I get stuck — never anything you typed."

This is the anonymity trust clause; it fires naturally at folder-mount time. Keep it to one beat.

---

## Step 7. Hand the user into their project — one clean context switch

This is the one moment the user changes chats, and it is the only one. **Do NOT walk the procedure in this conversation.** Cowork only loads a project's harness `CLAUDE.md` when a chat is opened *inside* that project folder — so the procedure work must run in a fresh chat opened in `${SUBSTRATE_DATA}`, not here. Staying in this chat is the bug this flow fixes: the harness gets written to disk but never loads, and the user ends up talking to a generic agent that has none of the harness rules.

So Chat 1 ends here. Hand the user a clickable link into their project, tell them exactly what they should see when the new chat opens, and then stop.

### 7.0. Only hand off if a project folder exists

The handoff below requires a real `${SUBSTRATE_DATA}` folder to open. If the user cancelled the folder picker (the advice-only branch in 6.1), **nothing was written to disk** — no folder, no `CLAUDE.md`, no state — so there is nothing for a fresh chat to auto-load, and a handoff link would point nowhere. In that case **do not run the handoff (7.1–7.3).** Instead, stay in this conversation in advice-only mode: nothing is saved to disk this session (the minted key was held in working memory only). Offer the user the choice again: *"I can keep helping you here, but nothing's being saved yet. Want to pick a folder now so I can save your progress and pick it up cleanly next time?"* If they pick a folder, complete **the full project write — the `setup_project.py` call in 6.2 (init repo + `.gitignore`, then state and the rest of the folder, per the Step 6.2 reference)** — then run the handoff. If they decline, continue in advice-only — no context switch.

Only when `${SUBSTRATE_DATA}` exists (the picker succeeded and the 6.2 project write ran: the `.gitignore`, state, `.be-civic/marker`, and `CLAUDE.md` are all in place, and the carry-over is captured in `procedures.json` + `preferences.json`) do you run the handoff below.

### 7.1. Tell the user what success looks like (before they switch)

The new chat will auto-load the harness and greet the user about their procedure. But that greeting only appears if the chat opens *inside* the project folder. If the user opens the wrong folder, nothing loads and there is no harness to catch the mistake — so you must tell them, **now, while you still have the floor**, what the greeting looks like and how to recover if it's missing.

Say this, in conversation language, filling `<procedure name>` and the absolute path to the **BeCivic project root** (`${SUBSTRATE_DATA}`, i.e. `<picked-parent>/BeCivic/`):

> "You're all set up. The last step is to open your project in a fresh chat — that's where I pick up your saved setup and we do the actual work.
>
> [Open your <procedure name> project →](<deeplink or path>)
>
> When the new chat opens you should see me name your **<procedure name>** straight away. If you don't, the chat isn't inside your project folder — close it and reopen it inside your `BeCivic` folder, and I'll be there."

The recovery sentence is mandatory, not optional. It is the only safety net if the auto-load misses, because a chat opened in the wrong folder has no harness to self-correct.

### 7.2. Make the link clickable

Render the open-project action as a **markdown link**, never a bare path or a code block. The link must point at the **BeCivic root** (`${SUBSTRATE_DATA}`), not a per-procedure subfolder — you did not create a `<procedure-slug>/` folder during setup (the Step 6.2 reference leaves it for the relevant skill to create lazily), and Cowork's ancestor-walk loads the harness `CLAUDE.md` from the BeCivic root, so the root is the correct target.

On Cowork, prefer a `claude://` deeplink that opens a new chat in `${SUBSTRATE_DATA}` if you can construct one (try the `claude://cowork/new?folder=<url-encoded-absolute-path>` form). **If no deeplink form works, still render a clickable link, not prose** — link the absolute folder path itself (e.g. `[Open your BeCivic folder](file://<absolute path to BeCivic/>)`) so the user has one thing to click, with the copy-paste path alongside as backup. The verdict's "handoff fell back to prose" failure mode is exactly what to avoid: never hand the user a bare path in a sentence when a link will do.

### 7.3. End this conversation

Once you've delivered 7.1 + 7.2, **stop.** Do not invoke `bc-path-traversal`, do not invoke `bc-discovery`, do not start the situation assessment, do not render the about-you form. Those all belong to the next chat, driven by the harness `CLAUDE.md` you just wrote. This skill's job is finished the moment the user has a clickable way into their project and knows what to look for.

**If `procedure_intent_vague` with zero manifest hits:** the seeded `procedures.json` records the `intake` slug (surfaced next chat as `CARRYOVER_PROCEDURE: intake`); the next chat's harness routes the user via `bc-discovery` in `process` mode before the about-you form. You still hand off the same way — the routing happens after the switch, not here.

**Exit this skill cleanly. Do not loop.** Subsequent procedure work (path traversal, document handling, observation buffering, session close) runs in the next chat against the harness. The about-you form runs in that next chat too — in **first-working-session mode** below, invoked by the harness after its load-canary greeting.

---

## First-working-session mode (the about-you form)

This is the **next chat**, opened inside the project folder, after first-contact set everything up. The harness loads, fires its load canary (greets the user about the carried-over procedure in their language), and then — because `PROFILE_CAPTURED: no` (the about-you form has not run yet) — invokes this skill in **first-working-session mode**. This is the one disposition where the project folder exists *and* the profile is still the untouched template; it fires **once per project**, after the greeting, before the procedure walk.

You are NOT setting up the project here (that already happened). You are not re-minting identity, not picking a folder, not verifying email. You run the about-you form, validate it, commit the profile sentinel, and hand back to the harness for the situation assessment + walk (harness §3.3).

Resolve the install root into `$BC_ROOT` first (the discovery step under "Resolve the install root", above) — `${SUBSTRATE_ROOT}` does not expand in the Cowork VM shell. Then:

1. **Fetch the canonical first.** Fetch the carried-over procedure's body via `GET ${BASE}/api/processes/<id>` over `WebFetch` (Bearer from `${SUBSTRATE_STATE}/.env`; base `${BASE}` = the preamble-emitted `BECIVIC_BASE`, default `https://becivic.be`, body at `.data.body`). You need its frontmatter `inputs:` **now** — they decide the form's Section 2 questions and the required-field validation in step 3. The procedure id is the active entry in `${SUBSTRATE_STATE}/procedures.json` (the preamble also surfaces it as `CARRYOVER_PROCEDURE`). If it carried as `intake` (a discovery-bound placeholder), route via `bc-discovery` `process` mode first to resolve a real Process, then come back. Library unreachable → tell the user and retry; do not render the form without the `inputs:`.

2. **Introduce, then render the shipped form.** Tell the user the form is coming and why (a few quick questions about their situation so you pull the right guidance), then render `$BC_ROOT/skills/bc-onboarding/references/onboarding.<locale>.html` (carry-over language from `CARRYOVER_LANG` / `preferences.json`; fall back to `onboarding.en.html` for a locale not yet authored) via `mcp__visualize__show_widget`, passing the whole file as `widget_code`. Read it via `bash` `cat "$BC_ROOT/skills/…"` — it is a plugin-install asset the host `Read` tool can't see. **This is shipped, fully-branded, self-contained HTML — do NOT call `mcp__visualize__read_me` first** (it returns widget-*authoring* guidance for building a form from scratch; this one is already built — calling `read_me` here burns tokens for ignored output). The form's field count, pre-population (uncomment Section 2 from the procedure's `inputs`), commune/NIS5 datalist capture, locale selection, and submit format are all documented in the HTML's own runtime-insertion block — follow it. The form returns one `Be Civic onboarding — <field>: <value> · …` chat message.

3. **Validate, then commit the sentinel.** Map the submitted fields onto `${SUBSTRATE_STATE}/profile.json` (**categorical fields only** — never names, NN/NISS, addresses, document numbers, exact dates of birth), normalise each to its `${SUBSTRATE_ROOT}/schemas/profile.schema.json` enum, and validate. **Set `last_updated_at` only once the profile validates AND the core routing fields are present** (≥ `region`, `civic_status`, `residency_status`, plus the procedure's declared `inputs`). Missing or un-normalising fields → ask for just those in chat (AskUserQuestion), and set `last_updated_at` only when they are filled. **Writing `last_updated_at` is the sentinel that tells future sessions the form is done — NEVER set it on a partial profile** (the form would be skipped forever with gaps; this is a privacy- and routing-critical trip-wire, restated as a safety invariant in the harness §3.2). If the user picks a language differing from the carry-over, mirror it to `${SUBSTRATE_STATE}/preferences.json` (and the profile) so later sessions don't revert. Narrative context (preferred name, soft history, family/work context) → `${SUBSTRATE_DATA}/MEMORY.md`, never the routing stores.

4. **Hand back to the harness.** The canonical is already in hand and the profile is captured → return control for the situation assessment (harness §3.3) and the procedure walk. Do not start the walk inside this skill; the harness owns it.

---

## Returning-user mode (short-circuit)

`bc-onboarding` **does not handle returning users with a complete setup.** The gate (`be-civic`) detects the marker and routes to `bc-path-traversal` (continuing) or surfaces the inline framing (returning / multi_active) itself.

If you are invoked when a `.be-civic/marker` already exists **and the harness key is present** in `${SUBSTRATE_STATE}/.env` (check presence only — never read the value) **and `${SUBSTRATE_DATA}/CLAUDE.md` exists**, this is a genuine, fully set-up returning user; refuse and route back:

> "You already have a Be Civic project at `<path>`. Open it in a fresh chat from inside the folder and I'll pick up where we left off — no need to set anything up again."

Do not re-run onboarding. Do not overwrite `profile.json`. Do not re-mint identity or re-write `.env`.

**Two carve-outs — a marker can exist over a half-written project.** A marker present does not always mean setup finished. Two crash windows leave a marker over an incomplete project, and in BOTH you ARE allowed to write the missing piece (the blanket "don't touch anything" refusal does not apply):

- **Key absent** (`HARNESS_KEY: absent`, or no `BECIVIC_HARNESS_KEY=` line in `.env`) → the keyless half-state. Run the **verification-only mode** below to mint + write the key.
- **`${SUBSTRATE_DATA}/CLAUDE.md` absent** (setup crashed after the marker but before the harness file — recall the marker is written before `CLAUDE.md`, per the Step 6.2 reference write order) → the harness can never auto-load. Run the **harness-repair mode** below to write the missing harness file (verbatim canonical) from the state that already exists.

If both gaps are present, fix the key first (verification-only mode), then the harness file (harness-repair mode).

---

## Verification-only mode (keyless half-state recovery)

The harness routes here when a project folder exists (marker present) but verification never completed, so `${SUBSTRATE_STATE}/.env` has no harness key. The user installed and set up the folder, then abandoned before entering their code — or returned to a project that never got a key. **Do NOT silently 401 against the wire; do NOT re-run the whole flow.** Just finish the one missing piece: minting and writing the key.

1. **Confirm the gap.** A marker exists (so the project is real) but the key is absent (presence check on `${SUBSTRATE_STATE}/.env` — never read the value). If a `${SUBSTRATE_STATE}/.pending-verification` file is present, read its `email` / `verification_id` / `expires_at` to resume mid-ceremony.
2. **Re-open the access widget at the right step.** Render the shipped access widget (Step 2) so the user can complete verification. If `.pending-verification` is still valid, you can go straight to the code step (tell the user a code was already emailed; offer resend). If it is expired or absent, start fresh from the email step. Frame it plainly: *"Your project's here, but your access wasn't finished setting up. Let's finish that now so I can open your guide."*
3. **Run Steps 3 → 5** (start-verification → receive code → verify) exactly as in first-contact. On `verify` success you get `{ user_id, harness_key, tier }`.
4. **Write the key (and only what's missing) — key on stdin, never on a command line.** Write `harness_key` to `${SUBSTRATE_STATE}/.env` (`BECIVIC_HARNESS_KEY=<harness_key>` and nothing else, per the Step 6.2 reference) by **piping the key on stdin** to the process that writes the file — the same discipline as Step 6.2, and for the same reason (an argv-interpolated key is exposed in the process table and shell history). Do **not** improvise a write that interpolates the key value into the command text of an external process — no `printf '…=%s' "<key>" > .env`-style write, no `echo`/`tee` carrying the key. Use exactly this shape, substituting `<resolved-substrate-state>` with the absolute path from the preamble's `SUBSTRATE_STATE` session-state line (it is NOT a shell variable — like `${SUBSTRATE_ROOT}`, it does not expand in the Cowork VM shell, and an unset-var expansion would silently target `/.env`):

   ```bash
   printf '%s' "<harness_key>" | python3 -c '
   import sys, pathlib
   p = pathlib.Path(sys.argv[1])
   assert str(p).endswith(".be-civic/state/.env"), "refusing: not a .be-civic/state/.env path"
   key = sys.stdin.read().strip()
   p.parent.mkdir(parents=True, exist_ok=True)
   p.write_text("BECIVIC_HARNESS_KEY=%s\n" % key)
   p.chmod(0o600)
   ' "<resolved-substrate-state>/.env"
   ```

   (The folder already exists, so the single `.gitignore` from 6.2 is already in place and the key is never staged — confirm `git check-ignore -q -- .be-civic/state/.env` passes if in doubt.) Write `user-id` if it is absent. **Do NOT overwrite an existing `profile.json`, `preferences.json`, `procedures.json`, the marker, `CLAUDE.md`, or anything else in the folder** — those were already written when the folder was set up. Delete `.pending-verification` once `verify` succeeds.
5. **Return control to the harness.** The key is now present; the harness self-check (its §3.0) passes and it proceeds with the carry-over it already has. Do not run the about-you form here — that is the harness's job in the working session.

If the user declines verification again, fall to anonymous-read mode (§1.1): the project stays on disk, but wire-gated work (full Process bodies, submissions) stays unavailable until they verify.

---

## Harness-repair mode (missing CLAUDE.md recovery)

The gate routes here when a project marker exists but `${SUBSTRATE_DATA}/CLAUDE.md` does not — setup wrote the marker then crashed before writing the harness file (the marker lands before `CLAUDE.md`, per the Step 6.2 reference write order). Without `CLAUDE.md` the substrate's ancestor-walk has nothing to load, so no harness comes up and no canary fires. **Do NOT re-run the whole flow and do NOT re-mint identity.** Write only the missing harness file, reusing the state already on disk.

1. **Confirm the gap.** A `.be-civic/marker` exists (the project is real) but `${SUBSTRATE_DATA}/CLAUDE.md` is missing. `${SUBSTRATE_DATA}` is the folder holding the marker (the same folder `preamble.py` resolves from the marker). If the key is also absent, do the verification-only mode first, then return here.
2. **Write the harness file VERBATIM.** First resolve the install root with the discovery step ("Resolve the install root", above) into `$BC_ROOT` — `${SUBSTRATE_ROOT}` does not expand in the Cowork shell. Then **copy** `$BC_ROOT/skills/bc-onboarding/references/harness-CLAUDE.md` to `${SUBSTRATE_DATA}/CLAUDE.md` with `bash cp` (the `CLAUDE.md` write per the Step 6.2 reference). The canonical template **is** reachable once you have `$BC_ROOT` — copy it byte-for-byte; do **not** reconstruct it from memory, and **do NOT append a `## Carry-over` block** (the carry-over lives in `procedures.json` + `preferences.json`, which are already on disk; the preamble reads them). The written `CLAUDE.md` must be byte-identical to the canonical harness. If `$BC_ROOT` resolves empty, tell the user and retry rather than hand-writing the harness. Do not write a CLAUDE.md inside any per-procedure subfolder.
3. **Do not touch anything else.** Leave `profile.json`, `preferences.json`, `procedures.json`, `.env`, `user-id`, and the marker as they are. You are filling a single missing file, not rebuilding the project. The carry-over the harness needs is already in the state files (`procedures.json` + `preferences.json`); there is nothing to reconstruct in the harness file. If `procedures.json` is empty too (a deeper crash), this is effectively a fresh setup — re-run the Step 6.2 project write (`setup_project.py`, or the manual fallback per the Step 6.2 reference).
5. **Hand the user into the project.** The harness file now exists, so run the Step 7 handoff: tell the user the canary to expect, give them the clickable open-project link to `${SUBSTRATE_DATA}`, and end. On the next chat the ancestor-walk loads the now-present `CLAUDE.md` and the harness self-check + canary run normally.

---

## Imported-state branch (returning user, new machine)

A returning user may arrive with a `bc-import` bundle from another machine. When the gate flags an import bundle in scope, it routes here to the imported-state branch instead of first-contact:

1. **Validate the bundle** — confirm the project-folder layout is intact (`CLAUDE.md`, `MEMORY.md`, `.be-civic/marker`, `.be-civic/state/`) and the bundle's `state_version` is not newer than this plugin (if it is, tell the user to upgrade the receiving plugin first; do not activate).
2. **Activate the folder** — have the user pick a parent (Step 6.1), then restore the whole project folder into `<picked-parent>/BeCivic/` as `${SUBSTRATE_DATA}`, including its hidden `.be-civic/state/` and the single `.gitignore`. `bc-import` restores the harness key to `${SUBSTRATE_STATE}/.env` **when the bundle carried it** — the exporter writes the key as a loose `identity/env` member (it is gitignored, so absent from the committed bundle). A key-bearing bundle is therefore credential-bearing; treat it like a passport scan. Write/refresh the `.be-civic/marker` so detection resolves to this folder.
3. **Frame as a returning user**, not a new one — never re-mint profile/registry. Check the key: if `${SUBSTRATE_STATE}/.env` has a `BECIVIC_HARNESS_KEY` after restore (the bundle carried identity), the user is fully restored — hand off to `bc-path-traversal` (or the inline framing) with **no** email gate. Only if the key is absent (the bundle was exported without identity) does the keyless half-state trigger the identity-preserving email→code recovery (re-verifying the same email restores the **same** `user_id`, not a new one). Either way, no new identity is minted.

---

## Anonymous-read mode (recap)

If the user never verifies (declined at §1.1, closed the email widget at §2, or the verification service was unreachable), the session runs read-only on `corpus:read:public`:

- `WebFetch` reads of the manifest (which includes a short outline per procedure), **no Bearer** (Process bodies stay gated — anonymous `GET /api/processes/<id>` returns `401`).
- No submissions. No folder. No `${SUBSTRATE_STATE}` writes. No marker.
- The mode resets each session — the next session starts anonymous again until the user opts in.

Frame the limit as a choice the user can reverse any time, never as a failure.

---

## Meta-question handling

`bc-onboarding` **does not own meta questions.** The `be-civic` gate answers them in chat from `${SUBSTRATE_ROOT}/data/privacy-snippet.md` **verbatim**.

If the user asks a meta question mid-onboarding (between the Step 1 framing and the email submit), pause the flow, quote `privacy-snippet.md` verbatim (load it from the file — **never paraphrase**), then offer:

> "Want me to carry on setting you up, or talk through the data side first?"

If they want to keep talking about data, hold position. If they decide not to proceed, fall to the anonymous-read fallback (§1.1).

---

## What this skill does NOT own

- The harness rules (Iron Law, situation assessment, observation handling, document handling, session close). Those live in `${SUBSTRATE_DATA}/CLAUDE.md` after this skill writes it.
- Procedure walking, document extraction, path traversal. Peer skills (`bc-path-traversal`, `bc-document-handler`) invoked by the harness.
- Returning sessions, multi-active pivots. The gate + harness handle those.
- Meta-question answering, off-topic redirect, no-intent tour. The `be-civic` gate handles those.
- The auto-commit monitor (`hooks/auto-commit-monitor.js`) and the recovery sweep (`preamble.py`). This skill writes the markers and `.gitignore` files they depend on, then gets out of the way.

**First-contact (Chat 1)** exists for one thing: take a user who said yes at the gate → match the procedure they came for → verify their email → pick the project folder → mint their pseudonymous identity → write the project state shape (one folder, one git repo) with the carry-over → hand the user cleanly into a fresh chat inside their project folder, where the harness takes over. First-contact does not introduce the plan, does not run the procedure, and does not render the about-you form — the about-you form belongs to **first-working-session mode** (Chat 2), and the procedure walk belongs to the harness + `bc-path-traversal`.
