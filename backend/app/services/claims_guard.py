"""Shared check for product claims that are not in the seller's facts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

PROMPT = """فقط یک شیء JSON با کلید claims.
claims فهرست عبارت‌هایی از متن است که ویژگی کالا را ادعا می‌کنند و آن ویژگی در facts نیست.
ویژگی یعنی جنس، اجزا، اندازه، دوام، اصالت، موجودی، ارسال، ضمانت، قیمت، حکاکی، جیب، بند.
اصیل، اصل، طبیعی، مقاوم، قابل تنظیم و حکاکی اگر در facts نیستند ویژگی‌اند.
حس، سبک و زیبایی ادعا نیستند.
اگر ادعایی نیست claims را [] بگذار.
هر عبارت را دقیق از خود متن کپی کن."""


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
    return [str(item).strip() for item in claims if str(item).strip()]
