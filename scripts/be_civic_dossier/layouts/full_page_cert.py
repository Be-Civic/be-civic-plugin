"""be_civic_dossier.layouts.full_page_cert — single-page issued certificate.

Layout: one user-supplied PDF page per A4 dossier page, fit-to-page,
auto-rotated to readable orientation. **No Be Civic branding overlaid**
— the document passes through as the issuing authority produced it
(design doc §3 branding discipline).

If the input PDF has multiple pages we still emit one page per source
page; the class name is a hint about the dossier slot, not a hard cap.

Stream A — owned by the W25.1a dossier-rebuild work.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FullPageCert:
    """Item-class for a single-page issued certificate.

    Used for: birth certificates, marriage certificates, residence-with-history,
    apostille endorsements, BAPA Annexe 3.1, NT2 certificate, and similar
    one-page-per-document issued certificates.

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

    # class label used by the dossier renderer for dispatch
    layout_class: str = "full-page-cert"

    def load_pdf_bytes(self, base_dir: Optional[Path] = None) -> Optional[bytes]:
        """Read the source PDF and return its bytes.

        Returns ``None`` if the file doesn't exist — callers (the Dossier
        container) substitute a Placeholder in that case (design doc §8
        "Behaviour on missing files").
        """
        path = _resolve_path(self.file_path, base_dir)
        if not path.is_file():
            return None
        return path.read_bytes()

    def auto_rotate(self, pdf_bytes: bytes) -> bytes:
        """Rotate each page to the closest 90° increment so it reads upright.

        This is a best-effort heuristic: if the page is in landscape on an
        A4 portrait dossier, we don't rotate (the user printed/scanned the
        cert that way intentionally). If pypdf can detect a rotation
        annotation, we honour it.
        """
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            existing = int(page.get("/Rotate", 0) or 0) % 360
            if existing:
                # normalise to 0° by applying the rotation
                page.rotate(-existing)
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()


def _resolve_path(file_path: str, base_dir: Optional[Path]) -> Path:
    """Resolve ``file_path`` against ``base_dir`` if relative."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    if base_dir is None:
        return p.resolve()
    return (base_dir / p).resolve()
