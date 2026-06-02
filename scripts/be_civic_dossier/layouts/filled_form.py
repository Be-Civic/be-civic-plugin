"""be_civic_dossier.layouts.filled_form — Be-Civic-rendered filled form.

Layout: Be Civic-rendered HTML with filled fields and signature lines.
"SIGN BEFORE FILING" watermark on every page in the user's conversation
language. The form template lives under
``skills/bc-dossier-compilation/templates/filled-form-<template-id>.html``;
the codegen module resolves it and renders via fpdf2's HTML support.

This is a page we generate, so it carries Be Civic branding plus the
sign-before-filing watermark as a usability nudge.

Used for: Annexe 1 declaration of nationality, other Belgian admin
forms where the agent fills the fields and the user signs before
walking into the commune.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class FilledForm:
    """Item-class for an agent-filled form page.

    :param template_id: short ID identifying which form template to use.
        Maps to ``skills/bc-dossier-compilation/templates/filled-form-{template_id}.html``.
        Example: ``"annexe-1"`` -> ``filled-form-annexe-1.html``.
    :param fields_dict: mapping of template variable -> filled value. Used
        when the template renderer substitutes ``{{ field_name }}``
        placeholders.
    :param original_required: filed forms aren't "originals" in the
        printout-vs-original sense (the user signs the printout). Default
        False; the watermark logic applies the *sign-before-filing*
        watermark regardless.
    """

    template_id: str
    fields_dict: Dict[str, str] = field(default_factory=dict)
    original_required: bool = False
    cert_type: str = ""  # filled in by the dossier container if blank

    layout_class: str = "filled-form"

    def template_filename(self) -> str:
        """Return the bundled template filename for this form."""
        return f"filled-form-{self.template_id}.html"

    def render_pdf_bytes(
        self,
        *,
        conversation_language: str,
        template_html: str,
    ) -> bytes:
        """Render the filled form to PDF bytes.

        :param conversation_language: ISO 639-1 code; controls the
            sign-before-filing watermark text.
        :param template_html: the resolved template HTML (after Jinja-style
            substitution of ``fields_dict``; substitution is the caller's
            responsibility, typically via ``be_civic_dossier.codegen``).
        :returns: PDF bytes — the form page(s), without the watermark.
            The dossier renderer applies the watermark in a post-pass.
        """
        from fpdf import FPDF
        from .. import metadata

        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(18, 18, 18)
        metadata.register_fonts(pdf, ("Inter", "SourceSansPro"))
        pdf.add_page()

        # fpdf2's write_html supports a subset of HTML.
        # We strip out the <style> block (fpdf2 ignores most CSS anyway)
        # and the @font-face declarations, since those reference paths that
        # only work in a real HTML rendering engine.
        body_html = _extract_body_for_fpdf(template_html)

        # fpdf2 doesn't natively understand @font-face from a style block,
        # so we set our preferred body font as the default and rely on
        # the template using simple inline structure.
        pdf.set_font("SourceSansPro", "", 11)
        pdf.set_text_color(*metadata.BRAND["ink_body"].as_tuple())
        # fpdf2's write_html honours <h1>/<h2>/<p>/<b>/<i>/<ul>/<li>/<br>/<table>
        # and styled fonts. Other CSS is ignored.
        pdf.write_html(body_html)

        metadata.apply_deterministic_metadata(pdf)
        return bytes(pdf.output())


def _extract_body_for_fpdf(template_html: str) -> str:
    """Strip <style>...</style> and <head>...</head>, return body innerHTML-ish.

    fpdf2's write_html doesn't process CSS; passing it raw template HTML
    with @font-face rules and CSS variables results in ugly fallback text.
    We strip the head/style blocks and keep just the body content, which
    fpdf2 can interpret.
    """
    import re
    # remove <head>...</head>
    html = re.sub(r"<head>.*?</head>", "", template_html, flags=re.IGNORECASE | re.DOTALL)
    # remove inline <style>...</style>
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)
    # extract body if present
    m = re.search(r"<body[^>]*>(.*)</body>", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return html.strip()
