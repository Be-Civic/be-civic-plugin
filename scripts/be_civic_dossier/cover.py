"""be_civic_dossier.cover — dossier cover page.

Renders the first page of every dossier: flag stripe (black/gold/red),
wordmark, procedure title + subtitle, applicant block, metadata grid,
footer band.

Visual reference: ``skills/bc-dossier-compilation/templates/cover.html``
(Stream B). This file implements the same layout via fpdf2 primitives so
the output is deterministic and works without a system HTML/CSS rendering
toolchain (no weasyprint, no cairo).

Branding: this is a Be-Civic-generated page, so the full brand identity
applies. See design doc §3 branding discipline.

Stream A — owned by the W25.1a dossier-rebuild work.
"""

from __future__ import annotations

from . import metadata


def add_cover_page(
    pdf,
    *,
    applicant_name: str,
    procedure_title: str,
    procedure_id: str,
    filing_authority: str,
    filing_date: str,
    generated_date: str = "",
    skill_version: str = "",
    skill_status: str = "",
) -> None:
    """Append a cover page to ``pdf`` (an ``fpdf.FPDF`` instance).

    Assumes fonts are already registered via :func:`metadata.register_fonts`.

    All parameters are simple strings; the cover does no semantic
    interpretation. The caller (the ``Dossier`` container) is responsible for
    formatting dates and selecting display variants.

    Auto page-break is disabled on the cover so the absolutely-positioned
    footer doesn't trigger an unwanted second page.
    """
    prev_auto = pdf.auto_page_break
    prev_bmargin = pdf.b_margin
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    # Page geometry: A4 portrait by convention. We use mm units throughout.
    page_w = pdf.w
    page_h = pdf.h

    # ---- top flag stripe (8mm tall, full width, no margin above)
    _draw_flag_stripe(pdf, x=0, y=0, width=page_w, height=8)

    # margin below the stripe before the wordmark begins
    pdf.set_y(8 + 12)

    # ---- wordmark row
    _draw_wordmark(pdf, x=15, y=pdf.get_y())

    # ---- procedure block
    pdf.set_xy(15, pdf.get_y() + 22)
    _draw_procedure_block(pdf, procedure_title=procedure_title)

    # ---- applicant block (gold left-bar)
    _draw_applicant_block(pdf, x=15, y=pdf.get_y() + 18, name=applicant_name)

    # ---- metadata grid
    _draw_meta_grid(
        pdf,
        x=15,
        y=pdf.get_y() + 8,
        rows=[
            ("Procedure ID", procedure_id),
            ("Filing authority", filing_authority),
            ("Filing date", filing_date),
        ] + (
            [("Skill version", f"{skill_version} ({skill_status})")]
            if skill_version else []
        ),
    )

    # ---- footer band (positioned absolutely near bottom)
    _draw_cover_footer(pdf, page_w=page_w, page_h=page_h, generated_date=generated_date)

    # restore previous auto-page-break setting
    pdf.set_auto_page_break(auto=prev_auto, margin=prev_bmargin)


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _draw_flag_stripe(pdf, *, x: float, y: float, width: float, height: float) -> None:
    """Draw the black/gold/red triple stripe."""
    third = width / 3.0
    colors = ["black", "gold", "red"]
    for i, key in enumerate(colors):
        pdf.set_fill_color(*metadata.BRAND[key].as_tuple())
        pdf.rect(x + i * third, y, third, height, style="F")


def _draw_wordmark(pdf, *, x: float, y: float) -> None:
    """Draw the Be Civic wordmark — a 16mm gold square logo + the words 'Be Civic'.

    The HTML template has a black square with content (an empty placeholder
    until logo art is supplied). We mirror by drawing a black-filled rounded
    square and the wordmark text beside it.
    """
    logo_size = 16
    pdf.set_fill_color(*metadata.BRAND["black"].as_tuple())
    # fpdf2 has rounded-rect support via .round_corners=True or via low-level path.
    # Use a plain square for simplicity; visually close enough at print scale.
    pdf.rect(x, y, logo_size, logo_size, style="F")

    # Wordmark text
    pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_font("Inter", "B", 22)
    pdf.set_xy(x + logo_size + 6, y + 2.5)
    pdf.cell(60, 9, "Be Civic")

    # Tagline beneath
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 9)
    pdf.set_xy(x + logo_size + 6, y + 10)
    pdf.cell(80, 5, "DOSSIER FOR THE BELGIAN ADMINISTRATION")

    pdf.set_y(y + logo_size)


def _draw_procedure_block(pdf, *, procedure_title: str) -> None:
    """Big procedure title + subtitle."""
    pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_font("Inter", "B", 22)
    # Use multi_cell so long titles wrap. width = page minus left+right margin.
    available = pdf.w - 15 - 15
    pdf.multi_cell(available, 9, procedure_title, align="L")

    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 12)
    pdf.set_xy(15, pdf.get_y() + 3)
    pdf.cell(available, 6, "Single bound dossier — filing version")


def _draw_applicant_block(pdf, *, x: float, y: float, name: str) -> None:
    """Gold left-bar block with 'APPLICANT' label + big name."""
    # gold bar
    pdf.set_fill_color(*metadata.BRAND["gold"].as_tuple())
    pdf.rect(x, y, 3, 18, style="F")

    # label
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 9)
    pdf.set_xy(x + 6, y + 2)
    pdf.cell(80, 4, "APPLICANT")

    # name
    pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_font("Inter", "B", 16)
    pdf.set_xy(x + 6, y + 7)
    available = pdf.w - (x + 6) - 15
    pdf.cell(available, 9, name)

    pdf.set_y(y + 18)


def _draw_meta_grid(pdf, *, x: float, y: float, rows: list) -> None:
    """2-column table: label (uppercase mute) | value (ink, semibold)."""
    label_col_w = 42
    value_col_w = pdf.w - x - 15 - label_col_w

    pdf.set_y(y)
    pdf.set_x(x)

    # top double rule
    pdf.set_draw_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_line_width(0.4)
    pdf.line(x, y, x + label_col_w + value_col_w, y)
    pdf.set_y(y + 1)

    for i, (label, value) in enumerate(rows):
        row_y = pdf.get_y()
        pdf.set_x(x)

        pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
        pdf.set_font("SourceSansPro", "", 9)
        pdf.cell(label_col_w, 7, label.upper())

        pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
        pdf.set_font("SourceSansPro", "B", 11)
        pdf.cell(value_col_w, 7, value)
        pdf.ln(7)

        # hairline between rows (except after the last)
        if i < len(rows) - 1:
            pdf.set_draw_color(*metadata.BRAND["hairline"].as_tuple())
            pdf.set_line_width(0.2)
            pdf.line(x, pdf.get_y(), x + label_col_w + value_col_w, pdf.get_y())

    # bottom double rule
    pdf.set_draw_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_line_width(0.4)
    pdf.line(x, pdf.get_y(), x + label_col_w + value_col_w, pdf.get_y())


def _draw_cover_footer(pdf, *, page_w: float, page_h: float, generated_date: str) -> None:
    """Footer band near bottom of cover page."""
    # We use a fixed Y near the bottom margin (1.5cm = 15mm)
    footer_y = page_h - 20
    pdf.set_xy(15, footer_y)

    # thin rule
    pdf.set_draw_color(*metadata.BRAND["hairline"].as_tuple())
    pdf.set_line_width(0.2)
    pdf.line(15, footer_y, page_w - 15, footer_y)

    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 8)
    pdf.set_xy(15, footer_y + 2)
    left = "Generated by Be Civic — bring originals; do not file printouts of original-required items."
    pdf.cell(120, 4, left)

    if generated_date:
        pdf.set_xy(page_w - 60, footer_y + 2)
        pdf.cell(45, 4, f"Rendered {generated_date}", align="R")
