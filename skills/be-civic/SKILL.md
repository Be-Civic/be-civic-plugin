---
name: be-civic
description: Gate for Be Civic — Belgian administrative procedures. Use when the user mentions Belgian administration, citizenship, residency, commune registration, mutualité, address change, residence card renewal, BIPL or inburgering integration parcours, apostille, EU multilingual forms, dossier compilation, or any Belgian city or commune in an administrative context. Classifies the user's intent (procedure_intent_clear, procedure_intent_vague, meta, off_topic/no_intent) and routes accordingly. If inside a Be Civic project folder, the project CLAUDE.md harness is already driving — confirms and exits. If no project folder exists and the user has an admin query, invokes bc-onboarding to handle folder setup and onboarding.
---

# Be Civic — Gate

This skill is the thin entry point for the Be Civic plugin. Its only job is to classify the user's intent, detect whether a Be Civic project folder is already initialised, and route to the correct peer skill. All real work — the harness rules, process walking, document handling, observation buffering, session close — happens through the project's CLAUDE.md and the bc-* peer skills.

## 1. Detect project context

Check the current working directory and its parents for a `.be-civic/marker` file (the marker lives under a hidden `.be-civic/` subdirectory so it stays out of the user's sidebar):

```bash
# Walk upward from the cwd looking for the marker.
dir=$(pwd)
while [ "$dir" != "/" ]; do
  if [ -f "$dir/.be-civic/marker" ]; then
    echo "be-civic project root: $dir"
    exit 0
  fi
  dir=$(dirname "$dir")
done
echo "no be-civic project found"
```

Note: older Be Civic projects (created before the `.be-civic/` subdirectory was introduced) used a top-level `.be-civic-project` marker file. Check that fallback location too:

```bash
[ -f "$dir/.be-civic-project" ] && echo "be-civic project root: $dir (legacy marker)" && exit 0
```

If found at the legacy location, offer to migrate: move the marker into `.be-civic/marker` and any state files under the new hidden subdirectory.

If the bash tool is unavailable, fall back to checking just the current working directory with the available filesystem tool.

Also check whether the user's message or attached files contain a **bc-import bundle** (see §5 below) before branching on marker presence.

## 2. Project found (marker present) — returning user

The CLAUDE.md harness inside this folder is already loaded as session context and is driving. Don't re-read CLAUDE.md, don't re-deliver framing, don't repeat onboarding.

Confirm briefly and route to bc-path-traversal / resume:

> "You're in your Be Civic project — the harness is loaded and active. Let me know what you'd like to work on."

Return control to the conversation. The harness handles everything from here.

## 3. Intent classification (four classes — MECE)

When the marker is **absent** (new user or outside any project folder), classify the user's opening message into exactly one of four mutually exclusive, collectively exhaustive classes before deciding how to respond:

| Class | Signal | Handling |
|---|---|---|
| `procedure_intent_clear` | User names a specific Belgian administrative goal ("I need to register my address", "apply for nationality") | AskUserQuestion: three MECE options — see §4 |
| `procedure_intent_vague` | User mentions Belgian admin in a general or uncertain way ("I think I need to do something about my residence?") | Same AskUserQuestion gate as `procedure_intent_clear`; bc-onboarding Section 2 may degrade to discovery if the procedure cannot be matched |
| `meta` | User asks about Be Civic itself or its data practices ("what does Be Civic do with my data?", "how does this work?") | Answer in chat from the canonical privacy snippet (§6); never paraphrase it; no AskUserQuestion; no folder created |
| `off_topic` / `no_intent` | No Belgian admin signal at all, or user typed `/be-civic` without context | 2–3 line tour or polite redirect; no folder created |

**MECE rule:** every AskUserQuestion this skill issues must be Mutually Exclusive + Collectively Exhaustive. The gate's own question (§4) satisfies this by design: the three options cover the full decision space (proceed fully / proceed partially / decline) with no overlap. When designing any additional question in this skill, use two labelled options + a free-text fallback if three clean options cannot be found.

If the user's message matches a procedure by name, you may use `WebFetch GET https://becivic.be/api/manifest` to confirm the process ID before routing — search client-side over the returned entries by title / summary / applies_to.

## 4. Project NOT found, user has procedure intent (clear or vague)

Explain Be Civic in plain language, two-three sentences:

> "Be Civic is a guided walkthrough for Belgian administrative procedures — citizenship declarations, residency, commune registrations, that kind of thing. It works best when you set up a Be Civic project folder once, so your notes and documents stay with you across sessions. Want me to set one up now? It takes a minute."

Use AskUserQuestion with three options (MECE: the three options are exhaustive and non-overlapping):

- **A) Yes, set up a Be Civic project** (recommended) — invokes `bc-onboarding` peer skill in `new-project` mode. That skill calls `request_cowork_directory`, writes the harness CLAUDE.md, initialises empty state on both the hidden surface (`${SUBSTRATE_STATE}`) and the visible surface (`${SUBSTRATE_DATA}`), writes `.be-civic/marker` to both surfaces, runs the intake.
- **B) Just answer this one question** — advice-only mode. Answer the user's immediate question with a brief disclaimer that nothing persists to disk, no observations are buffered, and the harness discipline does not apply. After answering, gently offer the project setup again as a follow-up.
- **C) Not interested, drop the subject** — close out politely.

For `procedure_intent_vague`: route identically. bc-onboarding's Section 2 will attempt to match the procedure; if it cannot, it degrades gracefully to discovery mode.

## 5. bc-import bundle detection

Before routing on marker presence, check whether the user has attached or referenced a **bc-import bundle** (a `.tar.gz` archive created by `scripts/bc_import.py`). Signals: file named `bc-export-*.tar.gz`, a `.tar.gz` that contains `manifest.json` at the root, or the user explicitly says "I'm importing my Be Civic data from another device".

When an import bundle is supplied, run the activation script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/bc_import.py <bundle.tar.gz> --cowork --data-parent <user-chosen-parent>
```

The script validates the bundle, checks `state_version` against the running plugin, restores both surfaces, and writes the `.be-civic/marker` cross-references. Identity is not in the bundle; post-import state is "returning user, needs to re-verify".

If an import bundle is detected:

1. Route to `bc-onboarding` in **imported-state** mode regardless of whether a local marker exists.
2. bc-onboarding validates the bundle, activates into both the hidden and visible surfaces, writes the marker, and frames the experience as a returning user continuing their work.
3. Do NOT treat an import as a new-user setup; preserve the existing process state.

## 6. Project NOT found, user has no specific query yet (off_topic / no_intent)

If the user invoked this skill manually without mentioning Belgian admin (e.g., they typed `/be-civic` to see what it does), use a softer opening without launching AskUserQuestion:

> "Be Civic is a guided walkthrough for Belgian administrative procedures — citizenship, residency, commune registrations, and more. I work best inside a project folder where I can keep your notes between sessions. Mention an administrative goal when you're ready and I'll help you get started."

No folder is created, no onboarding is triggered.

## 7. Canonical privacy snippet (meta intent)

When the user's message classifies as `meta` — specifically a question about data handling, privacy, or what Be Civic stores — respond with the following verbatim. Do not paraphrase, summarise, or shorten it:

> "Be Civic stores your administrative notes and documents locally in a folder you choose. Nothing leaves your device unless you explicitly submit a report or observation to the Be Civic knowledge graph, at which point only the content of that submission is sent — never your personal documents or profile data. Your harness key (used to authenticate submissions) is kept in a hidden state folder that is never committed to git. You can rotate or erase your identity at any time via the key-rotation flow."

After delivering this snippet, offer to continue with the user's original goal if there was one.

## What this skill does NOT own

- The harness rules (Iron Law, situation assessment, observation handling, document handling, session close). Those live in the project's CLAUDE.md.
- Process identification beyond a quick manifest lookup, the process graph walk, catalogue calls. Those happen in CLAUDE.md and the peer skills.
- Onboarding intake, project initialisation. That is `bc-onboarding`.
- Discovery flow, path traversal, dossier compilation. Those are peer skills invoked by the harness.

This skill exists only to bridge "user is in Cowork, hasn't set up a Be Civic project yet" → "user is in their Be Civic project with the harness loaded."
