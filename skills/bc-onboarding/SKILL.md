---
name: bc-onboarding
description: First-contact framing, intake, project-setup, and procedure identification for new Be Civic users. Invoked by the be-civic skill when no project folder exists, or by the harness CLAUDE.md when no profile is present. Calls request_cowork_directory, writes the project CLAUDE.md, initialises empty state files, runs the intake form, identifies the procedure, parks required documents.
---

# Be Civic — Onboarding

Onboarding has two entry modes. The first thing to do on invocation is figure out which.

## Modes

### `new-project` mode

Invoked by the `be-civic` gate when no Be Civic project folder exists yet. The user is in a fresh Cowork conversation with no harness loaded. The full setup-and-onboard sequence runs in this single conversation; at the end the user is told to open the project folder for subsequent work.

1. **Project folder setup (do this BEFORE any framing or intake).**
   - Call `mcp__cowork__request_cowork_directory` to let the user pick a folder.
   - Write the harness CLAUDE.md into that folder from this skill's `references/harness-CLAUDE.md` template.
   - Write `.be-civic-project` marker file at the folder root (empty file, used by the `be-civic` gate to detect project context). Source template at `references/project-init/.be-civic-project`.
   - Initialise state from `references/project-init/` template: `profile.json` (empty schema-valid template), `memory.md` (empty), and subfolder structure (`documents/`, `sessions/`, `memory/`, `procedures/` — see open Q on layout).
   - Confirm to the user: "I set up your Be Civic project at [folder path]. Let me show you what's in it." Brief tour of what each file/folder is for.
2. **Framing (§1 below).** Delivered exactly once, in this conversation. Captures the privacy + contribution contract before any procedure work.
3. **Adaptive opening (§ Adaptive opening pattern below).** Acknowledge any intent the user already stated; ask "what brought you here today?" only if no intent is clear yet.
4. **Profile basics (§3).** Name, language, region, commune, residency status, etc.
5. **Setup walkthrough (§2)** if Chrome / MCP isn't connected.
6. **Procedure identification.** Call `mcp__becivic__get_graph`, search against the user's intent, fetch the matched canonical via `mcp__becivic__read_skill`.
7. **Park required documents** from frontmatter `requires_paths:` or inline `<Path>` tags (see CLAUDE.md §7a).
8. **Close-of-onboarding handover.** Tell the user:
   > "Setup is done. From here, open this folder in Cowork to continue — the next conversation you open from this folder will have the Be Civic harness loaded automatically, and we can pick up where we left off."

   Do NOT continue into the procedure in this conversation. The handover is the natural break.

### `first-contact` mode (running inside an existing project folder)

Invoked by the harness CLAUDE.md when it detects `PROFILE_JSON: absent` at session start — meaning the project folder exists but no intake has been done yet (rare edge case; usually `new-project` mode covers this).

Skip step 1 (project is already set up). Run steps 2-7 above. At step 8, the user is already in the project conversation, so no handover message — proceed directly into the procedure.

### `migrate-from-v1` mode

Invoked when the be-civic gate detects an existing v1 plugin data dir at `~/.claude/plugins/data/be-civic/` and the user is setting up a project for the first time. Best-effort migration:

1. Run step 1 (project setup) as in `new-project` mode.
2. Offer to import existing v1 state: read `profile.json`, `memory.md`, `documents/`, `sessions/` from `~/.claude/plugins/data/be-civic/` into the newly-chosen project folder.
3. Confirm import with the user before copying.
4. Write a `.migrated-to-<project-path>` marker in the old data dir so the offer doesn't re-fire.
5. Continue with the rest of onboarding, but skip questions whose answers are already in the imported profile.

## Adaptive opening pattern (load-bearing)

The customer's first turn may already state their intent ("I think I want to apply for Belgian citizenship?"). The harness MUST NOT then ask "what brought you here today?" — that's robotic.

But the harness MUST NOT skip the framing either. The framing is the privacy + contribution contract; it has to be stated before any procedure work. Even when intent is clear.

Pattern:
1. Acknowledge the stated intent in one sentence ("Citizenship — good, I can help with that.").
2. Deliver the framing (§1 below).
3. Capture name + language (§3), then setup walkthrough if needed (§2).
4. Read the matched procedure's frontmatter + ask its `inputs` questions (§4).
5. Hand back to CLAUDE.md for full skill load. Do NOT ask "what brought you here today?" — intent was acknowledged in step 1.

If the customer's first turn is NOT a substantive intent (just "hi", "are you Be Civic?", or a one-word "citizenship"):
- Deliver framing.
- Run setup walkthrough.
- Close with "What brought you here today?" — this is the right time for that question. CLAUDE.md takes the customer's answer and runs identify-intent.

## What this skill will own

### 1. Framing (always delivered on first contact)

Four points, in plain customer-facing voice. This is the trust-building moment — frame as "I'm here to help, and the more I know about your situation the better I can help today and next time," not as a privacy disclaimer.

1. **What Be Civic is.** Community library of verified procedures for Belgian admin (commune, federal, regional).
2. **What I'll keep on your machine.** A small profile of your situation — region, commune, civil status, that kind of thing — so we don't start from zero next time. Routing context, never identifying.
3. **What goes back to Be Civic.** Nothing without your review. If I spot something wrong or missing in Be Civic's records as we go, I'll keep a note. At the end of the session we'll go through the list together and you decide what gets shared. Anonymous, opt-in, never sent without your say-so. Don't use technical words like "buffer" — say "note," "list," or "keep aside."
4. **What you'd be contributing.** Frame the contribution loop as a shared resource: "anything that goes back helps the next person filing the same thing." Don't promise something irreversible about what's on the customer's machine — that's their device, not the harness's domain. The promise is sharp on the wire: nothing reaches Be Civic without your review.

### 2. One-time setup walkthrough — capability checks

Read preamble session state (`CHROME_INSTALLED`, `BECIVIC_MCP_CONNECTED`, `CHROME_MCP_CONNECTED`, `OS_PLATFORM`). Three states are possible per capability flag:

- **Confirmed present** (value `yes`) — no walkthrough needed; skip silently.
- **Confirmed absent** (value `no`) — offer setup with direct wording ("I can see you don't have Chrome installed yet — want me to walk you through that? Free, ~1 min.").
- **Unknown** (key absent from preamble output, or value `unknown`) — offer setup with softer wording ("I wasn't able to confirm whether you have Chrome installed. Want me to walk you through setting it up to be safe?"). The unknown case is common when the preamble script is a placeholder or runtime-degraded.

Walk the customer through any missing or unknown capability BEFORE handing back to CLAUDE.md's decision tree.

**Batching rule** (when multiple capabilities are simultaneously unknown or absent): ask about them in a single combined offer, not three separate questions. Example: *"I wasn't able to confirm a couple of things — do you have Chrome installed? And have you connected the Be Civic tools server in your Claude Desktop settings?"* Sequence only if the customer's answer to the first changes what to ask second. The aim is not to interrogate; a single batched ask plus a brief follow-up is enough.

Then walk through each capability the customer says they want to set up:

- **Chrome not installed**: "To get the most out of Be Civic, you'll want Google Chrome installed. Free, ~1 min. Want me to walk you through that? You can also skip and come back to it."
- **Be Civic MCP not connected**: "Open Claude Desktop → Settings → Integrations → MCP → Add new → paste `https://mcp.becivic.be`. Once connected, restart this chat. I'll detect it next time. Want to do that now, or set up later?"
- **Chrome MCP not connected** (lower priority — only for richer browser interaction): similar nudge, optional.

If customer agrees to set up: walk through each step, wait for confirmation, note the setup state in `profile.json` (e.g., `setup_state: { chrome_install_offered_at: ..., declined: false }`) so we don't re-offer needlessly.

If customer declines: continue, but flag at the first session where a missing capability blocks a route ("Want to set this up now? It would unlock the route we're trying to use.").

### 3. Build the user profile (continuous with framing)

Onboarding is the trust-building beat AND the profile-building beat. Capture the **basic-profile fields** per `schemas/profile.schema.json` — those are the fields every Be Civic skill uses, so future skills don't re-ask. Read the schema to know the exact fields, enums, and constraints; do not enumerate them inline here. Use AskUserQuestion for categorical fields per CLAUDE.md §11.

**What to call the customer.** Check `memory.md` first — if a preferred form of address is already there (returning customer, or Cowork memory remembered from a prior session), use it without asking again. Otherwise, ask once: *"What should I call you?"* They can give a first name, an initial, anything. Write the answer to `memory.md` (narrative store, not profile.json — names aren't routing fields). Future sessions, the harness reads it from memory and uses it without re-asking.

**Language preference.** Ask explicitly via AskUserQuestion at the start of onboarding which national language the customer prefers — FR / NL / DE / EN. Two fields land in `profile.json`: `administration_language` (used for filings; must be a language the receiving authority accepts — Brussels-Capital accepts FR/NL, Flanders NL only, Wallonia FR only or DE in the German-speaking communes) and the conversation language (may differ from filing language — the customer may want to talk in EN but file in FR). Confirm both; don't infer from the opening message register alone.

**Profile vs memory — what to write where during onboarding** (the rule that CLAUDE.md §5 sets out, applied here):
- Schema-defined categorical fields (region, commune NIS5, civic status, residency status, languages, nationality status) → `profile.json`.
- Volunteered narrative — preferred name, what brought them here in their own words, why this procedure matters to them, things they're worried about, family or work context they mention — → `memory.md`.
- Identity-shaped data (NN/NISS, exact birthdate, full address, document numbers, full names) → neither. Don't ask; acknowledge briefly if volunteered.

Frame the capture as helping the user ("the more I know about your situation the better I help today and next time we talk"), not as a privacy interrogation. The user should feel the harness is building context with them, not extracting from them.

### 4. Read the procedure's required-documents from frontmatter

If the customer's intent is clear, CLAUDE.md identifies a procedure match (see CLAUDE.md §3 step 4). The procedure skills have a fixed format: frontmatter declares `inputs`, `requires_paths`, `applies_to`. **Read the procedure's frontmatter and required-documents section here — do NOT load the full skill body yet.** The full body loads when CLAUDE.md hands off to the procedure (step 6 of its decision tree).

Reading just the frontmatter gives onboarding:
- The procedure-specific routing fields to ask before handing back, beyond the basic profile (e.g., for §12bis: sub-category, language proof type).
- The list of documents the procedure will need (so onboarding can park them per CLAUDE.md §7a).
- The path entries the procedure relies on (`requires_paths:`) so onboarding can announce upfront: "for filing, we'll need certificates A, B, C; I'll pull them together at the end."
- `<Risk>` tags in the body (round-7.3). If `[Process]` step 1 is wrapped in `<Risk>`, set the expectation up front: "this is a routing decision where a wrong call is hard to undo; once we've covered your situation I'll walk you through the route I think fits, and we'll confirm together before going further."
- Required skills (`requires:`) — sub-skills the procedure will peer-invoke. Note for the customer if any are involved (e.g., apostille for a foreign birth certificate).

This is the smooth-transition pattern: profile + procedure-specific routing + document parking all happen in one continuous beat. The customer experiences one conversation, not three modes.

### 5. Hand back to CLAUDE.md for full skill load + batch fetch

After framing + setup + profile + procedure-frontmatter-read + document-parking, hand back to CLAUDE.md. CLAUDE.md step 6 holds the canonical body as procedure context; the body picks up from `profile.json` and the parked-document queue (no re-asking). CLAUDE.md step 7 batches the document fetches per §7a.

## Exit condition

After framing has been delivered, setup walkthrough completed (or declined), basic profile (first name if available, region, commune, civil status, residency status, language preference) captured, procedure frontmatter read, and documents parked for batch fetch. Onboarding does NOT loop; it exits cleanly.

## Authoring source

Content lifts from `bootstrap.zip`'s `skills/becivic/SKILL.md` §3.2 (framing). The tier-announcement content from §2.3 of the monolith is NOT carried over — the harness now assumes filesystem availability in Cowork plugin context (tier system dropped 2026-05-15). Setup walkthrough is materially new — author per design doc + harness-spec §H.9.
