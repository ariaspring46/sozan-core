from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]*>")
_CTRL = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_PERSIAN = re.compile(r"[\u0600-\u06FF]")
_PUNCT = " ،.,:;؛!؟«»\"'`"
FA_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SAFE_EMPTY = "این را بلد نیستم؛ از فروشگاه یا محتوا بگو."
CUT_SHORT = "جواب برید. کوتاه‌تر بگو."
PERSIAN_ONLY = "فارسی جواب می‌دهم. بگو فروشگاه، محتوا، یا صندوق."
SECRET_SCAN = re.compile(r"(otp|api[_-]?key|jwt|bearer\s+[A-Za-z0-9._-]{12,}|IR\d{24})", re.I)
ENGLISH_REFUSAL = re.compile(r"i['’]?m sorry|i can['’]?t|i cannot", re.I)


def sanitize_persian(text: str, *, limit: int = 80) -> str:
    value = _TAG.sub("", text or "")
    value = value.replace("`", "")
    value = _CTRL.sub("", value)
    value = value.translate(FA_DIGIT)
    value = re.sub(r"\s+", " ", value).strip(_PUNCT)
    tokens = [token for token in value.split() if token]
    while tokens and tokens[-1] in {"رو", "را", "هر"}:
        tokens.pop()
    return " ".join(tokens)[:limit]


def _latin_count(text: str) -> int:
    cleaned = re.sub(r"https?://\S+", "", text or "")
    cleaned = re.sub(r"\b[\w.-]+\.(ir|com|org|net)\b", "", cleaned, flags=re.I)
    return len(re.findall(r"[A-Za-z]", cleaned))


def guard_output(text: str, *, finish: str = "", limit: int = 800) -> str:
    value = (text or "").strip()
    if "<|" in value or ENGLISH_REFUSAL.search(value):
        return "این را در چت جواب نمی‌دهم."
    if SECRET_SCAN.search(value):
        return "این را در چت نمی‌گویم."
    if finish == "length" and len(value) < 8:
        return CUT_SHORT
    if not value:
        return SAFE_EMPTY
    letters = _latin_count(value)
    persian = _PERSIAN.findall(value)
    if letters and letters > len(persian):
        return PERSIAN_ONLY
    return value[:limit]
