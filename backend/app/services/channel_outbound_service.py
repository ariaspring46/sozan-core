from __future__ import annotations

from app.services import channel_service, sendbox_service, telegram_service


async def deliver(*, platform: str, sender_id: str, chat_id: str, text: str) -> None:
    key = platform.strip().lower()
    row = channel_service.account_for_platform(key)
    if row is None:
        raise ValueError("حساب این کانال وصل نیست")
    token = channel_service.token_for(row)
    if key == "telegram":
        await telegram_service.send_message(token=token, chat_id=chat_id, text=text)
        return
    if key == "instagram":
        sendbox_id = channel_service.sendbox_account_id(row)
        if sendbox_id:
            await sendbox_service.send_message(account_id=sendbox_id, recipient_id=sender_id or chat_id, text=text)
            return
        raise ValueError(channel_service.IG_RECONNECT)
    raise ValueError("ارسال پاسخ روی این کانال هنوز وصل نیست")
