"""be_civic_dossier.layouts.multi_page_doc — multi-page user document.

Layout: preserve all original pages exactly as-is, in order. No Be Civic
header or footer overlaid.

Used for: Sigedis compte individuel (commonly 6+ pages), multi-page
certificates, judgement extracts, anything where the user uploads a single
multi-page PDF and the receiving officer reads it pages 1-to-N.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class MultiPageDoc:
    """Item-class for a multi-page user document.

    :param file_path: path to a PDF on disk. Relative paths are resolved
        against the directory containing ``render.py``.
    :param cert_type: human-readable name; goes on the divider page and the
        checklist. Not stamped onto the document itself.
    :param original_required: True if the procedure canonical marks this row
        Form != "Printout acceptable". The dossier renderer adds the
        diagonal watermark to every page.
    """

    file_path: str
    cert_type: str
    original_required: bool

    layout_class: str = "multi-page-doc"

    def load_pdf_bytes(self, base_dir: Optional[Path] = None) -> Optional[bytes]:
        path = _resolve_path(self.file_path, base_dir)
        if not path.is_file():
            return None
        return path.read_bytes()


def _resolve_path(file_path: str, base_dir: Optional[Path]) -> Path:
    p = Path(file_path)
    if p.is_absolute():
        return p
    if base_dir is None:
        return p.resolve()
    return (base_dir / p).resolve()
