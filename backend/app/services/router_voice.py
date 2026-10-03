"""The router's words: the gate decides and checks the facts, the model says them (see shop_voice_service.say)."""

from __future__ import annotations

import re

from app.services import router_text, shop_voice_service

HOSTILE = re.compile(r"ignore|system prompt|پرامپت|دستورالعمل|jailbreak|\bdan\b|فراموش کن|secret|token|api[_-]?key", re.I)
NEVER = re.compile(r"secret|jwt|api[_-]?key|otp|read_env|\bsql\b|token", re.I)


# «قیمت‌ها توی پیجمه»، «از پیجم قیمتا رو بردار»، «اسکن چی شد»: the answer is what the page scan really found, not a promise
_PAGE_PRICES = re.compile(
    r"قیمت\S*.{0,40}(?:پیج|صفحه|اینستا|ایستا)|(?:پیج|صفحه|اینستا|ایستا).{0,40}قیمت|قیمت\S*.{0,30}(?:بردار|بخون|بگیر)|(?:بردار|بخون|بگیر).{0,15}قیمت|اسکن.{0,12}(?:چی|چه|شد|نتیجه|تموم)"
)


def page_prices_reply(spoken: str) -> str:
    """The honest scan outcome when the seller says the prices are on their page (or asks about the scan) and nothing was read from it."""
    if not _PAGE_PRICES.search(spoken or ""):
        return ""
    from app.services import channel_scan_service, storefront_service

    if any(row.get("source") for row in storefront_service.list_products().get("products") or []):
        return ""  # a page that gave products: the model can talk about them
    return channel_scan_service.scan_outcome()


def with_scan(text: str, shop: dict) -> str:
    """For a shop that is not built yet, the model is told what the page scan really found (so it never promises prices from an empty page)."""
    if str(shop.get("slug") or "").strip():
        return text
    from app.services.channel_scan_service import scan_outcome

    return f"{text} · {scan_outcome()}"


def names_a_page(text: str) -> bool:
    """A page name typed in the chat is the shop chat's business: it scans that page."""
    from app.services.channel_scan_service import handle_in_text

    return bool(handle_in_text(text))


def build_card(spoken: str, built: bool) -> str:
    from app.services.shop_service import explicit_rebuild

    return "فروشگاه از نو ساخته شود؟" if built or explicit_rebuild(spoken) else "ساخت فروشگاه شروع شود؟"


_ASKS_ABOUT_ITSELF = re.compile(r"می[\s\u200c]?خواه?(?:ی|ید)|لازم\s*داری")


def asks_about_itself(text: str) -> bool:
    """«قیمت چیو میخوای؟» is about Sozan's own words, not a price lookup."""
    return bool(_ASKS_ABOUT_ITSELF.search(text or ""))


def is_hostile(spoken: str) -> bool:
    from app.services.turn_parse import parse_turn

    text = spoken or ""
    return bool(
        HOSTILE.search(text)
        or NEVER.search(text)
        or router_text.has_payment_number(text)
        or parse_turn(text).topic in {"secret", "shaba", "other_shop"}
    )


async def voice(spoken: str, text: str, situation: str, rows: list[dict]) -> str:
    """The model's wording of `text`; a refusal is worded from the facts alone (the seller's words may be an attack).
    Without a model, or over the AI budget, the plain text is shown."""
    plain = str(text or "")
    if not plain.strip():
        return plain
    hostile = is_hostile(spoken)
    return await shop_voice_service.say(
        situation,
        [plain],
        seller_text="" if hostile else spoken,
        fallback=plain,
        recent=None if hostile else [row for row in rows[-6:] if isinstance(row, dict)],
    )
