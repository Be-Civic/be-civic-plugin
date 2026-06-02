"""be_civic_dossier.layouts — item-class layout transformers.

Six classes:

* :class:`IdCard` — residence permit / eID / driving licence
* :class:`FullPageCert` — single-page issued certificate
* :class:`MultiPageDoc` — multi-page user document
* :class:`FeeReceipt` — federal/communal fee receipt
* :class:`FilledForm` — Be Civic-rendered filled form
* :class:`Placeholder` — TO-COLLECT placeholder

The transformer for each class accepts an input file path (PDF) plus
metadata and yields a normalised standardised PDF page sequence that
the dossier renderer concatenates in order.
"""

from __future__ import annotations

from .fee_receipt import FeeReceipt
from .filled_form import FilledForm
from .full_page_cert import FullPageCert
from .id_card import IdCard, render_id_cards_to_pdf_bytes, get_id_card_slot_geometry
from .multi_page_doc import MultiPageDoc
from .placeholder import Placeholder

__all__ = (
    "FeeReceipt",
    "FilledForm",
    "FullPageCert",
    "IdCard",
    "MultiPageDoc",
    "Placeholder",
    "render_id_cards_to_pdf_bytes",
    "get_id_card_slot_geometry",
)
