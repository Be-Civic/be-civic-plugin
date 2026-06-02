"""be_civic_dossier.layouts.fee_receipt — federal/communal fee receipt.

Layout: fit-to-page, pass through as-is. Identical handling to
``full-page-cert`` from a rendering perspective; kept distinct so the
checklist can label the row meaningfully ("Federal fee receipt — €150,
2026-04-20") and the agent can record the payment_date separately.

No Be Civic branding overlaid.

Used for: MyMinfin Preuve de paiement, federal fee receipts, communal
fee receipts, payment confirmations from bank apps that the user prints.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FeeReceipt:
    """Item-class for a payment / receipt document.

    :param file_path: path to a PDF on disk. Relative paths are resolved
        against the directory containing ``render.py``.
    :param cert_type: human-readable name.
    :param original_required: usually False (fee receipts are routinely
        accepted as printouts), but kept on the class for parity. The
        dossier renderer respects whatever value is passed.
    :param payment_date: optional ISO date string. Not used in the rendered
        page itself; surfaced via the checklist row "source" column when
        present.
    """

    file_path: str
    cert_type: str
    original_required: bool = False
    payment_date: Optional[str] = None

    layout_class: str = "fee-receipt"

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
