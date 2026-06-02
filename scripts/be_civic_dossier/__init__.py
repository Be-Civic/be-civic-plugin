"""be_civic_dossier — Be Civic dossier renderer package.

The renderer is split across two areas:

* The Dossier / IdCard / FullPageCert / MultiPageDoc / FeeReceipt / FilledForm
  / Placeholder classes plus the watermark module live in sibling files inside
  this package.
* The HTML templates live at
  ``../../skills/bc-dossier-compilation/templates/`` and the codegen module
  (``codegen.py``) writes ``render.py`` into the user's project folder.

This ``__init__`` re-exports the public surface from both areas. If the
renderer classes aren't installed yet (partial install or running codegen tests
in isolation), the imports below degrade to ``None`` so the codegen path stays
usable — only end-to-end rendering will fail.

Public surface used by user-side ``render.py``::

    from be_civic_dossier import (
        Dossier, IdCard, FullPageCert, MultiPageDoc,
        FeeReceipt, FilledForm, Placeholder,
    )
"""

from __future__ import annotations

# Codegen is always available — it has no external dependencies.
from .codegen import (
    DossierConfig,
    ITEMS_BEGIN,
    ITEMS_END,
    ParsedItem,
    TEMPLATE_FILENAMES,
    bundled_templates_dir,
    load_template,
    parse_existing_items,
    plugin_root,
    refresh_items,
    render_render_py,
    resolve_template,
)

# Renderer classes — imported defensively. If a sibling module is missing
# during a partial install, the name binds to ``None`` so downstream
# introspection sees a clear "not yet wired" signal.
try:  # pragma: no cover - exercised by integration tests, not unit tests
    from .renderer import Dossier  # type: ignore[attr-defined]
except ImportError:
    Dossier = None  # type: ignore[assignment]

try:  # pragma: no cover
    from .layouts import (  # type: ignore[attr-defined]
        FeeReceipt,
        FilledForm,
        FullPageCert,
        IdCard,
        MultiPageDoc,
        Placeholder,
    )
except ImportError:
    IdCard = None  # type: ignore[assignment]
    FullPageCert = None  # type: ignore[assignment]
    MultiPageDoc = None  # type: ignore[assignment]
    FeeReceipt = None  # type: ignore[assignment]
    FilledForm = None  # type: ignore[assignment]
    Placeholder = None  # type: ignore[assignment]


__all__ = (
    # Renderer surface.
    "Dossier",
    "IdCard",
    "FullPageCert",
    "MultiPageDoc",
    "FeeReceipt",
    "FilledForm",
    "Placeholder",
    # Codegen surface.
    "DossierConfig",
    "ITEMS_BEGIN",
    "ITEMS_END",
    "ParsedItem",
    "TEMPLATE_FILENAMES",
    "bundled_templates_dir",
    "load_template",
    "parse_existing_items",
    "plugin_root",
    "refresh_items",
    "render_render_py",
    "resolve_template",
)
