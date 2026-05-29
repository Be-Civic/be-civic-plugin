---
description: Be Civic Cowork plugin. Substrate-side harness binding for the Cowork agent runtime. Wire-side delivery surface for the Be Civic platform.
model: sonnet
---

# Be Civic Plugin

## Identity

This repo is the harness binding that runs Be Civic inside the user's Cowork agent runtime. It provides the platform-facing Claude Code Skills (`bc-document-handler`, `bc-dossier-compilation`, `bc-path-traversal`, `bc-discovery`, `bc-onboarding`), the prompt → form → install flow, and the wire-side tool calls that connect the Cowork substrate to the Be Civic platform. It sits substrate-side — it runs in the user's agent environment, not on Be Civic's infrastructure.

## V2 wire

The plugin calls the Be Civic REST API at `becivic.be/api/*` via the `WebFetch` tool, authenticated with a per-installation Bearer harness key (`${SUBSTRATE_STATE}/.env`). V1 `mcp__becivic__*` MCP tools are retired — the hard cutover landed in W33; there is no MCP fallback.

## Hard rules

- Plugin code is substrate-side. The trust boundary runs between this code and `becivic.be/api/*`. Identity-bearing fields must be scrubbed before egress — per `50-harness.md §3` and `02-trust-and-privacy.md`.
- Never write secrets into plugin sources. If a credential is needed at runtime, use `agent-run` (see Secrets below).
- All canonical reference for plugin behaviour lives in the handbook — read `50-harness.md`, `51-cowork.md`, `40-substrate.md` before modifying harness or binding logic.

## Handbook pointers

| Section | Read when |
|---|---|
| `../bc-workspace/handbook/content/05-product/50-harness.md` | Modifying harness behaviour — preamble, gate skill, peer-skill inventory, drafter subagents, session lifecycle, voice |
| `../bc-workspace/handbook/content/05-product/51-cowork.md` | Cowork-specific binding — first-contact directory selection, atomic-commit monitor, visible/hidden allowlists, capability declaration |
| `../bc-workspace/handbook/content/05-product/40-substrate.md` | Substrate-side state contract — state-on-disk layout, identity-store discipline, schema migration, atomic-commit invariants |
| `../bc-workspace/handbook/content/04-domain/01-vocabulary.md` | Citing entities or vocabulary (Process, Path, Tool, Issue, etc.) |

## Project-wide pointer

Project-wide operating procedures live in the Be Civic handbook at `../bc-workspace/handbook/content/`. Section routing in `../CLAUDE.md` (be-civic project root).

## Secrets

Secrets on this workstation are brokered via Bitwarden. To read a credential, call `agent-run --project <bw-project> --secret <key> --as <agent-id>` (see `~/.claude/references/secrets.md`). Never read `.env`, `.bashrc`, or other dotfiles for credentials.

## Branch model

Plugin repo follows the standard be-civic ops-trio model — direct push to main with required CI checks. See `../bc-workspace/handbook/content/09-devops/03-branch-policy.md` for the full table.
