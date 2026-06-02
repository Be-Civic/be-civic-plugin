"""be_civic_dossier.checklist — dossier checklist + "bring originals" callout.

Renders section 2 of the dossier: a table with one row per dossier item
showing the document name, the form requirement (Original / Certified copy /
Apostilled / Sworn translation / Printout acceptable), and the source where
the user obtained it.

A "bring originals" callout follows, listing items whose Form column is not
"Printout acceptable" — these are also the items that receive the diagonal
watermark on their pages.

Branding: this is a Be-Civic-generated page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import metadata


# Form-requirement classification per the procedure canonical's `## Required
# documents` table. Strings are user-facing; this module displays them as-is.
FORM_REQUIREMENTS = (
    "Original",
    "Certified copy",
    "Apostilled",
    "Sworn translation",
    "Printout acceptable",
)

#: Form requirements that the user MUST bring as paper originals — i.e., the
#: warning watermark applies to these. Anything not in this set is acceptable
#: as a print-out and gets no watermark.
ORIGINAL_REQUIRED_FORMS = frozenset({
    "Original",
    "Certified copy",
    "Apostilled",
    "Sworn translation",
})


@dataclass
class ChecklistRow:
    """One row of the dossier checklist.

    :param index: 1-based row number, displayed in the § column.
    :param document_name: human-readable name, e.g. "Birth certificate (apostilled)".
    :param form_requirement: one of the strings in :data:`FORM_REQUIREMENTS`.
    :param source: where the user obtained the document, e.g.
        "Local registry office — Wycombe, UK" or "BAPA Brussels".
    :param is_placeholder: True if the dossier currently has a placeholder
        for this row instead of a real document. Displayed with a muted style.
    """

    index: int
    document_name: str
    form_requirement: str
    source: str = ""
    is_placeholder: bool = False


def add_checklist_page(pdf, *, rows: List[ChecklistRow], procedure_title: str = "") -> None:
    """Append the checklist + "bring originals" callout to ``pdf``.

    Assumes fonts are already registered via :func:`metadata.register_fonts`.

    May produce one or two pages depending on the number of rows.
    """
    pdf.add_page()
    page_w = pdf.w
    margin = 15
    available = page_w - 2 * margin

    # ---- header
    pdf.set_xy(margin, margin)
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 9)
    pdf.cell(available, 4, "DOSSIER CHECKLIST")

    pdf.set_xy(margin, margin + 5)
    pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_font("Inter", "B", 18)
    pdf.cell(available, 8, "Documents to file")

    if procedure_title:
        pdf.set_xy(margin, margin + 15)
        pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
        pdf.set_font("SourceSansPro", "", 11)
        pdf.cell(available, 6, procedure_title)

    # ---- table
    table_y = margin + 28
    _draw_table_header(pdf, x=margin, y=table_y, width=available)
    _draw_table_rows(pdf, x=margin, y=table_y + 8, width=available, rows=rows)

    # ---- bring originals callout
    originals = [r for r in rows if r.form_requirement in ORIGINAL_REQUIRED_FORMS and not r.is_placeholder]
    if originals:
        # If we're past 80% page height, start a new page.
        if pdf.get_y() > pdf.h - 70:
            pdf.add_page()
            pdf.set_y(margin)
        else:
            pdf.set_y(pdf.get_y() + 10)
        _draw_bring_originals_callout(pdf, x=margin, y=pdf.get_y(), width=available, items=originals)


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

# Column widths in mm. Sum should equal the available width (180mm at A4-1.5cm).
_COL_IDX = 10        # § (row number)
_COL_DOC = 78        # Document name
_COL_FORM = 38       # Form requirement
_COL_SRC = 54        # Source

_HEADER_HEIGHT = 8


def _draw_table_header(pdf, *, x: float, y: float, width: float) -> None:
    pdf.set_draw_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_line_width(0.4)
    pdf.line(x, y, x + width, y)

    pdf.set_fill_color(*metadata.BRAND["cream"].as_tuple())
    pdf.rect(x, y, width, _HEADER_HEIGHT, style="F")

    pdf.set_xy(x + 1, y + 2)
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "B", 9)
    headers = [
        ("§", _COL_IDX),
        ("DOCUMENT", _COL_DOC),
        ("FORM REQUIRED", _COL_FORM),
        ("SOURCE", _COL_SRC),
    ]
    cur_x = x + 1
    for label, w in headers:
        pdf.set_xy(cur_x, y + 2.5)
        pdf.cell(w, 4, label)
        cur_x += w

    # bottom border of header
    pdf.set_draw_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_line_width(0.4)
    pdf.line(x, y + _HEADER_HEIGHT, x + width, y + _HEADER_HEIGHT)


def _draw_table_rows(
    pdf, *, x: float, y: float, width: float, rows: List[ChecklistRow]
) -> None:
    cur_y = y
    for row in rows:
        row_height = _draw_table_row(pdf, x=x, y=cur_y, width=width, row=row)
        cur_y += row_height

        # hairline between rows
        pdf.set_draw_color(*metadata.BRAND["hairline"].as_tuple())
        pdf.set_line_width(0.15)
        pdf.line(x, cur_y, x + width, cur_y)

    # final solid bottom rule
    pdf.set_draw_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_line_width(0.4)
    pdf.line(x, cur_y, x + width, cur_y)
    pdf.set_y(cur_y)


def _draw_table_row(pdf, *, x: float, y: float, width: float, row: ChecklistRow) -> float:
    """Render one row. Returns the height consumed (mm)."""
    # We estimate row height = 8mm for normal rows; longer doc names wrap
    # to a second line which adds another 5mm.

    # text color: muted for placeholders, ink otherwise
    main_color = metadata.BRAND["mute"] if row.is_placeholder else metadata.BRAND["ink_body"]

    # index col
    pdf.set_xy(x + 1, y + 2.5)
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 10)
    pdf.cell(_COL_IDX - 1, 5, str(row.index))

    # document column — may wrap
    pdf.set_xy(x + _COL_IDX, y + 2)
    pdf.set_text_color(*main_color.as_tuple())
    pdf.set_font("SourceSansPro", "B", 10)
    doc_text = row.document_name
    if row.is_placeholder:
        doc_text = f"{doc_text}  [TO COLLECT]"
    # multi_cell with width = column width, keep on this row even if it wraps.
    pre_y = pdf.get_y()
    pdf.multi_cell(_COL_DOC - 2, 5, doc_text, align="L")
    doc_consumed = pdf.get_y() - pre_y

    # form-requirement column
    pdf.set_xy(x + _COL_IDX + _COL_DOC, y + 2)
    form_color = (
        metadata.BRAND["warn_red"]
        if row.form_requirement in ORIGINAL_REQUIRED_FORMS
        else metadata.BRAND["mute"]
    )
    pdf.set_text_color(*form_color.as_tuple())
    pdf.set_font("SourceSansPro", "B", 9)
    pdf.cell(_COL_FORM, 5, row.form_requirement)

    # source column
    pdf.set_xy(x + _COL_IDX + _COL_DOC + _COL_FORM, y + 2)
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 9)
    pdf.multi_cell(_COL_SRC - 2, 5, row.source or "—", align="L")

    # Row height: at minimum 8mm; expand if document or source wrapped.
    row_height = max(8.0, doc_consumed + 4)
    return row_height


# ---------------------------------------------------------------------------
# Bring-originals callout
# ---------------------------------------------------------------------------


def _draw_bring_originals_callout(
    pdf, *, x: float, y: float, width: float, items: List[ChecklistRow]
) -> None:
    """Tinted block listing the items the user must walk in with as originals."""
    # tinted background — light warn-red
    pdf.set_fill_color(252, 240, 235)
    callout_height = 12 + 6 * len(items) + 6
    pdf.rect(x, y, width, callout_height, style="F")

    # red left bar
    pdf.set_fill_color(*metadata.BRAND["warn_red"].as_tuple())
    pdf.rect(x, y, 3, callout_height, style="F")

    # header
    pdf.set_xy(x + 8, y + 4)
    pdf.set_text_color(*metadata.BRAND["warn_red"].as_tuple())
    pdf.set_font("Inter", "B", 11)
    pdf.cell(width - 8, 5, "BRING THESE AS ORIGINALS — DO NOT FILE PRINTOUTS")

    # list
    pdf.set_text_color(*metadata.BRAND["ink_body"].as_tuple())
    pdf.set_font("SourceSansPro", "", 10)
    for i, item in enumerate(items):
        pdf.set_xy(x + 8, y + 11 + i * 6)
        # bullet
        pdf.cell(3, 5, "•")
        pdf.set_xy(x + 11, y + 11 + i * 6)
        text = item.document_name
        if item.form_requirement != "Original":
            text = f"{text}  ({item.form_requirement.lower()})"
        pdf.cell(width - 14, 5, text)
