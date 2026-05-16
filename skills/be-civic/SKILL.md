---
name: be-civic
description: Gate for Be Civic — Belgian administrative procedures. Use when the user mentions Belgian administration, citizenship, residency, commune registration, mutualité, address change, residence card renewal, BIPL or inburgering integration parcours, apostille, EU multilingual forms, dossier compilation, or any Belgian city or commune in an administrative context. Checks whether the conversation is running inside a Be Civic project folder. If yes, the project CLAUDE.md harness is already driving. If no, walks the user through setting one up via Cowork request_cowork_directory.
---

# Be Civic — Gate

This skill is the thin entry point for the Be Civic plugin. Its only job is to detect whether the user is inside a Be Civic project folder and route accordingly. All real work — the harness rules, procedure walking, document handling, observation buffering, session close — happens through the project's CLAUDE.md and the bc-* peer skills.

## 1. Detect project context

Check the current working directory and its parents for a `.be-civic/marker` file (the marker lives under a hidden `.be-civic/` directory so it stays out of the user's sidebar):

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

## 2. Project found

The CLAUDE.md harness inside this folder is already loaded as session context and is driving. Don't re-read CLAUDE.md, don't re-deliver framing, don't repeat onboarding.

Confirm briefly and exit:

> "You're in your Be Civic project — the harness is loaded and active. Let me know what you'd like to work on."

Return control to the conversation. The harness handles everything from here.

## 3. Project NOT found, user has an administrative query

Explain Be Civic in plain language, two-three sentences:

> "Be Civic is a guided walkthrough for Belgian administrative procedures — citizenship declarations, residency, commune registrations, that kind of thing. It works best when you set up a Be Civic project folder once, so your notes and documents stay with you across sessions. Want me to set one up now? It takes a minute."

Use AskUserQuestion with three options:

- **A) Yes, set up a Be Civic project** (recommended) — invokes `bc-onboarding` peer skill in `new-project` mode. That skill calls `request_cowork_directory`, writes the harness CLAUDE.md, initialises empty state, runs the intake.
- **B) Just answer this one question** — advice-only mode. Answer the user's immediate question with a brief disclaimer that nothing persists to disk, no observations are buffered, and the harness discipline doesn't apply. After answering, gently offer the project setup again as a follow-up.
- **C) Not interested, drop the subject** — close out politely.

## 4. Project NOT found, user has no specific query yet

If the user invoked this skill manually without mentioning Belgian admin (e.g., they typed `/be-civic` to see what it does), use a softer opening:

> "Be Civic is a guided walkthrough for Belgian administrative procedures. I work best inside a project folder where I can keep your notes between sessions. Want a quick overview, or shall we set up a project?"

Then offer the same options as §3.

## What this skill does NOT own

- The harness rules (Iron Law, situation assessment, observation handling, document handling, session close). Those live in the project's CLAUDE.md.
- Procedure identification, the skills graph fetch, MCP calls. Those happen in CLAUDE.md and the peer skills.
- Onboarding intake, project initialisation. That's `bc-onboarding`.
- Discovery flow, path traversal, dossier compilation. Those are peer skills invoked by the harness.

This skill exists only to bridge "user is in Cowork, hasn't set up a Be Civic project yet" → "user is in their Be Civic project with the harness loaded."
