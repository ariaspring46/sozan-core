from __future__ import annotations

import re

from app.services.router_text import fix_halfspace, strip_markdown, trim_to_sentence

_THINK = re.compile(r"<think>.*?</think>", re.S)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
REFUSAL_GENERIC = "این را در چت جواب نمی‌دهم."
_TAG = re.compile(r"<[^>]*>")
_CTRL = re.compile(r"[\x00-\x1f\x7f\u200b\u200d-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_PERSIAN = re.compile(r"[\u0600-\u06FF]")
_PUNCT = " ،.,:;؛!؟«»\"'`"
FA_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SAFE_EMPTY = "این را بلد نیستم؛ از فروشگاه یا محتوا بگو."
CUT_SHORT = "جوابم نیمه‌کاره ماند. یک بار دیگر بپرس."
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
    value = _THINK.sub("", text or "").strip()
    if "<|" in value or ENGLISH_REFUSAL.search(value):
        return REFUSAL_GENERIC
    if SECRET_SCAN.search(value):
        return "این را در چت نمی‌گویم."
    # شناسهٔ داخلی (کمپین، پیام) هیچ‌وقت به فروشنده نشان داده نمی‌شود
    value = re.sub(r"[ \t]{2,}", " ", _UUID.sub("", value)).strip()
    # حباب چت متن ساده است: ** و # و بولت مارک‌داون نماد خام دیده می‌شود؛ نیم‌فاصلهٔ افتاده هم برمی‌گردد
    value = fix_halfspace(strip_markdown(value))
    if finish == "length" and len(value) < 8:
        return CUT_SHORT
    if finish == "length":
        # جواب کوتاه‌شده تا آخرین جملهٔ کامل می‌ماند؛ دور انداختنش کاربر را در حلقهٔ «دوباره بپرس» می‌گذارد
        value = trim_to_sentence(value) or CUT_SHORT
    if not value:
        return SAFE_EMPTY
    letters = _latin_count(value)
    persian = _PERSIAN.findall(value)
    if letters and letters > len(persian):
        return PERSIAN_ONLY
    if len(value) > limit:
        return trim_to_sentence(value[:limit], minimum=40) or value[:limit]
    return value
