"""be_civic_dossier.watermark — diagonal warning watermark overlay.

The watermark is applied to every page of items where the user-facing
"original required" form discipline holds (i.e. Form != "Printout acceptable").
It is a warning, not branding.

Two flavours:

* **ORIGINAL_REQUIRED** — applied to user documents (id-card, full-page-cert,
  multi-page-doc, fee-receipt) where the procedure marks the row as anything
  other than "Printout acceptable".
* **SIGN_BEFORE_FILING** — applied to filled-form pages we generate that the
  user must sign before depositing at the commune.

Both render the same way: 45° diagonal, repeating, muted red-orange
(#c0392b at ~25% opacity), font sized at ~12% of page width. The text varies
by ``conversation_language`` so the warning serves the user, not the receiving
officer.

Architecture: we build a single-page watermark PDF via fpdf2 (one for each
text variant), then use pypdf to layer it on top of each page of the target
PDF. pypdf's ``Page.merge_page`` does the overlay; it preserves the original
page content underneath.
"""

from __future__ import annotations

import io
import math
from typing import Mapping

from . import metadata


# ---------------------------------------------------------------------------
# Localised watermark text
# ---------------------------------------------------------------------------

#: Original-required text per conversation language.
WATERMARK_ORIGINAL_REQUIRED: Mapping[str, str] = {
    "en": "ORIGINAL REQUIRED — DO NOT FILE PRINTOUT",
    "fr": "ORIGINAL REQUIS — NE PAS DEPOSER L'IMPRESSION",
    "nl": "ORIGINEEL VEREIST — DRUK NIET INDIENEN",
    "de": "ORIGINAL ERFORDERLICH — DRUCK NICHT EINREICHEN",
    "ar": "يلزم تقديم الأصل - لا تُودِع نسخة مطبوعة",
    "uk": "ПОТРІБЕН ОРИГІНАЛ — НЕ ПОДАВАЙТЕ РОЗДРУКІВКУ",
}

#: Sign-before-filing text per conversation language. Same six locales.
WATERMARK_SIGN_BEFORE_FILING: Mapping[str, str] = {
    "en": "SIGN BEFORE FILING",
    "fr": "À SIGNER AVANT DÉPÔT",
    "nl": "TE ONDERTEKENEN VÓÓR INDIENING",
    "de": "VOR EINREICHUNG UNTERSCHREIBEN",
    "ar": "وقّع قبل الإيداع",
    "uk": "ПІДПИШІТЬ ПЕРЕД ПОДАННЯМ",
}


def _watermark_text(kind: str, conversation_language: str) -> str:
    """Resolve watermark text for a given (kind, language) pair.

    Falls back to English if the language is unknown.
    """
    table = (
        WATERMARK_ORIGINAL_REQUIRED if kind == "original_required"
        else WATERMARK_SIGN_BEFORE_FILING
    )
    return table.get((conversation_language or "en").lower(), table["en"])


# ---------------------------------------------------------------------------
# Watermark page builder
# ---------------------------------------------------------------------------


def build_watermark_pdf(
    kind: str,
    conversation_language: str,
    *,
    page_width_mm: float = 210.0,
    page_height_mm: float = 297.0,
) -> bytes:
    """Build a single-page PDF containing the diagonal watermark.

    :param kind: ``"original_required"`` or ``"sign_before_filing"``.
    :param conversation_language: 2-letter code per profile.json.
    :param page_width_mm: page width in mm. Default A4 portrait.
    :param page_height_mm: page height in mm.
    :returns: raw PDF bytes, one page, transparent background, watermark text
        in muted red at 45° tiled across the page.

    The result is deterministic for a given (kind, language, size) tuple.
    """
    text = _watermark_text(kind, conversation_language)
    return _build_watermark_pdf_inner(text, page_width_mm, page_height_mm, conversation_language)


def _build_watermark_pdf_inner(
    text: str,
    page_w: float,
    page_h: float,
    conversation_language: str,
) -> bytes:
    from fpdf import FPDF

    # fpdf2's FPDF expects mm by default; matches the page size we pass.
    pdf = FPDF(format=(page_w, page_h), unit="mm")
    # No margin — the watermark fills edge-to-edge.
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # Register the font family appropriate for the script. For Arabic and
    # Ukrainian we need the corresponding Noto family. For the Latin
    # locales (en/fr/nl/de) Source Sans Pro is fine — has the accented
    # characters we need.
    family = metadata.font_for_language(conversation_language)
    metadata.register_fonts(pdf, (family,))

    # Font size: roughly 12% of page width, in points. fpdf2 set_font expects pt.
    # 1 mm = 2.83465 pt
    font_size_pt = (page_w * 0.05) * 2.83465  # ~5% of page width feels right
    # cap to a sane range so absurd page sizes don't break things
    font_size_pt = max(18.0, min(font_size_pt, 60.0))

    # Watermark color: muted red-orange at 25% via opacity.
    pdf.set_text_color(*metadata.BRAND["warn_red"].as_tuple())
    pdf.set_font(family, "B", font_size_pt)

    # Rotation around the page centre.
    # fpdf2's transform context manager handles rotation + translation cleanly.
    cx, cy = page_w / 2.0, page_h / 2.0

    # Compose tile geometry. We want repeating diagonal text spanning the
    # whole page. The simplest reliable approach: rotate the entire canvas
    # 45°, then lay down N horizontal text rows in the rotated frame, sized
    # so they cover the page diagonal.
    diagonal = math.hypot(page_w, page_h)
    # text width estimate: fpdf2 has get_string_width but we set font first.
    text_width_mm = pdf.get_string_width(text)
    # If the text is wider than the diagonal, we'd clip — use a smaller font.
    if text_width_mm > diagonal * 1.4:
        # scale down proportionally
        new_size = font_size_pt * (diagonal * 1.4 / text_width_mm)
        pdf.set_font(family, "B", max(14.0, new_size))
        text_width_mm = pdf.get_string_width(text)

    # Row height — generous spacing so the watermark reads as a band, not a wall.
    row_height_mm = font_size_pt * 0.4233 * 2.5  # font_size_pt -> mm * spacing factor

    # Apply 25% opacity globally via GraphicsState (fpdf2 supports it).
    with pdf.local_context(fill_opacity=0.25, stroke_opacity=0.25):
        # set_text_color again inside context just to be defensive.
        pdf.set_text_color(*metadata.BRAND["warn_red"].as_tuple())
        # rotate around page centre
        with pdf.rotation(angle=45, x=cx, y=cy):
            # In the rotated frame, lay down rows. Range chosen to cover the
            # rotated bounding box (~ page diagonal).
            n_rows = int(diagonal / row_height_mm) + 2
            # vertical offset starts well above the page so the top-left corner
            # is filled after rotation.
            start_y = cy - (n_rows / 2.0) * row_height_mm
            for i in range(n_rows):
                y = start_y + i * row_height_mm
                # Text x position: centre horizontally in the rotated frame.
                x = cx - text_width_mm / 2.0
                pdf.set_xy(x, y)
                pdf.cell(w=text_width_mm, h=row_height_mm, text=text, align="C")

    metadata.apply_deterministic_metadata(pdf)
    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Watermark application (overlay via pypdf)
# ---------------------------------------------------------------------------


def apply_watermark_to_pdf(
    base_pdf_bytes: bytes,
    kind: str,
    conversation_language: str,
) -> bytes:
    """Overlay the watermark on every page of ``base_pdf_bytes``.

    :param base_pdf_bytes: the input PDF (one or many pages).
    :param kind: ``"original_required"`` or ``"sign_before_filing"``.
    :param conversation_language: ISO 639-1 two-letter code.
    :returns: a new PDF with the watermark layered on every page. Input
        bytes are not mutated.

    The watermark page is built once at the dimensions of each input page
    (handling mixed-size documents — rare but possible for scanned uploads).
    """
    import pypdf  # vendored on sys.path

    reader = pypdf.PdfReader(io.BytesIO(base_pdf_bytes))
    writer = pypdf.PdfWriter()

    # cache watermark page by (page_width, page_height) so a multi-page doc
    # with uniform geometry only builds the watermark once.
    cache: dict[tuple[float, float], pypdf.PageObject] = {}

    for page in reader.pages:
        # pypdf reports MediaBox in user units (points by default).
        mbox = page.mediabox
        w_pt = float(mbox.width)
        h_pt = float(mbox.height)
        # convert pt -> mm (1 pt = 0.3528 mm; or 1 mm = 2.83465 pt)
        w_mm = w_pt / 2.83465
        h_mm = h_pt / 2.83465
        key = (round(w_mm, 2), round(h_mm, 2))
        if key not in cache:
            wm_bytes = build_watermark_pdf(
                kind, conversation_language,
                page_width_mm=w_mm, page_height_mm=h_mm,
            )
            wm_reader = pypdf.PdfReader(io.BytesIO(wm_bytes))
            cache[key] = wm_reader.pages[0]
        page.merge_page(cache[key])
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
