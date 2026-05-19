---
name: bc-dossier-compilation
description: Assembles the user's gathered documents into a fully-bound A4 PDF dossier they print and file at the commune. Three modes — initial (first call, mostly placeholders), refresh (a new document arrived), final (terminal step). Writes and iterates on a render.py script in the user's project folder; renders via vendored pure-Python fpdf2 + pypdf. Six presentation classes; watermarks original-required pages in the user's conversation language.
---

<Tip>
Stable skill — agent-tooling sub-skill. Produces a local artefact for the user to file at the commune; Be Civic does not stage or store the dossier. No consumer-side validation submission applies.
</Tip>

Architectural authority: [`bc-operations/docs/agent-ux/dossier-rebuild-design.md`](../../../bc-operations/docs/agent-ux/dossier-rebuild-design.md). The design doc is the spec; this SKILL.md is the operating manual.

## Invocation

Three modes; the caller signals which, or you infer from context:

- **`initial`** — first dossier-relevant beat for this procedure (typically after `bc-document-handler` archives the first document). Build a dossier with placeholders for everything not yet collected, so the user sees the artefact taking shape early.
- **`refresh`** — a new document arrived; update the existing `render.py` and re-run.
- **`final`** — procedure terminal step reached (triggered by `<Skill id="bc-dossier-compilation" />` in the canonical, or defensively by `bc-session-close` Step 0). Produce the version the user files.

Only fire when the parent skill declares `application_dossier` as its artefact class and lists `bc-dossier-compilation` in its `requires`. Otherwise refuse.

## Step 1 — Capability gate

Confirm `python3` is callable and the plugin's vendored module is reachable. If either is missing, degrade per the table and tell the user once:

| Missing | Degraded behaviour |
|---|---|
| `python3` | Emit dossier *markdown only*; walk the user through a browser print-to-PDF path. |
| Vendored `fpdf2` + `pypdf` (plugin install incomplete) | Same as above; ask the user to reinstall the plugin when convenient. |

Don't over-explain — the user wants the dossier, not an apology.

## Step 2 — Reconcile + classify

Read the procedure canonical's `## Required documents` section (cached from `bc-path-traversal` or fetched via `read_skill`). For each row:

1. Look for a matching archived file in `<procedure-root>/documents/`. Match by cert type name first, filename heuristics second, agent judgment third.
2. If found, **classify** into one of six presentation classes per the design doc §3:
   - `id-card` — residence permit, eID, driving licence, orange card (front + back as one half-page row, up to 2 cards/page)
   - `full-page-cert` — birth, marriage, residence-with-history, apostille, BAPA Annexe 3.1, NT2, any single-page issued certificate
   - `multi-page-doc` — Sigedis compte individuel, multi-page certificates, judgement extracts
   - `fee-receipt` — MyMinfin Preuve de paiement, fee proofs
   - `filled-form` — Annexe 1 declaration, official forms the agent fills
3. If not found, mark as `placeholder` with the cert type name + source hint from the canonical (path id or commune-visit instructions).

Classification is agent reasoning, not a deterministic file property. Files arrive arbitrarily named ("scan.pdf", "IMG_2034.jpg"); read the content via `bc-document-handler` to infer the class.

Note for each item whether the canonical's form column is anything other than `Printout acceptable` — those pages get watermarked.

## Step 3 — Write or update `render.py`

Path: `<procedure-root>/dossier/render.py`.

On **initial** mode: create the file with an import header pointing at the live plugin root (resolve at write-time from `CLAUDE_PLUGIN_ROOT` if set, else from your tool environment). Header shape:

```python
# Be Civic dossier renderer. Run: python3 render.py
# Auto-generated — edit freely; the agent will preserve your changes.
import sys
sys.path.insert(0, "<absolute-plugin-root>/vendor")
sys.path.insert(0, "<absolute-plugin-root>/scripts")
# Fallback probe if the plugin path moved (auto-installer relocations, etc.):
try:
    from be_civic_dossier import Dossier, IdCard, FullPageCert, MultiPageDoc, FeeReceipt, FilledForm, Placeholder
except ImportError:
    for probe in ["~/.claude/plugins/be-civic", "~/Library/Application Support/Claude/plugins/be-civic"]:
        sys.path.insert(0, f"{probe}/vendor")
        sys.path.insert(0, f"{probe}/scripts")
        try:
            from be_civic_dossier import Dossier, IdCard, FullPageCert, MultiPageDoc, FeeReceipt, FilledForm, Placeholder
            break
        except ImportError:
            continue
    else:
        raise RuntimeError("Be Civic plugin not found — reinstall via Cowork sidebar.")
```

Then the `Dossier(...)` constructor and `.add(...)` calls per the design doc §5 worked example. Use the user's `profile.json` for `conversation_language`, `applicant_name`, `filing_language`; the procedure canonical for `procedure_title` and `filing_authority` (with commune resolved from profile).

On **refresh** mode: read the existing `render.py`, preserve any user edits (cover note tweaks, item reordering), and update only the item list — replace `Placeholder(...)` lines with the appropriate class instance for the newly-archived document. Do not rewrite the whole file.

If the plugin path block fails to import on a later run (plugin moved), regenerate the import header.

## Step 4 — Officer notes

On **final** mode (and optionally on refresh), author `<procedure-root>/dossier/officer-notes.md` — short prose explaining the routing call: applicable statute (e.g. art. 12bis §1, 2°), eligibility math (years of legal residence, integration evidence, etc.), any commune-specific notes worth surfacing. The agent writes this; `render.py` reads it.

Keep it to under 250 words. Officer reads it once at intake.

## Step 5 — Run `render.py`

Execute via the workspace bash. Output: `<procedure-root>/dossier/dossier-<YYYY-MM-DD>.pdf`.

The script's deterministic body handles cover, checklist, dividers, originals-callout, each per-class layout, watermarks (in the user's `conversation_language` on every page where form ≠ Printout acceptable), and concatenation. Branding (Be Civic header / ribbon / footer) appears **only on pages we generate** — cover, checklist, dividers, placeholders, filled forms, officer notes. User documents pass through untouched.

If the script errors, surface the error to the user plainly, fix the proximate cause (missing file, malformed image, bad path), and re-run. Don't hide the failure.

## Step 6 — Present + iterate

Show the user the rendered PDF and the placeholder count. Plain summary:

> *"Your dossier is at `dossier-2026-05-19.pdf` — 8 pages: cover, checklist, your birth certificate, residence certificate, L card, BAPA attestation, fee receipt, and a placeholder for the Annexe 1 you'll sign at the commune."*

If placeholders remain, list them briefly and offer the relevant next-step path (e.g. *"Drop the BAPA attestation PDF here when you have it and I'll fold it in."*). The user typically responds with a new document; that triggers `refresh` mode (Step 3 update + Step 5 re-run).

## Step 7 — Final handoff

On **final** mode after the last placeholder is filled (or the user explicitly accepts a dossier with remaining placeholders for commune-visit completion), close with:

- The originals reminder: enumerate the documents where the watermark indicates "ORIGINAL REQUIRED" — *"You'll need to bring these in original: birth certificate (apostilled), L card, BAPA attestation. The printed dossier is for reference; the originals are what the commune accepts."*
- The re-run instruction: *"You can re-run `python3 render.py` from your `dossier/` folder any time you update a document — the script is yours to edit too."*

Exit cleanly. Validation submission is not this skill's concern (per the `<Tip>` above).

## Failure modes

- **Vendored library import fails at runtime** — the probe fallback in the import header catches plugin relocations; if all probes fail, the script raises a clear "reinstall plugin" message. Don't silently degrade.
- **Image rotation wrong on an ID card** — re-prompt the user for a head-on scan; the renderer doesn't OCR or auto-rotate.
- **Watermark unreadable on a dark scanned document** — known limitation of 25%-opacity overlay; user can manually highlight the warning if needed. Surface as a known limitation if the user asks.
- **render.py byte-determinism** — `fpdf2` stamps `/CreationDate` and `/ModDate` from wall-clock by default; the vendored module stubs these to a fixed sentinel so re-runs produce byte-identical PDFs. If you see drift, check the module's metadata stub.

## What this skill does NOT own

- The procedure body (eligibility math, branching, statute references) — lives in the parent canonical.
- Document validation / authenticity checks — the parent canonical's concern.
- Document archiving (`documents/<procedure-id>/`) — `bc-document-handler` owns this; we only read.
- Validation submission — agent-tooling sub-skill, no validation fires here.

## References

- Architectural design: `bc-operations/docs/agent-ux/dossier-rebuild-design.md`
- Spec: `bc-operations/specs/cowork-plugin.md` §2.3 (bc-dossier-compilation paragraph)
- Renderer module: `${CLAUDE_PLUGIN_ROOT}/scripts/be_civic_dossier/`
- Templates: `${CLAUDE_PLUGIN_ROOT}/skills/bc-dossier-compilation/templates/`
- Vendored libs + fonts: `${CLAUDE_PLUGIN_ROOT}/vendor/`
