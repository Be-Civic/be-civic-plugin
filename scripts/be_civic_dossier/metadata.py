"""be_civic_dossier.metadata — shared constants, font registration, deterministic stamping.

This module is the single source of truth for:

* fixed PDF metadata strings (Producer, CreationDate, ModDate) so re-runs
  produce byte-identical output;
* the canonical font set bundled at ``vendor/fonts/``;
* the agreed brand palette baked into Be-Civic-generated pages (kept in
  sync with the HTML templates).

Nothing here renders a page; the rendering modules import these constants
and helpers.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple


# ---------------------------------------------------------------------------
# Deterministic PDF metadata
# ---------------------------------------------------------------------------

#: Fixed sentinel timestamp baked into every PDF we render.
#:
#: PDF spec D-strings carry a creation date and modification date. fpdf2
#: defaults to "now", which makes byte-identical re-runs impossible. We pin to
#: 2000-01-01T00:00:00Z so the dossier renderer satisfies the determinism
#: constraint (same documents -> same output bytes).
DETERMINISTIC_TIMESTAMP = datetime.datetime(
    2000, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc
)

#: Producer string written into the PDF /Producer field.
#:
#: fpdf2 normally writes "PyFPDF <version>" / "fpdf2 <version>". Fixed string
#: removes version drift from the metadata so library upgrades don't ripple
#: into hashed output.
PDF_PRODUCER = "Be Civic dossier renderer"

#: Creator string written into the PDF /Creator field. Stable string that names
#: the renderer; matches /Producer for our use.
PDF_CREATOR = "Be Civic dossier renderer"


def apply_deterministic_metadata(pdf) -> None:
    """Stamp an :class:`fpdf.FPDF` instance with the canonical fixed metadata.

    Call this once per FPDF instance, after pages are added but before
    ``output()``. Idempotent.
    """
    pdf.set_creation_date(DETERMINISTIC_TIMESTAMP)
    pdf.set_producer(PDF_PRODUCER)
    pdf.set_creator(PDF_CREATOR)
    # Title/author/subject/keywords intentionally left to the caller — those
    # are dossier-specific and don't affect bytewise determinism for a given
    # dossier definition.


# ---------------------------------------------------------------------------
# Vendor / font paths
# ---------------------------------------------------------------------------


def vendor_dir() -> Path:
    """Absolute path to the plugin's ``vendor/`` directory.

    Resolution: walk upward from this file looking for the plugin marker
    (``.claude-plugin/plugin.json``). Mirrors the resolution in
    :mod:`be_civic_dossier.codegen`.
    """
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        marker = ancestor / ".claude-plugin" / "plugin.json"
        if marker.is_file():
            return ancestor / "vendor"
    raise RuntimeError(
        "Could not locate plugin root from "
        f"{here}. Expected .claude-plugin/plugin.json in an ancestor."
    )


def fonts_dir() -> Path:
    """Absolute path to the plugin's bundled fonts."""
    return vendor_dir() / "fonts"


#: The font family registry. Maps family-name -> {style-code: filename}.
#:
#: Style codes follow fpdf2's convention: ``''`` regular, ``'B'`` bold,
#: ``'I'`` italic, ``'BI'`` bold-italic.
#:
#: Family names ("Inter", "SourceSansPro", "NotoSans", "NotoSansArabic") are
#: the strings rendering code uses with ``pdf.set_font(family, style, size)``.
#: They match the HTML template ``font-family`` declarations.
FONT_FAMILIES: Dict[str, Dict[str, str]] = {
    "Inter": {
        "": "Inter-Regular.ttf",
        "B": "Inter-Bold.ttf",
        "I": "Inter-Italic.ttf",
        "BI": "Inter-BoldItalic.ttf",
    },
    "SourceSansPro": {
        "": "SourceSansPro-Regular.ttf",
        "B": "SourceSansPro-Bold.ttf",
        "I": "SourceSansPro-Italic.ttf",
        "BI": "SourceSansPro-BoldItalic.ttf",
    },
    "NotoSans": {
        "": "NotoSans-Regular.ttf",
        "B": "NotoSans-Bold.ttf",
    },
    "NotoSansArabic": {
        "": "NotoSansArabic-Regular.ttf",
        "B": "NotoSansArabic-Bold.ttf",
    },
}


def register_fonts(
    pdf,
    families: Iterable[str] = ("Inter", "SourceSansPro"),
) -> None:
    """Register the requested font families on an FPDF instance.

    Default set covers UI (Inter) + body (Source Sans Pro). Pass
    ``("Inter", "SourceSansPro", "NotoSans")`` to add Cyrillic / Greek
    coverage, or include ``"NotoSansArabic"`` for Arabic.

    Idempotent within a single FPDF — fpdf2 raises ``FPDFException`` on
    duplicate registration, which this function swallows so callers can call
    it speculatively from multiple page generators.
    """
    from fpdf.errors import FPDFException  # imported lazily; vendor on sys.path
    base = fonts_dir()
    for family in families:
        styles = FONT_FAMILIES.get(family)
        if styles is None:
            raise ValueError(
                f"Unknown font family {family!r}. Known: {sorted(FONT_FAMILIES)}"
            )
        for style, filename in styles.items():
            try:
                pdf.add_font(family, style, str(base / filename))
            except FPDFException:
                # Already registered — fine.
                pass


def font_for_language(conversation_language: str) -> str:
    """Return the body-font family name appropriate for the language.

    Latin scripts -> SourceSansPro (the default body font).
    Cyrillic (uk) -> NotoSans (covers Latin + Cyrillic).
    Arabic (ar)   -> NotoSansArabic.

    Callers that need to mix scripts on one line must register both families
    and switch via ``pdf.set_font(...)`` per-run.
    """
    lang = (conversation_language or "en").lower()
    if lang == "ar":
        return "NotoSansArabic"
    if lang == "uk":
        return "NotoSans"
    return "SourceSansPro"


# ---------------------------------------------------------------------------
# Brand palette — kept in sync with the HTML template :root variables.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Color:
    """An RGB triple. Use ``.as_tuple()`` for fpdf2 set_text_color / set_fill_color."""

    r: int
    g: int
    b: int

    def as_tuple(self) -> Tuple[int, int, int]:
        return (self.r, self.g, self.b)


#: Be Civic brand palette. Hex values mirror the HTML templates.
#: Black (ink), Gold, Red are the Belgian flag stripe colours.
BRAND = {
    "black": Color(10, 10, 10),       # #0a0a0a — primary ink
    "gold": Color(250, 224, 66),      # #fae042 — flag stripe middle
    "red": Color(237, 41, 57),        # #ed2939 — flag stripe right + accents
    "cream": Color(245, 244, 238),    # #f5f4ee — page background tint
    "ink": Color(26, 26, 24),         # #1a1a18 — body headers
    "ink_body": Color(42, 42, 38),    # #2a2a26 — body text
    "mute": Color(106, 106, 101),     # #6a6a65 — secondary text
    "hairline": Color(235, 233, 227), # #ebe9e3 — thin rules
    "warn_red": Color(192, 57, 43),   # #c0392b — watermark red
}
