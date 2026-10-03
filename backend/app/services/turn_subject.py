"""What a caption is about: a thing («انگشتر نقره»، «تخفیف یلدا»), never what the seller said to us."""

from __future__ import annotations

import re

# «داداش یه خفن واسه گردنبند بزن» is a request, not a subject
_COMMAND_WORDS = frozenset(
    "بزن بنویس بنویسید بگو بکن بده فقط باشد باشه باش خفن داداش واسه برا یه ایموجی کپشن چیزی نکن بفرست ببین سلام درود فروشگاهم فروشگاه ویترین ویترینم سایت سایتم".split()
)
_COMMAND_MARKS = ("http", "ignore", "instruction", "<", ">")
_PRODUCT_WORDS = (
    "انگشتر", "گردنبند", "گوشواره", "دستبند", "آویز", "النگو", "ست طلا", "کفش", "کتانی", "پیراهن", "مانتو", "شلوار", "شال", "روسری",
    "کیف", "ساعت", "عینک", "کلاه", "عطر", "شمع", "عروسک", "هودی", "تیشرت", "جوراب", "لباس", "فرش", "گلدان", "مجسمه", "ظرف",
)
_MATERIALS = ("نقره", "طلا", "فیروزه", "چرم", "عقیق", "یاقوت", "الماس", "مروارید", "ابریشم", "پشمی", "چوبی", "سرامیکی", "معطر")


def is_junk(text: str) -> bool:
    if not text:
        return False
    if len(text.split()) > 6:
        return True
    if len(re.findall(r"[A-Za-z]", text)) >= 3:
        return True
    words = set(re.split(r"[\s،؛.]+", text))
    return bool(words & _COMMAND_WORDS) or any(mark in text.lower() for mark in _COMMAND_MARKS)


def vocab_subject(text: str) -> str:
    """The product word the seller used (plus a material next to it), or '' when there is none."""
    blob = text or ""
    found = next((word for word in _PRODUCT_WORDS if word in blob), "")
    if not found:
        return ""
    tail = blob.split(found, 1)[1]
    material = next((m for m in _MATERIALS if re.match(r"[\s‌]*" + m, tail[:12])), "")
    return f"{found} {material}".strip()


def guard(cleaned: str, original: str) -> str:
    """The cleaned phrase when it is a plain subject, else the product word the seller used (or nothing: the caller asks)."""
    return vocab_subject(original) if is_junk(cleaned) else cleaned
