# Be Civic dossier templates

Jinja2-style HTML templates consumed by `be_civic_dossier` (Stream A's Python
module) and by the `render.py` codegen flow described in `../RENDER_PY_CODEGEN.md`.

| Template | Purpose | Pages | Branding |
|---|---|---|---|
| `cover.html` | First page of every dossier — flag stripe, wordmark, applicant, procedure, filing authority, date. | 1 | Yes |
| `checklist.html` | Filing-order table of every dossier item + "bring originals" callout. | 1–2 | Yes |
| `divider.html` | Section divider inserted before each major item; carries cert type + class. | 1 per item | Yes |
| `placeholder.html` | Single page substituted when a checklist item hasn't been collected yet. | 1 per missing item | Yes |
| `filled-form-annexe-1.html` | Belgian Annexe 1 (Déclaration de nationalité, art. 12bis) form layout with fillable fields. | 1–2 | Yes — and "SIGN BEFORE FILING" watermark is layered on at render. |
| `officer-notes.html` | Wrapper for MD→HTML officer-notes prose, with applicant/authority context block. | 1+ (notes-body-driven) | Yes |

## Branding discipline

These templates are **Be-Civic-generated pages only**. User-uploaded documents
(`id-card`, `full-page-cert`, `multi-page-doc`, `fee-receipt`) pass through without
Be Civic header/footer — see design doc §3 "branding discipline" for the reason.
The watermark on original-required pages is the one exception and is applied by
`be_civic_dossier.watermark`, not by these templates.

## Placeholders

All placeholders use Jinja2 syntax (`{{ var }}`, `{% if %}`, `{% for %}`). Header
comments in each file list the variables that template expects. The
`be_civic_dossier.codegen` module (Stream A) is the canonical caller; see
`../RENDER_PY_CODEGEN.md` for how `render.py` wires user data through to these
templates.

## Fonts

The `@font-face` rules reference fonts that Stream A bundles under
`be-civic-plugin/vendor/fonts/`:

- `Inter-Regular.ttf`, `Inter-Bold.ttf` — display / headers
- `SourceSansPro-Regular.ttf`, `SourceSansPro-Bold.ttf` — body
- Noto Sans Arabic (for `conversation_language: ar`) is loaded by the renderer
  conditionally, not by the templates directly.

The paths are written relative to the templates folder (`../vendor/fonts/...`)
so the same templates work whether the dossier renders in-place from the plugin
or from a copy in the user's project folder, as long as the renderer resolves
the relative URLs against the template's directory.

## Editing

These templates ship inside the plugin. Treat them as code, not as user-editable
artefacts. If you need a project-specific variation, copy the template into the
user's `<procedure-id>/dossier/templates/` folder; `render.py` will prefer a
local copy if one exists (see `be_civic_dossier.codegen.resolve_template`).
