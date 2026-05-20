"""be_civic_dossier.renderer — compat shim re-exporting Dossier.

The canonical home of the Dossier container is :mod:`be_civic_dossier.dossier`.
This module exists so :mod:`be_civic_dossier.__init__` can ``from .renderer
import Dossier`` and keep Stream B's coordination contract intact.

Stream A — owned by the W25.1a dossier-rebuild work.
"""

from __future__ import annotations

from .dossier import Dossier

__all__ = ("Dossier",)
