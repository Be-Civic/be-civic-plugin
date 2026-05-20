"""be_civic_dossier.officer_notes — agent-authored officer-notes prose.

Section 4 of the dossier (per design doc §2): a markdown-source page (or
pages) the agent authors, explaining the routing call, eligibility math,
applicable statute, and any commune-specific notes for the receiving
officer.

This module renders a minimal subset of CommonMark — enough to express the
prose the agent typically writes:

* paragraphs separated by blank lines
* level-1 and level-2 headings (``# foo``, ``## bar``)
* unordered bullets (``- foo``, ``* foo``)
* inline bold (``**foo**``) and italic (``*foo*``)

Anything more complex (tables, code blocks, links, nested lists) is
intentionally out of scope for V1. The agent should split into paragraphs
and bullets if it wants richer structure.

Branding: this is a Be-Civic-generated page (design doc §3).

Stream A — owned by the W25.1a dossier-rebuild work.
"""

from __future__ import annotations

import re
from typing import Iterator, Tuple

from . import metadata


def add_officer_notes_pages(pdf, *, markdown_text: str, applicant_name: str = "") -> None:
    """Append officer-notes pages to ``pdf``.

    Assumes fonts are already registered via :func:`metadata.register_fonts`.

    Handles long prose by flowing onto additional pages as needed.
    """
    if not markdown_text or not markdown_text.strip():
        # No notes — write a minimal page so the section still appears.
        markdown_text = "_Officer notes for this dossier have not been authored._"

    pdf.add_page()
    page_w = pdf.w
    margin = 18  # slightly tighter than other pages — prose reads better

    # ---- header
    pdf.set_xy(margin, margin)
    pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
    pdf.set_font("SourceSansPro", "", 9)
    pdf.cell(page_w - 2 * margin, 4, "OFFICER NOTES")

    pdf.set_xy(margin, margin + 5)
    pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
    pdf.set_font("Inter", "B", 18)
    pdf.cell(page_w - 2 * margin, 8, "Notes for the receiving officer")

    if applicant_name:
        pdf.set_xy(margin, margin + 15)
        pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
        pdf.set_font("SourceSansPro", "I", 10)
        pdf.cell(page_w - 2 * margin, 5, f"Re: {applicant_name}")

    pdf.set_y(margin + 24)

    # ---- thin rule
    pdf.set_draw_color(*metadata.BRAND["hairline"].as_tuple())
    pdf.set_line_width(0.2)
    pdf.line(margin, pdf.get_y(), page_w - margin, pdf.get_y())
    pdf.set_y(pdf.get_y() + 4)

    # ---- body
    _render_markdown(pdf, markdown_text, x=margin, max_width=page_w - 2 * margin)


# ---------------------------------------------------------------------------
# Tiny markdown renderer
# ---------------------------------------------------------------------------


_H1_RE = re.compile(r"^#\s+(.*)$")
_H2_RE = re.compile(r"^##\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")


def _render_markdown(pdf, text: str, *, x: float, max_width: float) -> None:
    """Render a slice of markdown into the current PDF position.

    Maintains the cursor position; the caller is responsible for any header
    they've already written.
    """
    lines = text.splitlines()
    para_buffer: list[str] = []

    def flush_paragraph() -> None:
        if not para_buffer:
            return
        joined = " ".join(s.strip() for s in para_buffer)
        para_buffer.clear()
        if not joined.strip():
            return
        pdf.set_text_color(*metadata.BRAND["ink_body"].as_tuple())
        pdf.set_font("SourceSansPro", "", 10.5)
        pdf.set_x(x)
        _write_inline(pdf, joined, max_width=max_width)
        pdf.ln(3)

    for line in lines:
        stripped = line.rstrip()

        # blank line ends a paragraph
        if not stripped.strip():
            flush_paragraph()
            continue

        m = _H1_RE.match(stripped)
        if m:
            flush_paragraph()
            pdf.set_y(pdf.get_y() + 3)
            pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
            pdf.set_font("Inter", "B", 14)
            pdf.set_x(x)
            pdf.multi_cell(max_width, 7, m.group(1))
            pdf.ln(1)
            continue

        m = _H2_RE.match(stripped)
        if m:
            flush_paragraph()
            pdf.set_y(pdf.get_y() + 2)
            pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
            pdf.set_font("Inter", "B", 12)
            pdf.set_x(x)
            pdf.multi_cell(max_width, 6, m.group(1))
            pdf.ln(1)
            continue

        m = _BULLET_RE.match(stripped)
        if m:
            flush_paragraph()
            pdf.set_text_color(*metadata.BRAND["ink_body"].as_tuple())
            pdf.set_font("SourceSansPro", "", 10.5)
            pdf.set_x(x)
            pdf.cell(4, 5, "•")
            pdf.set_x(x + 5)
            _write_inline(pdf, m.group(1), max_width=max_width - 5)
            pdf.ln(1)
            continue

        # otherwise it's a paragraph continuation
        para_buffer.append(stripped)

    flush_paragraph()


def _write_inline(pdf, text: str, *, max_width: float) -> None:
    """Render a paragraph of text with **bold** and *italic* inline runs.

    fpdf2's multi_cell supports basic markup if we drive it ourselves. We
    tokenize the line and write segment by segment, switching font style.
    """
    segments = _tokenize_inline(text)
    # Use multi_cell with markdown=False; we manage style switching ourselves.
    # We can't naively change font mid-multi_cell because that breaks the
    # word-wrap. Approach: write each segment via cell() with the appropriate
    # style; let fpdf2's auto line break handle wrapping.

    # Track the running x position; start at the current cursor.
    line_height = 5.5
    pdf.set_font("SourceSansPro", "", 10.5)
    # Use write() which is the right tool here — it inserts text into the
    # current paragraph and handles wrapping at word boundaries, while
    # allowing font changes between calls.
    for style, segment in segments:
        if style == "B":
            pdf.set_font("SourceSansPro", "B", 10.5)
        elif style == "I":
            pdf.set_font("SourceSansPro", "I", 10.5)
        elif style == "BI":
            pdf.set_font("SourceSansPro", "BI", 10.5)
        else:
            pdf.set_font("SourceSansPro", "", 10.5)
        pdf.write(line_height, segment)
    pdf.ln(line_height)


_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_)")


def _tokenize_inline(text: str) -> Iterator[Tuple[str, str]]:
    """Yield (style_code, segment) tuples for an inline-formatted line.

    Style codes match fpdf2's set_font: ``''`` regular, ``'B'`` bold,
    ``'I'`` italic.
    """
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            yield ("", text[pos:match.start()])
        token = match.group(0)
        if token.startswith("**") and token.endswith("**"):
            yield ("B", token[2:-2])
        elif token.startswith("*") and token.endswith("*"):
            yield ("I", token[1:-1])
        elif token.startswith("_") and token.endswith("_"):
            yield ("I", token[1:-1])
        else:
            yield ("", token)
        pos = match.end()
    if pos < len(text):
        yield ("", text[pos:])
