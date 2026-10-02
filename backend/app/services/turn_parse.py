from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
_WORD = r"(?<![\u0600-\u06FF\w]){token}(?![\u0600-\u06FF\w])"


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads((_DATA / "router_registry.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def spec() -> dict:
    return json.loads((_DATA / "router_spec.json").read_text(encoding="utf-8"))


def word_in(text: str, token: str) -> bool:
    if not token:
        return False
    return re.search(_WORD.format(token=re.escape(token)), text or "") is not None


def _has_mark(text: str, marks: list) -> bool:
    return any(mark and mark in (text or "") for mark in marks)


@dataclass
class Turn:
    raw: str
    act: str = "unknown"
    topic: str = ""
    subject: str = ""
    write: bool = False
    revise: bool = False
    question: bool = False
    formats: list[str] = field(default_factory=list)
    platform: str = ""
    no_overlay: bool = False
    handmade: bool = False
    formal: bool = False


def _write(text: str, data: dict) -> bool:
    if _has_mark(text, list(data.get("write_marks") or [])):
        return True
    return any(word_in(text, str(word)) for word in data.get("write_words") or [])


def _subject(text: str, data: dict) -> str:
    from app.services.persian_text import sanitize_persian

    cleaned = sanitize_persian(text or "", limit=80)
    drops = (
        "بساز",
        "درست کن",
        "یک پست",
        "هیچ نوشته",
        "نوشته‌ای نباشد",
        "نوشته ای نباشد",
        "روی عکس",
        "هشتگ",
        "انگلیسی",
        "لاتین",
        "رسمی‌تر",
        "رسمی تر",
        "برای",
        "یک",
        "قبلی",
        "کن",
        *[str(word) for word in data.get("format_words") or []],
    )
    for drop in drops:
        cleaned = cleaned.replace(drop, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ،؛.")
    return cleaned[:36]


# «رمز» فقط وقتی کلمهٔ مستقل است؛ در «قرمز» و «رمزگذاری» پنهان نیست.
_SECRET_WORD = re.compile(
    r"(?<![\u0600-\u06FF])(?:رمز(?:م|\s?عبور|\s?دوم|\s?پویا|\s?یکبار)?|پسورد|password)(?![\u0600-\u06FF])", re.I
)
_MENU_WORD = re.compile(r"(?<![\u0600-\u06FF])منو(?:ی)?(?![\u0600-\u06FF])")


def _topic(text: str, write: bool) -> str:
    folded = (text or "").lower().replace("’", "'")
    if "وضعیت" in text:
        return "status"
    if _SECRET_WORD.search(text) or any(mark in folded for mark in ("otp", "توکن", "کد ورود", "کد یکبار", "api key", "کلید api")):
        return "secret"
    if "شبا" in text:
        return "shaba"
    if "joahr" in folded or "فروشگاه دیگر" in text or "فروشگاه همسایه" in text:
        return "other_shop"
    channels = ("اینستاگرام", "تلگرام", "روبیکا", "واتساپ")
    if any(mark in text for mark in channels) and "وصل" in text and "کن" in text:
        return "channel_connect"
    if write:
        return ""
    if any(mark in text for mark in ("ساعت کاری", "آدرس", "تلفن", "شماره تماس")):
        return "missing_profile"
    if "تخفیف" in text:
        return "discount"
    if "خرید" in text and "چند" in text:
        return "purchases"
    if "خطا" in text and "ساخت" in text:
        return "build_error"
    if ("دامنه" in text or ("دامن" in text and "فرو" in text)) and any(
        mark in text for mark in ("چیه", "چیست", "بگو", "هست", "بدون")
    ):
        return "domain"
    if "کیف پول" in text:
        return "wallet"
    if "پلن" in text or "سقف" in text:
        return "plan"
    if any(mark in text for mark in ("اینستاگرام", "تلگرام", "روبیکا")) and "وصل" in text and "کن" not in text:
        return "channel_status"
    if ("کالا" in text or "محصول" in text) and any(mark in text for mark in ("چند", "تعداد")):
        return "product_count"
    if "موجودی" in text:
        return "stock"
    if "اسم" in text and "فروشگاه" in text:
        return "shop_name"
    if "شعار" in text:
        return "slogan"
    if _MENU_WORD.search(text):
        return "menu"
    if "رنگ" in text and any(mark in text for mark in ("چقدر", "چند", "چیست", "چیه", "هست", "دارم", "داری", "بگو", "بالا")):
        return "color"
    if word_in(text, "پورت"):
        return "port"
    if "قیمت" in text and any(mark in text for mark in ("هست", "هست یا نه", "نشان داده", "پنهان")) and "کن" not in text and "بده" not in text:
        return "price_hidden"
    if (
        "قیمت" in text
        and "کن" not in text
        and "بده" not in text
        and "نشان" not in text
        and "پنهان" not in text
        and "مخفی" not in text
        and "بساز" not in text
        and "بگذار" not in text
        and "بذار" not in text
        and "اضافه" not in text
        and not any(mark in text for mark in ("نشون", "نمایش", "قایم", "پنهون", "بردار", "حذف", "عوض", "تغییر", "درصد", "ببر", "بزار"))
    ):
        return "price"
    if any(mark in text for mark in ("بالا است", "بالاست", "آماده است")):
        return "site_up"
    if any(mark in text for mark in ("صندوق", "خوانده")):
        return "inbox"
    return ""


def _act(text: str, data: dict, *, revise: bool, topic: str) -> str:
    if any(mark in text for mark in data.get("publish_marks") or []):
        return "publish"
    if revise or _has_mark(text, ["کپشن", "هشتگ", "استوری"]):
        return "studio"
    photo = ("عکس" in text or "تصویر" in text) and any(mark in text for mark in ("بساز", "بسازی", "طراحی"))
    if photo:
        return "studio"
    if "پست" in text and any(mark in text for mark in ("بساز", "بنویس", "درست")):
        return "studio"
    if "ریلز" in text and "بساز" in text:
        return "studio"
    if "اضافه" in text and word_in(text, "کن") and "صفحه" not in text:
        return "add_product"
    if any(mark in text for mark in data.get("advice_marks") or []):
        return "advice"
    if topic and topic not in {"status", "inbox"}:
        return "read"
    if topic == "status":
        return "read"
    return "unknown"


def _formats(text: str) -> list[str]:
    found: list[str] = []
    if "استوری" in text:
        found.append("story")
    if any(mark in text for mark in ("ریلز", "ریل", "ویدیو")):
        found.append("reel")
    if "پست" in text or "فید" in text:
        found.append("feed")
    return found


def _platform(text: str) -> str:
    if "واتساپ" in text:
        return "whatsapp"
    if "تلگرام" in text:
        return "telegram"
    if "اینستا" in text:
        return "instagram"
    return ""


def parse_turn(text: str) -> Turn:
    data = registry()
    raw = text or ""
    write = _write(raw, data)
    revise = _has_mark(raw, list(data.get("revise_marks") or [])) and "عکس" not in raw and "تصویر" not in raw
    topic = _topic(raw, write)
    return Turn(
        raw=raw,
        act=_act(raw, data, revise=revise, topic=topic),
        topic=topic,
        subject=_subject(raw, data),
        write=write,
        revise=revise,
        question=raw.strip().endswith(("؟", "?")) or any(mark in raw for mark in ("چیه", "چیست", "چقدر", "چند")),
        formats=_formats(raw),
        platform=_platform(raw),
        no_overlay=any(mark in raw for mark in ("بدون متن", "هیچ نوشته", "روی عکس ننویس", "نوشته‌ای نباشد", "نوشته ای نباشد")),
        handmade=bool(re.search(r"دست[\s\u200c-]*ساز", raw)),
        formal=any(mark in raw for mark in ("رسمی‌تر", "رسمی تر")),
    )
