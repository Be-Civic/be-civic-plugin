"""be_civic_dossier.dossier — top-level Dossier container.

The ``Dossier`` class is the renderer's public surface. The agent (or the
user) builds one in ``render.py`` like::

    d = Dossier(procedure_id="...", procedure_title="...", ...)
    d.add(FullPageCert("../documents/birth.pdf", ...))
    d.add(MultiPageDoc("../documents/compte-individuel.pdf", ...))
    d.add(Placeholder(cert_type="Annexe 1", source="commune visit"))
    d.add_officer_notes(Path("officer-notes.md").read_text())
    d.render(output_path="dossier-2026-05-19.pdf")

Re-running with the same documents folder produces byte-identical
output (design doc §5).

Architecture:

1. Items are stored in insertion order.
2. ``render()`` builds the dossier in seven sections per design doc §2:
   cover, checklist, "bring originals" callout (embedded in checklist),
   officer notes, then per-item content with section dividers between.
3. For each item, the layout class produces its own pages (via fpdf2 for
   Be-Civic-generated content, or via pypdf passthrough for user
   documents).
4. Pages where ``original_required=True`` get the diagonal watermark
   layered on via pypdf in a post-pass.
5. Final assembly is a pypdf merge of all the section PDFs into one.

Stream A — owned by the W25.1a dossier-rebuild work.
"""

from __future__ import annotations

import datetime
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from . import metadata
from .checklist import add_checklist_page, ChecklistRow, ORIGINAL_REQUIRED_FORMS
from .cover import add_cover_page
from .layouts import (
    FeeReceipt,
    FilledForm,
    FullPageCert,
    IdCard,
    MultiPageDoc,
    Placeholder,
)
from .layouts.id_card import render_id_cards_to_pdf_bytes
from .officer_notes import add_officer_notes_pages
from .watermark import apply_watermark_to_pdf


# Union type: any of the six item classes.
DossierItem = object  # too broad to type usefully without a Protocol


class Dossier:
    """Top-level dossier container.

    Constructor per design doc §8::

        Dossier(
            procedure_id="nationality-application",
            procedure_title="Belgian nationality declaration (...)",
            conversation_language="en",
            filing_language="fr",
            applicant_name="Henry Kernot",
            filing_authority="Commune d'Ixelles ...",
            filing_date="2026-05-19",
        )
    """

    def __init__(
        self,
        *,
        procedure_id: str,
        procedure_title: str,
        conversation_language: str,
        filing_language: str,
        applicant_name: str,
        filing_authority: str,
        filing_date: str,
    ) -> None:
        self.procedure_id = procedure_id
        self.procedure_title = procedure_title
        self.conversation_language = (conversation_language or "en").lower()
        self.filing_language = (filing_language or self.conversation_language).lower()
        self.applicant_name = applicant_name
        self.filing_authority = filing_authority
        self.filing_date = filing_date

        self.items: List[DossierItem] = []
        self.officer_notes_md: str = ""

        # Optional metadata captured for tests / debugging.
        self.skill_version: str = ""
        self.skill_status: str = ""

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def add(self, item: DossierItem) -> None:
        """Append an item to the dossier."""
        self.items.append(item)

    def add_officer_notes(self, markdown_text: str) -> None:
        """Set the officer-notes prose (markdown source)."""
        self.officer_notes_md = markdown_text or ""

    def render(
        self,
        *,
        output_path: str,
        base_dir: Optional[Path] = None,
    ) -> Path:
        """Render the dossier to ``output_path``.

        :param output_path: filename or path the bound PDF is written to.
            Relative paths are resolved against ``base_dir`` or the
            current working directory.
        :param base_dir: directory to resolve relative item ``file_path``
            values against. Defaults to the parent of ``output_path``.
        :returns: absolute path the PDF was written to.

        Re-running with the same documents/folder produces byte-identical
        bytes. Missing item files are auto-substituted by ``Placeholder``
        pages (design doc §8 "Behaviour on missing files").
        """
        out_path = Path(output_path)
        if not out_path.is_absolute():
            out_path = (Path(base_dir).resolve() if base_dir else Path.cwd()) / out_path
        out_path = out_path.resolve()
        if base_dir is None:
            base_dir = out_path.parent

        # Normalise items: replace items pointing to missing files with
        # Placeholders so downstream code can rely on file presence.
        items = self._normalise_items(base_dir)

        # Build each section as its own PDF bytes blob, then concatenate
        # at the end via pypdf.
        section_blobs: List[bytes] = []

        # 1. Cover page
        section_blobs.append(self._build_cover_pdf())

        # 2. Checklist (with "bring originals" callout integrated)
        section_blobs.append(self._build_checklist_pdf(items))

        # 3. Officer notes
        if self.officer_notes_md.strip():
            section_blobs.append(self._build_officer_notes_pdf())

        # 4-7. Per-item content.
        # Group consecutive IdCards so they pack into rows; everything else
        # passes through one at a time, prefixed by a divider page.
        for blob in self._render_items_in_order(items, base_dir):
            section_blobs.append(blob)

        # Final concat
        final_bytes = _concat_pdfs(section_blobs)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(final_bytes)
        return out_path

    # ----------------------------------------------------------------------
    # Section builders
    # ----------------------------------------------------------------------

    def _build_cover_pdf(self) -> bytes:
        from fpdf import FPDF
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(15, 15, 15)
        metadata.register_fonts(pdf, ("Inter", "SourceSansPro"))
        add_cover_page(
            pdf,
            applicant_name=self.applicant_name,
            procedure_title=self.procedure_title,
            procedure_id=self.procedure_id,
            filing_authority=self.filing_authority,
            filing_date=self.filing_date,
            generated_date=self.filing_date,
            skill_version=self.skill_version,
            skill_status=self.skill_status,
        )
        metadata.apply_deterministic_metadata(pdf)
        return bytes(pdf.output())

    def _build_checklist_pdf(self, items: Sequence[DossierItem]) -> bytes:
        from fpdf import FPDF
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(15, 15, 15)
        metadata.register_fonts(pdf, ("Inter", "SourceSansPro"))

        rows = [self._item_to_checklist_row(idx + 1, item) for idx, item in enumerate(items)]
        add_checklist_page(pdf, rows=rows, procedure_title=self.procedure_title)
        metadata.apply_deterministic_metadata(pdf)
        return bytes(pdf.output())

    def _build_officer_notes_pdf(self) -> bytes:
        from fpdf import FPDF
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(18, 18, 18)
        metadata.register_fonts(pdf, ("Inter", "SourceSansPro"))
        add_officer_notes_pages(
            pdf,
            markdown_text=self.officer_notes_md,
            applicant_name=self.applicant_name,
        )
        metadata.apply_deterministic_metadata(pdf)
        return bytes(pdf.output())

    def _build_divider_pdf(self, *, cert_type: str, layout_class: str) -> bytes:
        """A short divider page introducing the next dossier item.

        Be Civic-branded; carries the item name and class hint."""
        from fpdf import FPDF
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(15, 15, 15)
        pdf.set_auto_page_break(auto=False)
        metadata.register_fonts(pdf, ("Inter", "SourceSansPro"))
        pdf.add_page()

        # gold accent stripe at top
        pdf.set_fill_color(*metadata.BRAND["gold"].as_tuple())
        pdf.rect(0, 0, pdf.w, 4, style="F")

        # eyebrow label
        pdf.set_xy(15, pdf.h * 0.35)
        pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
        pdf.set_font("SourceSansPro", "", 10)
        pdf.cell(pdf.w - 30, 5, "NEXT ITEM", align="L")

        # cert type
        pdf.set_xy(15, pdf.h * 0.35 + 8)
        pdf.set_text_color(*metadata.BRAND["ink"].as_tuple())
        pdf.set_font("Inter", "B", 22)
        pdf.multi_cell(pdf.w - 30, 10, cert_type, align="L")

        # class hint
        pdf.set_xy(15, pdf.get_y() + 4)
        pdf.set_text_color(*metadata.BRAND["mute"].as_tuple())
        pdf.set_font("SourceSansPro", "I", 10)
        pdf.cell(pdf.w - 30, 5, f"presentation: {layout_class}")

        metadata.apply_deterministic_metadata(pdf)
        return bytes(pdf.output())

    # ----------------------------------------------------------------------
    # Per-item rendering
    # ----------------------------------------------------------------------

    def _render_items_in_order(
        self,
        items: Sequence[DossierItem],
        base_dir: Path,
    ) -> List[bytes]:
        """Yield section blobs (divider + content) for each item in order.

        Consecutive ``IdCard`` items are grouped onto packed A4 pages.
        """
        blobs: List[bytes] = []
        i = 0
        while i < len(items):
            item = items[i]

            if isinstance(item, IdCard):
                # Find the run of consecutive IdCards
                run_end = i
                while run_end < len(items) and isinstance(items[run_end], IdCard):
                    run_end += 1
                cards = list(items[i:run_end])

                # Single divider for the whole id-card section
                divider_label = (
                    cards[0].cert_type if len(cards) == 1
                    else f"{cards[0].cert_type} (and {len(cards) - 1} more)"
                )
                blobs.append(self._build_divider_pdf(
                    cert_type=divider_label, layout_class="id-card",
                ))

                # render packed rows
                packed = render_id_cards_to_pdf_bytes(cards, base_dir=base_dir)
                # overlay each card's actual content via pypdf transform
                packed = _embed_id_card_sources(packed, cards, base_dir=base_dir)
                # watermark if any card in the run is original-required
                if any(c.original_required for c in cards):
                    packed = apply_watermark_to_pdf(
                        packed, "original_required", self.conversation_language,
                    )
                blobs.append(packed)
                i = run_end
                continue

            # all other item classes: single divider + their PDF + watermark
            divider = self._build_divider_pdf(
                cert_type=getattr(item, "cert_type", ""),
                layout_class=getattr(item, "layout_class", "?"),
            )
            blobs.append(divider)

            item_pdf = self._render_single_item(item, base_dir)
            if item_pdf is not None:
                blobs.append(item_pdf)
            i += 1

        return blobs

    def _render_single_item(
        self, item: DossierItem, base_dir: Path,
    ) -> Optional[bytes]:
        """Render one non-IdCard item to PDF bytes (with watermark applied)."""
        if isinstance(item, Placeholder):
            from fpdf import FPDF
            pdf = FPDF(format="A4", unit="mm")
            pdf.set_margins(18, 18, 18)
            metadata.register_fonts(pdf, ("Inter", "SourceSansPro"))
            item.render_pages(pdf)
            metadata.apply_deterministic_metadata(pdf)
            return bytes(pdf.output())

        if isinstance(item, FilledForm):
            # Resolve and substitute the form template, then render to PDF.
            template_html = _resolve_filled_form_template(item, base_dir=base_dir)
            pdf_bytes = item.render_pdf_bytes(
                conversation_language=self.conversation_language,
                template_html=template_html,
            )
            # Always sign-before-filing watermark on filled forms
            pdf_bytes = apply_watermark_to_pdf(
                pdf_bytes, "sign_before_filing", self.conversation_language,
            )
            return pdf_bytes

        if isinstance(item, FullPageCert):
            data = item.load_pdf_bytes(base_dir)
            if data is None:
                return None
            data = item.auto_rotate(data)
            if item.original_required:
                data = apply_watermark_to_pdf(
                    data, "original_required", self.conversation_language,
                )
            return data

        if isinstance(item, (MultiPageDoc, FeeReceipt)):
            data = item.load_pdf_bytes(base_dir)
            if data is None:
                return None
            if item.original_required:
                data = apply_watermark_to_pdf(
                    data, "original_required", self.conversation_language,
                )
            return data

        # Unknown class — defensive no-op
        return None

    # ----------------------------------------------------------------------
    # Item normalisation
    # ----------------------------------------------------------------------

    def _normalise_items(self, base_dir: Path) -> List[DossierItem]:
        """Replace items whose source file is missing with Placeholders.

        Per design doc §8: "if an item's file_path doesn't exist, the
        renderer auto-substitutes a Placeholder for that slot (with a
        console warning the agent surfaces in chat). No exceptions, no
        halt."
        """
        out: List[DossierItem] = []
        for item in self.items:
            file_path = getattr(item, "file_path", None)
            if file_path is None:
                # Placeholder / FilledForm have no file_path → pass through
                out.append(item)
                continue
            p = Path(file_path)
            if not p.is_absolute():
                p = base_dir / p
            if p.is_file():
                out.append(item)
                continue
            # Missing — substitute Placeholder
            cert_type = getattr(item, "cert_type", str(file_path))
            print(
                f"WARNING: dossier source file missing for "
                f"{cert_type!r}: {file_path}. Substituting a Placeholder.",
                flush=True,
            )
            out.append(Placeholder(
                cert_type=cert_type,
                source=f"original source: {file_path}",
            ))
        return out

    # ----------------------------------------------------------------------
    # Checklist row mapping
    # ----------------------------------------------------------------------

    def _item_to_checklist_row(self, index: int, item: DossierItem) -> ChecklistRow:
        cert_type = getattr(item, "cert_type", "")
        # template_id for FilledForm if cert_type not set
        if not cert_type and hasattr(item, "template_id"):
            cert_type = f"Filled form: {item.template_id}"

        is_placeholder = isinstance(item, Placeholder)
        original_required = bool(getattr(item, "original_required", False))

        if is_placeholder:
            form_requirement = "Original"  # placeholders default to needing the original
        elif isinstance(item, FilledForm):
            form_requirement = "Original"  # the user signs & files the printout-as-original
        elif original_required:
            # We don't know which specific sub-class (Original / Apostilled / etc.)
            # without consulting the procedure canonical; the agent supplies
            # the exact label via cert_type and/or via direct ChecklistRow
            # construction in V2. For V1 we use the umbrella "Original".
            form_requirement = "Original"
        else:
            form_requirement = "Printout acceptable"

        source = ""
        if isinstance(item, Placeholder):
            source = item.source
        elif isinstance(item, FeeReceipt) and item.payment_date:
            source = f"paid {item.payment_date}"

        return ChecklistRow(
            index=index,
            document_name=cert_type or "(unnamed item)",
            form_requirement=form_requirement,
            source=source,
            is_placeholder=is_placeholder,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concat_pdfs(blobs: Sequence[bytes]) -> bytes:
    """Concatenate a list of single-section PDF blobs into one PDF."""
    import pypdf
    writer = pypdf.PdfWriter()
    for blob in blobs:
        reader = pypdf.PdfReader(io.BytesIO(blob))
        for page in reader.pages:
            writer.add_page(page)
    # Set deterministic metadata on the final concatenated file too.
    writer.add_metadata({
        "/Producer": metadata.PDF_PRODUCER,
        "/Creator": metadata.PDF_CREATOR,
        "/CreationDate": _pdf_date(metadata.DETERMINISTIC_TIMESTAMP),
        "/ModDate": _pdf_date(metadata.DETERMINISTIC_TIMESTAMP),
    })
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _pdf_date(dt: datetime.datetime) -> str:
    """Format a datetime as a PDF D-string: D:YYYYMMDDHHmmSS+00'00'."""
    s = dt.strftime("%Y%m%d%H%M%S")
    return f"D:{s}+00'00'"


def _embed_id_card_sources(
    packed_pdf_bytes: bytes,
    cards: Sequence[IdCard],
    *,
    base_dir: Path,
) -> bytes:
    """Overlay each card's source PDF page(s) onto the packed scaffold.

    The scaffold (from :func:`render_id_cards_to_pdf_bytes`) has slot
    borders and labels. This function uses pypdf's
    ``merge_transformed_page`` to scale + translate each card's front
    (and back, if present) into the appropriate slot.
    """
    import pypdf
    from pypdf import Transformation
    from .layouts.id_card import get_id_card_slot_geometry

    reader = pypdf.PdfReader(io.BytesIO(packed_pdf_bytes))
    writer = pypdf.PdfWriter()

    # iterate (page_index, card_index_on_page)
    cards_per_page = 2
    for page_idx, scaffold_page in enumerate(reader.pages):
        # which 0-2 cards belong on this scaffold page?
        start = page_idx * cards_per_page
        slice_cards = list(cards[start:start + cards_per_page])

        for slot_idx, card in enumerate(slice_cards):
            card_bytes = card.load_pdf_bytes(base_dir)
            if not card_bytes:
                continue
            card_reader = pypdf.PdfReader(io.BytesIO(card_bytes))
            (fx, fy, fw, fh, bx, by, bw, bh) = get_id_card_slot_geometry(slot_idx)

            # front: page 1 of source
            _merge_into_slot(
                scaffold_page,
                card_reader.pages[0],
                slot_x_mm=fx, slot_y_mm=fy,
                slot_w_mm=fw, slot_h_mm=fh,
                page_h_mm=297.0,
            )

            # back: page 2 of source if present
            if len(card_reader.pages) > 1:
                _merge_into_slot(
                    scaffold_page,
                    card_reader.pages[1],
                    slot_x_mm=bx, slot_y_mm=by,
                    slot_w_mm=bw, slot_h_mm=bh,
                    page_h_mm=297.0,
                )

        writer.add_page(scaffold_page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _merge_into_slot(
    scaffold_page,
    source_page,
    *,
    slot_x_mm: float,
    slot_y_mm: float,
    slot_w_mm: float,
    slot_h_mm: float,
    page_h_mm: float,
) -> None:
    """Scale + translate ``source_page`` onto ``scaffold_page`` at the slot.

    PDF coordinates are bottom-up (y=0 is the bottom of the page), while
    we author layouts top-down. Convert.

    All inputs are in mm; convert to points (1 mm = 2.83465 pt) for the
    pypdf Transformation.
    """
    from pypdf import Transformation
    MM_TO_PT = 2.83465

    src_w_pt = float(source_page.mediabox.width)
    src_h_pt = float(source_page.mediabox.height)

    slot_w_pt = slot_w_mm * MM_TO_PT
    slot_h_pt = slot_h_mm * MM_TO_PT

    # uniform scale to fit
    scale = min(slot_w_pt / src_w_pt, slot_h_pt / src_h_pt)
    scaled_w_pt = src_w_pt * scale
    scaled_h_pt = src_h_pt * scale

    # centre within the slot
    offset_x_mm = slot_x_mm + (slot_w_mm - scaled_w_pt / MM_TO_PT) / 2.0
    offset_y_top_mm = slot_y_mm + (slot_h_mm - scaled_h_pt / MM_TO_PT) / 2.0

    # convert from top-down mm to bottom-up pt
    tx_pt = offset_x_mm * MM_TO_PT
    ty_pt = (page_h_mm - offset_y_top_mm - scaled_h_pt / MM_TO_PT) * MM_TO_PT

    tr = Transformation().scale(scale).translate(tx_pt, ty_pt)
    scaffold_page.merge_transformed_page(source_page, tr)


def _resolve_filled_form_template(form: FilledForm, *, base_dir: Path) -> str:
    """Resolve the template for a FilledForm and apply field substitution.

    Resolution order matches ``be_civic_dossier.codegen.resolve_template``:
    project-local override first, then plugin-bundled fallback.

    Field substitution is a minimal mustache: ``{{ field_name }}`` ->
    ``form.fields_dict[field_name]``. Unmatched fields leave the literal
    placeholder in place so the agent can see what's missing.
    """
    # Try project-local override
    local_dir = base_dir / "templates"
    template_name = form.template_filename()

    project_path = local_dir / template_name
    if project_path.is_file():
        text = project_path.read_text(encoding="utf-8")
    else:
        # fall back to plugin-bundled. Don't import codegen here to keep
        # the dossier module dependency-free; resolve manually.
        plugin_root = _find_plugin_root_from_module()
        bundled = (
            plugin_root / "skills" / "bc-dossier-compilation" / "templates" / template_name
        )
        if not bundled.is_file():
            # bare-bones fallback so the dossier still renders
            text = (
                f"<html><body><h1>{form.cert_type or form.template_id}</h1>"
                "<p>Template not found; the agent must add a template at "
                f"<code>skills/bc-dossier-compilation/templates/{template_name}</code> "
                "before re-rendering.</p></body></html>"
            )
        else:
            text = bundled.read_text(encoding="utf-8")

    # very small mustache substitution
    import re
    def sub(match):
        key = match.group(1).strip()
        return str(form.fields_dict.get(key, match.group(0)))
    text = re.sub(r"\{\{\s*([\w.-]+)\s*\}\}", sub, text)
    return text


def _find_plugin_root_from_module() -> Path:
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        marker = ancestor / ".claude-plugin" / "plugin.json"
        if marker.is_file():
            return ancestor
    raise RuntimeError("Could not locate plugin root from be_civic_dossier.dossier")
