"""be_civic_dossier.renderer — compat shim re-exporting Dossier.

The canonical home of the Dossier container is :mod:`be_civic_dossier.dossier`.
This module exists so :mod:`be_civic_dossier.__init__` can ``from .renderer
import Dossier``.
"""

from __future__ import annotations

from .dossier import Dossier

__all__ = ("Dossier",)
