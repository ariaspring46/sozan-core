"""هشدار تلگرام به مالک: تیکت تازهٔ فروشنده و رویدادهای بحرانی.

کلید `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` در env هاب است (مالک می‌گذارد)؛
بی‌کلید همه‌چیز بی‌اثر است. ارسال از همان مسیر کانال است (پروکسی خارجی با پشتیبان)؛
هرگز متن مشتری یا شماره در پیام نمی‌آید.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.services.channel_http import async_client
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.alerts")

TIMEOUT = 8.0


def configured() -> bool:
    return bool(_token()) and bool(_chat_id())


def _token() -> str:
    return str(getattr(settings, "telegram_bot_token", "") or "").strip()


def _chat_id() -> str:
    return str(getattr(settings, "telegram_chat_id", "") or "").strip()


async def send(text: str) -> bool:
    """یک پیام به چت مالک؛ بی‌کلید False و بدون هشدار."""
    if not configured():
        return False
    try:
        async with async_client(timeout=TIMEOUT) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{_token()}/sendMessage",
                json={"chat_id": _chat_id(), "text": text[:3500]},
            )
        return response.status_code < 400
    except Exception as exc:
        log.warning("telegram alert failed: %s", type(exc).__name__)
        return False


async def seller_ticket_alert(ticket_id: str, subject: str, tenant: str) -> None:
    ok = await send(
        "تیکت تازه از فروشنده\n"
        f"شناسه: {ticket_id}\n"
        f"موضوع: {subject[:80]}\n"
        f"فروشنده: {str(tenant)[:4]}***\n"
        "پاسخ در پنل ← پشتیبانی و رسیدها."
    )
    emit_later(
        kind="support",
        title="seller-ticket-alert",
        surface="panel",
        status="ok" if ok else "skipped",
        payload={"sent": ok},
    )
