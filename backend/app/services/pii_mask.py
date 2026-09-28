"""Mask customer PII before any cloud model call.

Prices and stock stay in tool results and are not passed through this function.
The mask is lossy on purpose: the model must not see a phone, card, sheba,
national id, postal code, or street address that the customer typed.
"""

from __future__ import annotations

import re

_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEP = r"[\s\-\u200c\u200d._]*"
_SHEBA = re.compile(rf"\bIR{_SEP}(?:\d{_SEP}){{24}}", re.IGNORECASE)
_CARD = re.compile(rf"(?<!\d)(?:\d{_SEP}){{15}}\d(?!\d)")
_MOBILE = re.compile(rf"(?<!\d)(?:\+98|0098|0){_SEP}9(?:{_SEP}\d){{9}}(?!\d)")
_LANDLINE = re.compile(rf"(?<!\d)0{_SEP}[1-8]\d(?:{_SEP}\d){{8}}(?!\d)")
_TEN = re.compile(r"(?<!\d)\d{10}(?!\d)")
_ADDRESS = re.compile(
    r"(?:خیابان|کوچه|بن[\u200c\s]*بست|بلوار|بزرگراه|پلاک|طبقه|واحد|کد[\s\u200c]*پستی)"
    r"[^\n.]{0,90}"
)


def _fold(text: str) -> str:
    return text.translate(_DIGIT)


def mask_pii(text: str) -> str:
    """Return text with customer secrets replaced by fixed Persian placeholders."""
    raw = str(text or "")
    if not raw:
        return ""
    folded = _fold(raw)
    folded = _SHEBA.sub("[شبا]", folded)
    folded = _CARD.sub("[کارت]", folded)
    folded = _MOBILE.sub("[تلفن]", folded)
    folded = _LANDLINE.sub("[تلفن]", folded)
    folded = _TEN.sub("[کد]", folded)
    folded = _ADDRESS.sub("[نشانی]", folded)
    return folded
