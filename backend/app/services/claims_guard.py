"""Shared check for product claims that are not in the seller's facts."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

PROMPT = """فقط یک شیء JSON با کلید claims.
claims فهرست عبارت‌هایی از متن است که ویژگی کالا را ادعا می‌کنند و آن ویژگی در facts نیست.
ویژگی یعنی جنس، اجزا، اندازه، دوام، اصالت، موجودی، ارسال، ضمانت، قیمت، حکاکی، جیب، بند.
اصیل، اصل، طبیعی، مقاوم، قابل تنظیم و حکاکی اگر در facts نیستند ویژگی‌اند.
نرم، محکم، دوخت محکم، بادوام، ایمن، استاندارد، ضدآب و ضدحساسیت هم اگر در facts نیستند ویژگی‌اند، حتی برای عروسک و لباس و کفش.
حس، سبک و زیبایی ادعا نیستند.
اگر ادعایی نیست claims را [] بگذار.
هر عبارت را دقیق از خود متن کپی کن."""


_STOP = frozenset("بودن است دارد دارند شود میشود باشد با که این آن را از در به برای هم تا یا ما شما بگو بنویس".split())


def _flat(text: str) -> str:
    return (text or "").replace("\u200c", "")


def backed(claim: str, facts: str) -> bool:
    """A phrase the seller said themselves is not an outside claim: the judge model sometimes flags «ضدآب است» although
    the seller's own message says it. Every content word of the claim must be in the facts («ارسال رایگان» is not backed by «ارسال»)."""
    flat = _flat(facts)
    words = [word for word in re.split(r"[^\w]+", _flat(claim)) if len(word) >= 3 and word not in _STOP]
    return bool(words) and all(word in flat for word in words)


async def check(
    text: str,
    facts: str,
    complete: Callable[..., Awaitable[dict]] | None = None,
) -> list[str]:
    if not (text or "").strip():
        return []
    if complete is None:
        from app.services.llm import complete_json as complete
    try:
        parsed = await complete(
            PROMPT,
            f"facts:\n{facts}\n\nمتن:\n{text}",
            surface="studio",
            max_tokens=400,
        )
    except Exception:
        return []
    claims = parsed.get("claims") if isinstance(parsed, dict) else None
    if not isinstance(claims, list):
        return []
    return [text for text in (str(item).strip() for item in claims) if text and not backed(text, facts)]
