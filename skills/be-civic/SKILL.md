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

## 2. Project found (marker present) — harness is driving

The CLAUDE.md harness inside this folder is already loaded as session context and is driving. Don't re-read CLAUDE.md, don't re-deliver framing, don't repeat onboarding.

**First, confirm the harness file actually exists.** A marker can be present while `CLAUDE.md` is missing — a setup that crashed between writing `.be-civic/marker` and writing the harness `CLAUDE.md`. In that half-written state nothing auto-loads, so no harness is there to greet the user or self-check, and a silent return would leave the user with no response. So before deferring, check that the project root (the folder holding the marker, or its parent if the marker is in a `.be-civic/` subdir) contains a `CLAUDE.md`. If it does **not**, this is a half-written project: route to `be-civic:bc-onboarding`, which runs its **harness-repair mode** (writes the missing harness `CLAUDE.md` + carry-over from the existing registry/preferences, or re-runs setup if those are missing too) — rather than deferring into a void. (`bc-onboarding` explicitly allows this even though a marker is present.)

**When `CLAUDE.md` is present, defer silently — do NOT emit your own greeting or confirmation.** The harness opens the session with its own project-specific greeting (it names the user's procedure in their language as the first message — its load self-confirmation). If you post a generic "you're in your Be Civic project" line first, you pre-empt that signal and the user can't tell the harness actually loaded. So when the marker AND the harness file are present, return control immediately and let the harness's first message stand as the opener.

Return control to the conversation. The harness handles everything from here, including the opening greeting.

## 3. Intent classification (four classes — MECE)

When the marker is **absent** (new user or outside any project folder), classify the user's opening message into exactly one of four mutually exclusive, collectively exhaustive classes before deciding how to respond:

| Class | Signal | Handling |
|---|---|---|
| `procedure_intent_clear` | User names a specific Belgian administrative goal ("I need to register my address", "apply for nationality") | AskUserQuestion: three MECE options — see §4 |
| `procedure_intent_vague` | User mentions Belgian admin in a general or uncertain way ("I think I need to do something about my residence?") | Same AskUserQuestion gate as `procedure_intent_clear`; bc-onboarding Section 2 may degrade to discovery if the procedure cannot be matched |
| `meta` | User asks about Be Civic itself or its data practices ("what does Be Civic do with my data?", "how does this work?") | Answer in chat from the canonical privacy snippet (§7); never paraphrase it; no AskUserQuestion; no folder created |
| `off_topic` / `no_intent` | No Belgian admin signal at all, or user typed `/be-civic` without context | 2–3 line tour or polite redirect; no folder created |

**MECE rule:** every AskUserQuestion this skill issues must be Mutually Exclusive + Collectively Exhaustive. The gate's own question (§4) satisfies this by design: the three options cover the full decision space (proceed fully / proceed partially / decline) with no overlap. When designing any additional question in this skill, use two labelled options + a free-text fallback if three clean options cannot be found.

If the user's message matches a procedure by name, you may use `WebFetch GET https://becivic.be/api/manifest` to confirm the process ID before routing — search client-side over the returned entries by title / summary / applies_to.

## 4. Project NOT found, user has procedure intent (clear or vague)

Explain Be Civic in plain language, two-three sentences. **When intent is `procedure_intent_clear`, name the procedure the user just mentioned** — don't re-pitch generically or re-ask what they came for; they told you. Acknowledge it and go straight to the one decision that's actually open (set up a project or not):

> "I can help with your **<the procedure they named, e.g. Belgian nationality declaration>**. Be Civic gives me a verified library of Belgian admin procedures I can walk you through step by step, and I can save your progress in a project folder on your computer between sessions. Want me to get you set up? It takes a minute."

(For `procedure_intent_vague`, keep the generic framing: *"I can help with that. Be Civic gives me a verified library of Belgian admin procedures — citizenship, residency, commune registrations, driving licences, that kind of thing. Want me to get you set up?"*)

Use AskUserQuestion with three options (MECE: the three options are exhaustive and non-overlapping):

- **A) Yes, get me set up** (recommended) — invokes `bc-onboarding` peer skill in `new-project` mode. That skill calls `request_cowork_directory`, creates the project folder (`${SUBSTRATE_DATA}`) as a single git repo, writes the harness CLAUDE.md, initialises empty agent-managed state in the hidden `.be-civic/state` subdir (`${SUBSTRATE_STATE}`), writes the `.be-civic/marker`, runs the intake.
- **B) Just answer this one question** — advice-only mode. Answer the user's immediate question with a brief disclaimer that nothing persists to disk, no observations are buffered, and the harness discipline does not apply. After answering, gently offer the project setup again as a follow-up.
- **C) Not interested** — close out politely.

For `procedure_intent_vague`: route identically. bc-onboarding's Section 2 will attempt to match the procedure; if it cannot, it degrades gracefully to discovery mode.

## 5. bc-import bundle detection

Before routing on marker presence, check whether the user has attached or referenced a **bc-import bundle** (a `.tar.gz` archive created by `scripts/bc_import.py`). Signals: file named `bc-export-*.tar.gz`, a `.tar.gz` that contains `manifest.json` at the root, or the user explicitly says "I'm importing my Be Civic data from another device".

When an import bundle is supplied, run the activation script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/bc_import.py <bundle.tar.gz> --cowork --data-parent <user-chosen-parent>
```

The script validates the bundle, checks `state_version` against the running plugin, restores the project folder (including its hidden `.be-civic/state` subdir), and writes the `.be-civic/marker`. If the bundle carried the user's identity (the exporter includes the harness key as a loose `identity/env` member when present), the import restores it and the user is fully restored. If not, post-import state is "returning user, needs to re-verify" (identity-preserving — re-verifying the same email restores the same identity).

If an import bundle is detected:

1. Route to `bc-onboarding` in **imported-state** mode regardless of whether a local marker exists.
2. bc-onboarding validates the bundle, activates the restored project folder (state subdir included), writes the marker, and frames the experience as a returning user continuing their work.
3. Do NOT treat an import as a new-user setup; preserve the existing process state.

## 6. Project NOT found, user has no specific query yet (off_topic / no_intent)

If the user invoked this skill manually without mentioning Belgian admin (e.g., they typed `/be-civic` to see what it does), use a softer opening without launching AskUserQuestion:

> "Be Civic is a verified library of Belgian administrative procedures I can draw on — citizenship, residency, commune registrations, and more. Tell me what you're trying to sort out and I'll get you set up."

No folder is created, no onboarding is triggered.

## 7. Canonical privacy snippet (meta intent)

When the user's message classifies as `meta` — specifically a question about data handling, privacy, or what Be Civic stores — respond with the following verbatim. Do not paraphrase, summarise, or shorten it:

> Everything you tell me stays in a Be Civic folder on your own computer — your situation, your notes, and any documents you share. Your name, your documents, your ID numbers, and your address never leave your machine.
>
> The only things that ever leave your computer are your email, basic routing information to get the right procedural guidance (commune, residency status etc.), and any anonymous feedback you agree to send to Be Civic.
>
> Verifying your email creates a Be Civic account to authenticate your access to the service and prevent misuse. Be Civic also receives basic usage stats (which procedures get used, where your agent gets stuck — never anything you typed).
>
> At the end of a session I will ask if you want to send feedback — for example, that a fee changed or a document wasn't on the list. Those notes are useful to other people doing the same thing in the same place, each one includes your region, your commune, and the language you're working in — but never anything that identifies you. You see every note before it's sent, and you can cancel it for 48 hours after.
>
> To remove everything and cancel Be Civic: delete the folder to wipe what's on your computer, and ask me to erase your Be Civic account, which removes your email and unlinks your past notes.

After delivering this snippet, offer to continue with the user's original goal if there was one.

## What this skill does NOT own

- The harness rules (Iron Law, situation assessment, observation handling, document handling, session close). Those live in the project's CLAUDE.md.
- Process identification beyond a quick manifest lookup, the process graph walk, catalogue calls. Those happen in CLAUDE.md and the peer skills.
- Onboarding intake, project initialisation. That is `bc-onboarding`.
- Discovery flow, path traversal, dossier compilation. Those are peer skills invoked by the harness.

This skill exists only to bridge "user is in Cowork, hasn't set up a Be Civic project yet" → "user is in their Be Civic project with the harness loaded."
