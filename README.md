# Be Civic — Cowork plugin

Belgian administrative procedures assistant for Claude Cowork. Installs as a Cowork plugin; works alongside a per-user **Be Civic project folder** that holds the harness CLAUDE.md and the customer's notes/dossier across sessions.

## Repo status

Pre-launch. Public repo for early testers; not yet listed on the official Anthropic plugin registry.

## What ships in this plugin

- The **be-civic skill** — a thin gate that checks whether the conversation is running inside a Be Civic project folder, and starts onboarding if not.
- **Peer skills** — `onboarding`, `discovery`, `document-handler`, `path-traversal`, `session-close`, `dossier-compilation`. Each is a focused mode that the harness invokes.
- **Drafter sub-agents** — `be-civic-path-drafter`, `be-civic-process-drafter`. Spawned by `session-close` to draft amendments and new entries from session research-notes.
- **API wiring** — connects to `becivic.be/api` for the live process graph, procedure canonicals, path directory, and submission endpoints.
- **State schemas** — `profile.schema.json`, `observation.v3.schema.json`. Stable contracts the harness writes against.
- **Layer-1 scrub rules** — local PII scrub before any submission leaves the machine.

## What lives in the user's project folder, NOT here

- The **harness CLAUDE.md** — written by the onboarding flow into the user's chosen folder. Loaded as session context on every conversation start in that folder. The harness drives the entire session.
- The user's `profile.json`, `MEMORY.md`, `documents/`, `sessions/`, and `memory/research-notes-*.md` — all customer state.

The plugin auto-updates from this repo on every commit. The user's CLAUDE.md is one-time-written by onboarding and stays put unless re-initialised.

## Install

### Cowork desktop (recommended)

1. Open the **Customize** sidebar.
2. **Browse plugins → Personal**.
3. Click **"+"** → **"Add marketplace from GitHub"**.
4. Paste: `https://github.com/hk121992/be-civic-plugin`
5. Install **Be Civic** from the catalog.

The plugin auto-updates on every push to this repo.

### Claude Code CLI

```
/plugin marketplace add hk121992/be-civic-plugin
/plugin install be-civic
```

### Cowork desktop, zip-upload fallback

If the marketplace path doesn't work for you (e.g. proxy, network restriction), download the source zip from this repo's [Releases](https://github.com/hk121992/be-civic-plugin/releases) and upload it via Customize → My Uploads.

## License

MIT — see [LICENSE](LICENSE).
