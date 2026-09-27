from __future__ import annotations

import re

from app.services.persian_text import sanitize_persian
from app.services.shop_edit_service import (
    looks_like_foreign_payload,
    named_color_updates,
    wants_delete_selected,
    wants_revert,
    write_intent,
)

PAGE_LABELS = {
    "about": "درباره ما",
    "contact": "تماس",
    "story": "داستان برند",
    "faq": "پرسش‌های متداول",
}
PAGE_HINTS = (
    ("faq", ("سؤالات متداول", "سوالات متداول", "پرسش‌های متداول", "پرسش", "faq")),
    ("about", ("درباره ما", "درباره", "about")),
    ("contact", ("تماس با ما", "تماس", "ارتباط", "contact")),
    ("story", ("داستان برند", "قصه ما", "داستان", "قصه", "story")),
)
SHOW_PRICE_RE = re.compile(r"قیمت(?:‌?ها)?\s*(?:را\s*)?(?:نشان|بذار|بگذار|بزن)|با\s*قیمت")
HIDE_PRICE_RE = re.compile(
    r"قیمت\s*نزن|بدون قیمت|قیمت\s*نذار|قیمت\s*نگذار|پنهان.{0,12}قیمت|قیمت.{0,12}پنهان|مخفی.{0,16}قیمت|قیمت.{0,16}مخفی"
)
FROM_PAGE = ("از پیج", "از داخل پیج", "از کانال", "از اینستا")
CREATE_PAGE_RE = re.compile(r"صفحه.{0,24}(?:بساز|درست کن|اضافه)|(?:بساز|درست کن).{0,24}صفحه")
ADD_PRODUCT_RE = re.compile(
    r"(?:کالا|محصول).{0,48}(?:اضافه|بگذار|بذار)|(?:اضافه|بگذار|بذار).{0,48}(?:کالا|محصول)"
)
ADD_VERB_RE = re.compile(r"اضافه\s*کن")
GOODS_WORDS = ("کفش", "کیف", "کلاه", "لباس", "شال", "ساعت", "عینک", "عطر")
FA_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
REMOVE_PRODUCT_RE = re.compile(r"(?:کالا|محصول).{0,48}(?:حذف|بردار|پاک)")
HEADER_RE = re.compile(r"هدر|منوی بالا|لوگوی هدر")
QUOTED = re.compile(r"[«\"']([^»\"']{1,80})[»\"']")
CTA_RE = re.compile(r"(?:متن دکمه|دکمه).{0,40}(?:بکن|بشود|بشه|عوض کن)\s*[«\"']?(.+?)[»\"']?\s*$")
GREET = frozenset(
    {
        "سلام",
        "درود",
        "خوبی",
        "چطوری",
        "چخبر",
        "چه خبر",
        "مرسی",
        "ممنون",
        "که هستی",
        "تو کی هستی",
        "سلام خوبی",
        "سلام چطوری",
    }
)
CONTINUE = frozenset({"خب", "باشه", "باشه خب", "اوکی", "ok", "okay", "ادامه", "ادامه بده", "بیشتر بگو", "بعدی"})
ADVICE = ("پیشنهاد", "توضیح", "چطور", "چگونه", "به چه شکل")
CLARIFY_PAGE = "کدام صفحه را بسازم: درباره ما، تماس، داستان برند، یا پرسش‌های متداول؟"


def _price_toman(text: str) -> int:
    raw = (text or "").translate(FA_DIGIT).replace("٬", "").replace("\u066c", "").replace("\u066b", ".")
    raw = raw.replace("تومن", "تومان")
    million = re.search(r"(\d+(?:[./]\d+)?)\s*میلیون(?:\s*و\s*(\d+))?", raw)
    if million:
        whole = float(million.group(1).replace("/", "."))
        extra = int(million.group(2) or 0)
        amount = int(round(whole * 1_000_000))
        if extra:
            amount += extra * 1000 if extra < 1000 else extra
        return amount
    thousand = re.search(r"(\d+(?:[./]\d{3})+|\d+(?:[./]\d+)?)\s*هزار", raw)
    if thousand:
        token = thousand.group(1)
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
            return int(re.sub(r"\D", "", token)) * 1000
        if re.fullmatch(r"\d+[./]\d+", token):
            return int(round(float(token.replace("/", ".")) * 1000))
        return int(token) * 1000
    grouped = re.search(r"(\d{1,3}(?:[,.]\d{3})+)", raw)
    if grouped:
        digits = re.sub(r"\D", "", grouped.group(1))
        if len(digits) >= 4:
            return int(digits)
    plain = re.search(r"(\d{4,})", raw)
    if plain:
        return int(plain.group(1))
    short = re.search(r"(?<!\d)(\d{2,4})\s*ت(?!ومان)", raw)
    if short:
        return int(short.group(1)) * 1000
    near = re.search(r"(\d{1,9})\s*تومان", raw)
    return int(near.group(1)) if near else 0


_TITLE_DROP = frozenset(
    {"یک", "یه", "را", "کالا", "محصول", "اضافه", "کن", "کنید", "بگذار", "بذار", "عنوان", "تومان", "تومن", "هزار", "میلیون"}
)
_TITLE_PUNCT = " ،.,:;؛!؟«»\"'`"


def _bare_token(token: str) -> str:
    return (token or "").strip(_TITLE_PUNCT)


def _product_title(text: str) -> str:
    quoted = _quoted(text)
    if quoted:
        return quoted
    cleaned = re.sub(r"(?:با\s+|به\s+)?قیمت.*", "", text or "")
    kept: list[str] = []
    tokens = cleaned.split()
    index = 0
    while index < len(tokens):
        bare = _bare_token(tokens[index])
        nxt = _bare_token(tokens[index + 1]) if index + 1 < len(tokens) else ""
        if bare == "با" and nxt == "عنوان":
            index += 2
            continue
        if not bare or bare in _TITLE_DROP or re.fullmatch(r"[\d۰-۹]+", bare):
            index += 1
            continue
        kept.append(bare)
        index += 1
    return " ".join(kept)[:36]


def _is_product_add(text: str) -> bool:
    blob = text or ""
    if CREATE_PAGE_RE.search(blob):
        return False
    if ADD_PRODUCT_RE.search(blob):
        return True
    if not ADD_VERB_RE.search(blob):
        return False
    if _price_toman(blob) > 0:
        return True
    return any(word in blob for word in GOODS_WORDS)


def catalog_add(text: str) -> dict | None:
    if not _is_product_add(text):
        return None
    title = sanitize_persian(_product_title(text), limit=36)
    if not title:
        return None
    return {"title": title, "price": _price_toman(text)}


def _catalog_title_in(text: str) -> str:
    from app.services.storefront_service import list_products

    titles: list[str] = []
    for row in list_products().get("products") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if len(title) >= 2:
            titles.append(title)
    for title in sorted(titles, key=len, reverse=True):
        if title in text:
            return title
    return ""


def _quoted(text: str) -> str:
    match = QUOTED.search(text or "")
    return match.group(1).strip() if match else ""


def page_kind_from_text(text: str) -> str:
    blob = text or ""
    for kind, hints in PAGE_HINTS:
        if any(hint in blob for hint in hints):
            return kind
    return ""


def _is_question(text: str) -> bool:
    stripped = (text or "").strip()
    if stripped.endswith(("؟", "?")):
        return True
    compact = stripped.replace("؟", "").replace("?", "").strip().lower()
    if compact in CONTINUE:
        return True
    return any(token in stripped for token in ADVICE)


def _wants_hero(text: str, colors: dict) -> bool:
    if "تصویر" in text or "عکس" in text:
        return "بساز" in text or "طراحی" in text
    if "بک گراند" in text or "بک‌گراند" in text:
        return not colors
    return False


def _pinned_write(text: str, target: str, view_path: str) -> list[dict] | None:
    written = write_intent(text)
    quoted = _quoted(text)
    cta = CTA_RE.search(text)
    if cta:
        label = cta.group(1).strip().strip("«»\"'")
        if not label:
            return None
        actions = [{"type": "set_brand", "fields": {"ctaLabelFa": label}}]
        if target:
            actions.append({"type": "replace_text", "find": target, "replace": label})
        return actions
    value = written or (quoted if target else "")
    if not value:
        return None
    if target:
        return [{"type": "replace_text", "find": target, "replace": value}]
    if view_path.rstrip("/") == "/products":
        return [{"type": "replace_text", "find": "", "replace": value, "heading": True}]
    return [{"type": "set_brand", "fields": {"name": value}}]


def classify_actions(prompt: str, view_target: str = "", view_path: str = "") -> list[dict]:
    text = (prompt or "").strip()
    target = (view_target or "").strip()
    if not text and not target:
        return []
    if looks_like_foreign_payload(text):
        reason = "url" if re.search(r"https?://", text) else "token"
        return [{"type": "reject_foreign", "reason": reason}]
    compact = text.replace("؟", "").replace("?", "").strip()
    if compact in GREET or compact.lower() in CONTINUE:
        return [{"type": "greet"}]
    if wants_revert(text):
        return [{"type": "revert"}]
    pinned = _pinned_write(text, target, view_path)
    if pinned is not None:
        return pinned
    actions: list[dict] = []
    if HIDE_PRICE_RE.search(text):
        actions.append({"type": "hide_prices"})
    if SHOW_PRICE_RE.search(text) and not HIDE_PRICE_RE.search(text):
        actions.append({"type": "show_prices"})
    if any(token in text for token in FROM_PAGE):
        actions.append({"type": "catalog_from_page"})
    page_kind = page_kind_from_text(text)
    if CREATE_PAGE_RE.search(text) or (page_kind and any(mark in text for mark in ("بساز", "اضافه"))):
        kind = page_kind
        if kind:
            actions.append({"type": "create_page", "kind": kind, "label": PAGE_LABELS[kind]})
            actions.append(
                {
                    "type": "add_nav_link",
                    "href": f"/{kind}",
                    "label": PAGE_LABELS[kind],
                    "depends_on": f"create_page:{kind}",
                }
            )
        else:
            actions.append({"type": "ask_clarify", "reply": CLARIFY_PAGE})
    added = catalog_add(text)
    if added is not None:
        title = str(added.get("title") or "")
        price = int(added.get("price") or 0)
        if len(title) < 2:
            actions.append({"type": "ask_clarify", "reply": "نام کالا چیست؟"})
        elif price <= 0:
            actions.append({"type": "ask_clarify", "reply": "قیمت تومان را هم بگو تا در کاتالوگ بنویسم."})
        else:
            actions.append({"type": "add_product", "title": title, "price": price})
    wipe_all = "همه" in text and re.search(r"(?:کالا|محصول)", text) and re.search(r"(?:حذف|بردار|پاک)", text)
    if wipe_all:
        pass
    elif REMOVE_PRODUCT_RE.search(text):
        title = _quoted(text) or target
        if title:
            actions.append({"type": "remove_product", "title": title})
        elif catalog_add(text) is None:
            actions.append({"type": "ask_clarify", "reply": "کدام کالا حذف شود؟"})
    elif re.search(r"(?:حذف|بردار|پاک)", text):
        titled = _catalog_title_in(text)
        if titled:
            actions.append({"type": "remove_product", "title": titled})
    if HEADER_RE.search(text) and not CREATE_PAGE_RE.search(text):
        logo = _quoted(text)
        kind = page_kind_from_text(text)
        if logo:
            actions.append({"type": "set_header", "logoFa": logo})
        elif kind:
            actions.append({"type": "add_nav_link", "href": f"/{kind}", "label": PAGE_LABELS[kind]})
        elif "نام" in text or "عنوان" in text:
            actions.append({"type": "ask_clarify", "reply": "متن هدر چه باشد؟"})
    colors = named_color_updates(text)
    if colors:
        actions.append({"type": "set_colors", "colors": colors})
    if _wants_hero(text, colors):
        actions.append({"type": "hero_image"})
    written = write_intent(text)
    quoted = _quoted(text)
    cta = CTA_RE.search(text)
    catalog_turn = any(item.get("type") in {"add_product", "remove_product"} for item in actions)
    if catalog_turn:
        pass
    elif wants_delete_selected(text) and target:
        actions.append({"type": "delete_text", "target": target})
    elif cta:
        label = cta.group(1).strip().strip("«»\"'")
        if label:
            actions.append({"type": "set_brand", "fields": {"ctaLabelFa": label}})
            if target:
                actions.append({"type": "replace_text", "find": target, "replace": label})
    elif written:
        if target:
            actions.append({"type": "replace_text", "find": target, "replace": written})
        else:
            key = "name"
            if view_path.rstrip("/") == "/products":
                actions.append({"type": "replace_text", "find": "", "replace": written, "heading": True})
            else:
                actions.append({"type": "set_brand", "fields": {key: written}})
    elif target and quoted:
        actions.append({"type": "replace_text", "find": target, "replace": quoted})
    elif quoted and ("تیتر" in text or "عنوان" in text) and "هدر" not in text:
        if target or "تیتر" in text:
            actions.append({"type": "replace_text", "find": target or quoted, "replace": quoted})
        else:
            actions.append({"type": "set_brand", "fields": {"name": quoted}})
    elif quoted and ("بنویس" in text or "عوض کن" in text):
        if target:
            actions.append({"type": "replace_text", "find": target, "replace": quoted})
        else:
            actions.append({"type": "set_brand", "fields": {"name": quoted}})

    cleaned: list[dict] = []
    for item in actions:
        if item.get("type") == "set_brand" and not item.get("fields"):
            continue
        cleaned.append(item)
    actions = cleaned
    if actions:
        return actions
    if _is_question(text) and not target:
        return [{"type": "answer"}]
    if "صفحه" in text and not page_kind_from_text(text):
        return [{"type": "ask_clarify", "reply": CLARIFY_PAGE}]
    if compact.lower() in CONTINUE:
        return [{"type": "answer"}]
    return [{"type": "edit_llm"}]
