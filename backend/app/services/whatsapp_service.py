from __future__ import annotations

from pathlib import Path

import httpx

from app.services.channel_http import async_client

GRAPH = "https://graph.facebook.com/v21.0"

MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
}


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _digits(raw: str) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def _graph_error(payload: dict, fallback: str) -> str:
    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = err.get("code")
    if code in {131047, 131048}:
        return "واتساپ خارج از پنجرهٔ ۲۴ساعته است. مشتری باید اول پیام بدهد یا قالب تأییدشده بسازی."
    if code in {100, 190, 10}:
        return "توکن واتساپ قبول نشد. Phone Number ID و توکن سیستم‌یوزر را دوباره وصل کن."
    return fallback


async def send_media(
    *,
    token: str,
    phone_number_id: str,
    to: str,
    path,
    caption: str = "",
) -> None:
    token = token.strip()
    phone_id = str(phone_number_id or "").strip()
    dest = _digits(to)
    if not token or not phone_id:
        raise ValueError("واتساپ وصل نیست. Phone Number ID و توکن را در کانال‌ها بگذار.")
    if not dest:
        raise ValueError("شماره مقصد واتساپ نیست. در کانال‌ها مقصد ارسال را بگذار.")
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError("فایل برای واتساپ پیدا نشد")
    mime = MIME.get(file_path.suffix.lower()) or "application/octet-stream"
    kind = "video" if mime.startswith("video/") else "image"
    headers = {"Authorization": f"Bearer {token}"}
    async with async_client(timeout=60) as client:
        with file_path.open("rb") as handle:
            uploaded = await client.post(
                f"{GRAPH}/{phone_id}/media",
                headers=headers,
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (file_path.name, handle, mime)},
            )
        payload = _json(uploaded)
        media_id = str(payload.get("id") or "")
        if uploaded.status_code >= 400 or not media_id:
            raise ValueError(_graph_error(payload, "واتساپ فایل را آپلود نکرد."))
        media_body = {"id": media_id}
        if caption.strip():
            media_body["caption"] = caption.strip()[:1024]
        sent = await client.post(
            f"{GRAPH}/{phone_id}/messages",
            headers=headers,
            json={
                "messaging_product": "whatsapp",
                "to": dest,
                "type": kind,
                kind: media_body,
            },
        )
        result = _json(sent)
        messages = result.get("messages") if isinstance(result.get("messages"), list) else []
        if sent.status_code >= 400 or not messages:
            raise ValueError(_graph_error(result, "واتساپ پیام را نفرستاد."))
