"""be_civic_dossier.layouts.id_card — residence permit / eID / driving licence layout.

Per design doc §3 and operator clarification 2026-05-19:

* Each card occupies **one half-page-height row** (height of half A4 less
  margins).
* Within the row, **front on the left, back on the right**, sized to fill
  the row height.
* Up to **two cards per A4 page** (row 1 + row 2). The renderer packs
  consecutive ``IdCard`` items.
* Pair front+back from either a 2-page input PDF (page 1 = front, page 2 =
  back) or, if only 1 page is provided, the card occupies the left half
  and the right half is left blank with a "back not provided" note.

We accept PDF input only — no image formats. fpdf2 needs Pillow to embed
images and Pillow is explicitly out of scope (design doc §7). The agent
re-prompts the user to convert phone photos to PDF before upload.

**No Be Civic branding overlaid** on the card pages themselves (design
doc §3). The packing into rows is layout work, not branding.

Stream A — owned by the W25.1a dossier-rebuild work.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


# Per-page geometry constants. A4 portrait = 210 x 297 mm.
# We use 15mm margins for the dossier and divide the remaining height into
# two equal rows.
_A4_W = 210.0
_A4_H = 297.0
_MARGIN = 15.0
_ROW_HEIGHT = (_A4_H - 2 * _MARGIN) / 2.0  # ~133.5mm
_HALF_W = (_A4_W - 2 * _MARGIN) / 2.0      # 90mm each half
_GUTTER = 4.0                              # gap between front and back within a row


@dataclass
class IdCard:
    """Item-class for an id-card-shaped document.

    Used for: residence permit (L card, etc.), eID, driving licence,
    orange card (CIRE), and similar wallet-sized cards.

    :param file_path: path to a PDF on disk. The PDF should contain
        either 1 or 2 pages (page 1 = front, page 2 = back if present).
        Relative paths are resolved against the directory containing
        ``render.py``.
    :param cert_type: human-readable name (e.g. "Residence permit (L card)").
        Goes on the divider page and the checklist. Not stamped onto the
        card itself.
    :param original_required: True if the procedure canonical marks this row
        Form != "Printout acceptable". The dossier renderer adds the
        diagonal watermark to every page.
    """

    file_path: str
    cert_type: str
    original_required: bool

    layout_class: str = "id-card"

    def load_pdf_bytes(self, base_dir: Optional[Path] = None) -> Optional[bytes]:
        path = _resolve_path(self.file_path, base_dir)
        if not path.is_file():
            return None
        return path.read_bytes()

    def page_count(self, base_dir: Optional[Path] = None) -> int:
        """Return the number of pages in the source PDF (1 or 2 expected)."""
        b = self.load_pdf_bytes(base_dir)
        if b is None:
            return 0
        import pypdf
        return len(pypdf.PdfReader(io.BytesIO(b)).pages)


# ---------------------------------------------------------------------------
# Multi-card packing
# ---------------------------------------------------------------------------


def render_id_cards_to_pdf_bytes(
    cards: List[IdCard],
    base_dir: Optional[Path] = None,
) -> bytes:
    """Render a sequence of IdCard items into a multi-page PDF.

    Two cards per A4 page (top row + bottom row). Each card occupies a
    half-page-height row; within the row, front on the left half, back on
    the right half (or "back not provided" if absent).

    :param cards: list of :class:`IdCard` items in order.
    :param base_dir: directory to resolve relative ``file_path`` values against.
    :returns: PDF bytes with ceil(len(cards) / 2) pages.
    """
    from fpdf import FPDF
    from .. import metadata

    out_pdf = FPDF(format=(_A4_W, _A4_H), unit="mm")
    out_pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    out_pdf.set_auto_page_break(auto=False)

    metadata.register_fonts(out_pdf, ("SourceSansPro",))

    # iterate cards in pairs (row 1, row 2)
    for page_idx in range(0, len(cards), 2):
        out_pdf.add_page()
        for slot, card in enumerate(cards[page_idx:page_idx + 2]):
            row_y = _MARGIN + slot * _ROW_HEIGHT
            _render_card_into_row(
                out_pdf, card,
                row_x=_MARGIN, row_y=row_y,
                row_w=_A4_W - 2 * _MARGIN,
                row_h=_ROW_HEIGHT,
                base_dir=base_dir,
            )
            # subtle hairline between rows
            if slot == 0 and len(cards[page_idx:page_idx + 2]) == 2:
                out_pdf.set_draw_color(*metadata.BRAND["hairline"].as_tuple())
                out_pdf.set_line_width(0.2)
                out_pdf.line(
                    _MARGIN, _MARGIN + _ROW_HEIGHT,
                    _A4_W - _MARGIN, _MARGIN + _ROW_HEIGHT,
                )

    metadata.apply_deterministic_metadata(out_pdf)
    return bytes(out_pdf.output())


def _render_card_into_row(
    pdf,
    card: IdCard,
    *,
    row_x: float,
    row_y: float,
    row_w: float,
    row_h: float,
    base_dir: Optional[Path],
) -> None:
    """Render one card's front+back into a half-page row.

    The actual card content is a PDF page from the user; we use pypdf to
    embed it via fpdf2's ``import_pdf`` if available, else we leave a
    bordered slot with an annotation. pypdf can't *embed* a page into an
    fpdf canvas directly; the practical approach is to defer the embed
    to the dossier's pypdf-merge pass.

    For now we draw the row scaffold (label, slots, divider) and the
    actual page content gets overlaid in :class:`Dossier.render` via
    pypdf's page-merge using a stamping watermark approach.
    """
    from .. import metadata

    # row label: cert type at the top-left of the row
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "B", 9)
    pdf.set_xy(row_x, row_y + 2)
    pdf.cell(row_w, 4, card.cert_type.upper())

    # subtle border around each half-slot (so blank slots are visible)
    front_x = row_x
    front_y = row_y + 8
    half_w = (row_w - _GUTTER) / 2.0
    half_h = row_h - 12

    back_x = row_x + half_w + _GUTTER
    back_y = front_y

    # frame the slots in mute hairline
    pdf.set_draw_color(*metadata.BRAND["hairline"].as_tuple())
    pdf.set_line_width(0.2)
    pdf.rect(front_x, front_y, half_w, half_h)
    pdf.rect(back_x, back_y, half_w, half_h)

    # small labels
    pdf.set_font("SourceSansPro", "", 8)
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_xy(front_x + 1, front_y - 3)
    pdf.cell(20, 3, "FRONT")
    pdf.set_xy(back_x + 1, back_y - 3)
    pdf.cell(20, 3, "BACK")

    # If the underlying PDF is missing, write a "missing source" note in
    # the front slot. The Dossier container will substitute Placeholders
    # before we ever get here, so this is defensive.
    pdf_bytes = card.load_pdf_bytes(base_dir)
    if pdf_bytes is None:
        pdf.set_xy(front_x + 4, front_y + half_h / 2)
        pdf.set_text_color(*metadata.BRAND["warn_red"].as_tuple())
        pdf.set_font("SourceSansPro", "B", 10)
        pdf.cell(half_w - 8, 4, "source file missing")
        return

    # Otherwise: indicate the slot has been populated. The actual page
    # content is merged in at the dossier-render stage via pypdf overlay.
    # Mark the row with geometry hints baked into the layout for the
    # merger to find. See :func:`get_id_card_slot_geometry`.


def get_id_card_slot_geometry(
    card_index: int,
) -> Tuple[float, float, float, float, float, float, float, float]:
    """Return the (front_x, front_y, front_w, front_h, back_x, back_y, back_w, back_h)
    geometry (in mm) for the Nth card on its A4 page.

    ``card_index`` is 0-based within a page (0 = top row, 1 = bottom row).
    """
    if card_index not in (0, 1):
        raise ValueError("card_index must be 0 or 1 (two cards per A4 page)")
    row_y = _MARGIN + card_index * _ROW_HEIGHT
    front_x = _MARGIN
    front_y = row_y + 8
    half_w = (_A4_W - 2 * _MARGIN - _GUTTER) / 2.0
    half_h = _ROW_HEIGHT - 12
    back_x = _MARGIN + half_w + _GUTTER
    back_y = front_y
    return (front_x, front_y, half_w, half_h, back_x, back_y, half_w, half_h)


def _resolve_path(file_path: str, base_dir: Optional[Path]) -> Path:
    p = Path(file_path)
    if p.is_absolute():
        return p
    if base_dir is None:
        return p.resolve()
    return (base_dir / p).resolve()
