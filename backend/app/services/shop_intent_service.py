from __future__ import annotations

import re

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
SHOW_PRICE_RE = re.compile(r"قیمت\s*(?:را\s*)?(?:نشان|بذار|بگذار|بزن)|با\s*قیمت")
HIDE_PRICE_RE = re.compile(r"قیمت\s*نزن|بدون قیمت|قیمت\s*نذار|قیمت\s*نگذار|پنهان.{0,12}قیمت|قیمت.{0,12}پنهان")
FROM_PAGE = ("از پیج", "از داخل پیج", "از کانال", "از اینستا")
CREATE_PAGE_RE = re.compile(r"صفحه.{0,24}(?:بساز|درست کن|اضافه)|(?:بساز|درست کن).{0,24}صفحه")
ADD_PRODUCT_RE = re.compile(
    r"(?:کالا|محصول).{0,48}(?:اضافه|بگذار|بذار)|(?:اضافه|بگذار|بذار).{0,48}(?:کالا|محصول)"
)
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
    actions: list[dict] = []
    if HIDE_PRICE_RE.search(text):
        actions.append({"type": "hide_prices"})
    if SHOW_PRICE_RE.search(text) and not HIDE_PRICE_RE.search(text):
        actions.append({"type": "show_prices"})
    if any(token in text for token in FROM_PAGE):
        actions.append({"type": "catalog_from_page"})
    if CREATE_PAGE_RE.search(text):
        kind = page_kind_from_text(text)
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
    if ADD_PRODUCT_RE.search(text):
        title = _quoted(text)
        if not title:
            cleaned = re.sub(r"قیمت.*", "", text)
            cleaned = re.sub(r"(?:کالا|محصول|اضافه کن|اضافه|بگذار|بذار|با عنوان)", " ", cleaned)
            title = re.sub(r"\s+", " ", cleaned).strip()[:36]
        if title and len(title) >= 2:
            price_match = re.search(r"(\d[\d,]{2,})", text)
            price = int(price_match.group(1).replace(",", "")) if price_match else 0
            actions.append({"type": "add_product", "title": title, "price": price})
        else:
            actions.append({"type": "ask_clarify", "reply": "نام کالا چیست؟"})
    if REMOVE_PRODUCT_RE.search(text):
        title = _quoted(text) or target
        if title:
            actions.append({"type": "remove_product", "title": title})
        elif not ADD_PRODUCT_RE.search(text):
            actions.append({"type": "ask_clarify", "reply": "کدام کالا حذف شود؟"})
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
    if compact.lower() in CONTINUE:
        return [{"type": "answer"}]
    return [{"type": "edit_llm"}]
