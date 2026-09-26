from __future__ import annotations

from pathlib import Path

import httpx

from app.services import inbox_service
from app.services.channel_http import async_client
from app.state_store import read_json, write_json

API = "https://api.telegram.org"


def _offset_state() -> dict:
    data = read_json("telegram-offset.json", {})
    return data if isinstance(data, dict) else {}


def _save_offset(data: dict) -> None:
    write_json("telegram-offset.json", data)


def _seen() -> set[str]:
    rows = read_json("tg-seen.json", [])
    return {str(item) for item in rows} if isinstance(rows, list) else set()


def _mark(ids: list[str]) -> None:
    seen = _seen()
    seen.update(ids)
    write_json("tg-seen.json", sorted(seen)[-800:])


def _client():
    return async_client(timeout=25)


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def send_photo(*, token: str, chat_id: str, path, caption: str = "") -> None:
    token = token.strip()
    chat_id = str(chat_id or "").strip()
    if not token:
        raise ValueError("توکن بات تلگرام نیست")
    if not chat_id:
        raise ValueError("مقصد پست تلگرام نیست. آیدی کانال را در کانال‌ها بگذار.")
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError("فایل تصویر برای تلگرام پیدا نشد")
    data = {"chat_id": chat_id, "caption": (caption or "")[:1024]}
    mime = "image/jpeg" if file_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    with file_path.open("rb") as handle:
        async with _client() as client:
            response = await client.post(
                f"{API}/bot{token}/sendPhoto",
                data=data,
                files={"photo": (file_path.name, handle, mime)},
            )
    payload = _json(response)
    if response.status_code >= 400 or payload.get("ok") is not True:
        raise ValueError("تلگرام تصویر را نفرستاد. بات باید ادمین کانال باشد.")


async def send_video(*, token: str, chat_id: str, path, caption: str = "") -> None:
    token = token.strip()
    chat_id = str(chat_id or "").strip()
    if not token:
        raise ValueError("توکن بات تلگرام نیست")
    if not chat_id:
        raise ValueError("مقصد پست تلگرام نیست. آیدی کانال را در کانال‌ها بگذار.")
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError("فایل ویدیو برای تلگرام پیدا نشد")
    data = {"chat_id": chat_id, "caption": (caption or "")[:1024]}
    with file_path.open("rb") as handle:
        async with _client() as client:
            response = await client.post(
                f"{API}/bot{token}/sendVideo",
                data=data,
                files={"video": (file_path.name, handle, "video/mp4")},
            )
    payload = _json(response)
    if response.status_code >= 400 or payload.get("ok") is not True:
        raise ValueError("تلگرام ویدیو را نفرستاد. بات باید ادمین کانال باشد.")


async def send_message(*, token: str, chat_id: str, text: str) -> None:
    token = token.strip()
    chat_id = str(chat_id or "").strip()
    body = text.strip()
    if not token:
        raise ValueError("توکن بات تلگرام نیست")
    if not chat_id:
        raise ValueError("شناسه گفتگوی تلگرام نیست. مشتری باید اول پیام بدهد.")
    if not body:
        raise ValueError("متن پاسخ خالی است")
    async with _client() as client:
        response = await client.post(
            f"{API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": body[:4000]},
        )
    payload = _json(response)
    if response.status_code >= 400 or payload.get("ok") is not True:
        raise ValueError("تلگرام پیام را نفرستاد. توکن و گفتگو را دوباره وصل کن.")


async def _ensure_polling(client: httpx.AsyncClient, token: str, state: dict) -> dict:
    if state.get("webhookCleared"):
        return state
    response = await client.post(f"{API}/bot{token}/deleteWebhook", json={"drop_pending_updates": False})
    payload = _json(response)
    if response.status_code >= 400 or payload.get("ok") is not True:
        raise ValueError("وب‌هوک تلگرام پاک نشد؛ getUpdates کار نمی‌کند.")
    state["webhookCleared"] = True
    _save_offset(state)
    return state


async def _download_file(*, token: str, file_id: str, kind_hint: str) -> dict | None:
    from app.services.inbound_media_service import fetch_and_store

    ident = str(file_id or "").strip()
    if not ident:
        return None
    try:
        async with _client() as client:
            response = await client.post(f"{API}/bot{token}/getFile", json={"file_id": ident})
        payload = _json(response)
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        path = str(result.get("file_path") or "").lstrip("/")
        if not path or response.status_code >= 400:
            return None
        return await fetch_and_store(f"{API}/file/bot{token}/{path}", kind_hint=kind_hint)
    except Exception:
        return None


async def media_from_message(message: dict, *, token: str) -> tuple[str, dict | None]:
    from app.services import chat_media_service

    caption = str(message.get("caption") or "").strip()
    text = str(message.get("text") or "").strip()
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        last = photos[-1] if isinstance(photos[-1], dict) else {}
        media = await _download_file(token=token, file_id=str(last.get("file_id") or ""), kind_hint="image")
        return caption or text, media
    if isinstance(message.get("sticker"), dict):
        return caption or text or "(استیکر)", None
    mapping = (
        ("voice", "audio"),
        ("audio", "audio"),
        ("video", "video"),
        ("video_note", "video"),
        ("document", ""),
    )
    for key, hint in mapping:
        item = message.get(key)
        if not isinstance(item, dict):
            continue
        kind = hint
        if key == "document":
            kind = chat_media_service.kind_of(str(item.get("mime_type") or ""), str(item.get("file_name") or "")) or ""
            if kind not in {"image", "video", "audio"}:
                return caption or text or "(فایل)", None
        media = await _download_file(token=token, file_id=str(item.get("file_id") or ""), kind_hint=kind)
        return caption or text, media
    return text, None


async def pull_updates(*, token: str, handle: str = "") -> dict:
    token = token.strip()
    if not token:
        return {"ok": False, "error": "توکن بات تلگرام نیست", "imported": 0}
    state = _offset_state()
    offset = int(state.get("offset") or 0)
    imported = 0
    seen = _seen()
    try:
        async with _client() as client:
            state = await _ensure_polling(client, token, state)
            me = await client.get(f"{API}/bot{token}/getMe")
            me_payload = _json(me)
            bot = me_payload.get("result") if isinstance(me_payload.get("result"), dict) else {}
            bot_id = str(bot.get("id") or state.get("botId") or "")
            if bot_id:
                state["botId"] = bot_id
            response = await client.post(
                f"{API}/bot{token}/getUpdates",
                json={"offset": offset, "timeout": 1, "allowed_updates": ["message"]},
            )
            payload = _json(response)
    except ValueError as exc:
        return {"ok": False, "imported": 0, "error": str(exc)}
    except Exception:
        return {"ok": False, "imported": 0, "error": "خواندن تلگرام به شبکه نرسید."}
    if response.status_code == 409 or payload.get("error_code") == 409:
        return {
            "ok": False,
            "imported": 0,
            "error": "ربات جای دیگری هم پیام می‌خواند. همان بات را فقط در سوزان وصل کن.",
        }
    if response.status_code >= 400 or payload.get("ok") is not True:
        return {"ok": False, "imported": 0, "error": "توکن تلگرام پیام‌ها را نداد. از BotFather دوباره کپی کن."}
    rows = payload.get("result") if isinstance(payload.get("result"), list) else []
    next_offset = offset
    for row in rows:
        if not isinstance(row, dict):
            continue
        update_id = int(row.get("update_id") or 0)
        if update_id:
            next_offset = max(next_offset, update_id + 1)
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        if not message:
            continue
        mid = str(message.get("message_id") or "")
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        from_user = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = str(chat.get("id") or "")
        sender_id = str(from_user.get("id") or "")
        sender = str(from_user.get("username") or from_user.get("first_name") or handle or "مشتری")
        if not mid or not chat_id:
            continue
        if str(chat.get("type") or "private").lower() != "private":
            continue
        if bot_id and sender_id == bot_id:
            continue
        key = f"{chat_id}:{mid}"
        if key in seen:
            continue
        text, media = await media_from_message(message, token=token)
        if not text and not media:
            continue
        await inbox_service.handle_inbound(
            platform="telegram",
            sender=sender,
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            external_id=key,
            media=media,
        )
        _mark([key])
        seen.add(key)
        imported += 1
    if next_offset != offset or bot_id:
        state["offset"] = next_offset
        _save_offset(state)
    return {"ok": True, "imported": imported}
