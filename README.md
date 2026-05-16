# Be Civic — Cowork plugin

Belgian administrative procedures assistant for Claude Cowork. Installs as a Cowork plugin; works alongside a per-user **Be Civic project folder** that holds the harness CLAUDE.md and the customer's notes/dossier across sessions.

## Repo status

Pre-launch. Iterating in private. Public marketplace listing not yet active.

## What ships in this plugin

- The **be-civic skill** — a thin gate that checks whether the conversation is running inside a Be Civic project folder, and starts onboarding if not.
- **Peer skills** — `onboarding`, `discovery`, `document-handler`, `path-traversal`, `session-close`, `dossier-compilation`. Each is a focused mode that the harness invokes.
- **Drafter sub-agents** — `be-civic-path-drafter`, `be-civic-skill-drafter`. Spawned by `session-close` to draft amendments and new entries from session research-notes.
- **MCP wiring** — connects to `mcp.becivic.be` for the live skills graph, procedure canonicals, path directory, and submission endpoints.
- **State schemas** — `profile.schema.json`, `observation.v3.schema.json`. Stable contracts the harness writes against.
- **Layer-1 scrub rules** — local PII scrub before any submission leaves the machine.

## What lives in the user's project folder, NOT here

- The **harness CLAUDE.md** — written by the onboarding flow into the user's chosen folder. Loaded as session context on every conversation start in that folder. The harness drives the entire session.
- The user's `profile.json`, `memory.md`, `documents/`, `sessions/`, and `memory/research-notes-*.md` — all customer state.

The plugin auto-updates from this repo on every commit. The user's CLAUDE.md is one-time-written by onboarding and stays put unless re-initialised.

## Install

In Claude Cowork: open the **Customize** sidebar, browse plugins, find **Be Civic** in the org marketplace, click install.

Tested on Cowork desktop 2026-05-16. See `docs/MAINTENANCE.md` for operator notes.

## Companion repos

- `hk121992/be-civic` — the public corpus (bc-docs). Verified Belgian administrative procedures, paths, schemas, public site.
- `bc-operations` (local-only) — strategy, specs, retrospectives, internal product narrative.

## License

To be set before any public install. Private repo until then.
