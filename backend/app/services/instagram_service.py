from __future__ import annotations

import asyncio

import httpx

from app.services import inbox_service
from app.services.channel_http import async_client
from app.state_store import read_json, write_json

GRAPH = "https://graph.instagram.com/v21.0"


def _seen() -> set[str]:
    rows = read_json("ig-seen.json", [])
    return {str(item) for item in rows} if isinstance(rows, list) else set()


def _mark(ids: list[str]) -> None:
    seen = _seen()
    seen.update(ids)
    write_json("ig-seen.json", sorted(seen)[-400:])


async def media_from_graph_message(msg: dict) -> dict | None:
    from app.services.inbound_media_service import fetch_and_store

    blob = msg.get("attachments")
    rows = blob.get("data") if isinstance(blob, dict) else blob
    if not isinstance(rows, list):
        return None
    for item in rows:
        if not isinstance(item, dict):
            continue
        image = item.get("image_data") if isinstance(item.get("image_data"), dict) else {}
        video = item.get("video_data") if isinstance(item.get("video_data"), dict) else {}
        url = str(image.get("url") or video.get("url") or item.get("url") or item.get("file_url") or "").strip()
        hint = "video" if video.get("url") else "image"
        if url:
            stored = await fetch_and_store(url, kind_hint=hint)
            if stored:
                return stored
    return None


def _client():
    return async_client(timeout=20)


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _graph_error(payload: dict, fallback: str) -> str:
    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = err.get("code")
    message = str(err.get("message") or "")
    if code in {10, 190, 200} or "permission" in message.lower() or "publish" in message.lower():
        return "توکن اینستاگرام مجوز انتشار محتوا ندارد. در Meta مجوز instagram_content_publish را بده."
    if code in {2207020, 2207050, 9004}:
        return "اینستاگرام فایل را نپذیرفت. تصویر باید JPEG/PNG عمومی باشد و ویدیو ریل باشد."
    return fallback


async def _ig_user_id(client: httpx.AsyncClient, token: str) -> str:
    response = await client.get(
        f"{GRAPH}/me",
        params={"fields": "id,username"},
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = _json(response)
    user_id = str(payload.get("id") or "")
    if response.status_code >= 400 or not user_id:
        raise ValueError(_graph_error(payload, "توکن اینستاگرام صفحه را نداد. حساب حرفه‌ای را دوباره وصل کن."))
    return user_id


async def _create_and_publish(*, token: str, body: dict, timeout: float, poll: bool) -> None:
    token = token.strip()
    if not token:
        raise ValueError("توکن اینستاگرام نیست")
    headers = {"Authorization": f"Bearer {token}"}
    async with async_client(timeout=timeout) as client:
        user_id = await _ig_user_id(client, token)
        created = await client.post(f"{GRAPH}/{user_id}/media", headers=headers, json=body)
        payload = _json(created)
        creation_id = str(payload.get("id") or "")
        if created.status_code >= 400 or not creation_id:
            raise ValueError(_graph_error(payload, "اینستاگرام کانتینر پست را نساخت."))
        if poll:
            status_code = ""
            for _ in range(30):
                check = await client.get(
                    f"{GRAPH}/{creation_id}",
                    params={"fields": "status_code,status"},
                    headers=headers,
                )
                info = _json(check)
                status_code = str(info.get("status_code") or "").upper()
                if status_code == "FINISHED":
                    break
                if status_code in {"ERROR", "EXPIRED"}:
                    raise ValueError("اینستاگرام ویدیو را پردازش نکرد. فایل را کوتاه‌تر یا MP4 بفرست.")
                await asyncio.sleep(2)
            if status_code != "FINISHED":
                raise ValueError("پردازش ریل اینستاگرام طول کشید. کمی بعد دوباره بفرست.")
        published = await client.post(
            f"{GRAPH}/{user_id}/media_publish",
            headers=headers,
            json={"creation_id": creation_id},
        )
        result = _json(published)
        if published.status_code >= 400 or not result.get("id"):
            raise ValueError(_graph_error(result, "اینستاگرام پست را منتشر نکرد."))


async def publish_image(*, token: str, image_url: str, caption: str = "") -> None:
    url = str(image_url or "").strip()
    if not url.startswith("https://"):
        raise ValueError("اینستاگرام فقط نشانی HTTPS عمومی تصویر را می‌گیرد.")
    await _create_and_publish(
        token=token,
        body={"image_url": url, "caption": (caption or "")[:2200]},
        timeout=40,
        poll=False,
    )


async def publish_reel(*, token: str, video_url: str, caption: str = "") -> None:
    url = str(video_url or "").strip()
    if not url.startswith("https://"):
        raise ValueError("اینستاگرام فقط نشانی HTTPS عمومی ویدیو را می‌گیرد.")
    await _create_and_publish(
        token=token,
        body={"media_type": "REELS", "video_url": url, "caption": (caption or "")[:2200]},
        timeout=90,
        poll=True,
    )


async def send_message(*, token: str, recipient_id: str, text: str) -> None:
    token = token.strip()
    recipient_id = str(recipient_id or "").strip()
    body = text.strip()
    if not token:
        raise ValueError("توکن اینستاگرام نیست")
    if not recipient_id:
        raise ValueError("شناسه دایرکت اینستاگرام نیست. اول پیام مشتری را همگام کن.")
    if not body:
        raise ValueError("متن پاسخ خالی است")
    async with _client() as client:
        response = await client.post(
            f"{GRAPH}/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"recipient": {"id": recipient_id}, "message": {"text": body[:1000]}},
        )
    if response.status_code >= 400:
        raise ValueError("اینستاگرام پیام را نفرستاد. توکن حرفه‌ای با مجوز پیام لازم است.")


async def pull_directs(*, token: str, handle: str) -> dict:
    token = token.strip()
    if not token:
        return {"ok": False, "error": "توکن اینستاگرام نیست", "imported": 0}
    headers = {"Authorization": f"Bearer {token}"}
    imported = 0
    seen = _seen()
    try:
        async with _client() as client:
            me = await client.get(f"{GRAPH}/me", params={"fields": "id,username"}, headers=headers)
            if me.status_code >= 400:
                return {
                    "ok": False,
                    "imported": 0,
                    "error": "توکن دایرکت اینستاگرام قبول نشد. توکن حرفه‌ای با مجوز پیام لازم است.",
                }
            try:
                me_payload = me.json()
            except ValueError:
                me_payload = {}
            me_payload = me_payload if isinstance(me_payload, dict) else {}
            me_id = str(me_payload.get("id") or "")
            conv = await client.get(
                f"{GRAPH}/me/conversations",
                params={"fields": "id,messages{id,message,from,created_time,attachments}"},
                headers=headers,
            )
            payload = conv.json() if conv.status_code < 400 else {}
    except Exception:
        return {"ok": False, "imported": 0, "error": "خواندن دایرکت اینستاگرام به شبکه نرسید."}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return {
            "ok": False,
            "imported": 0,
            "error": "اینستاگرام گفتگویی نداد. حساب باید حرفه‌ای و به پیام وصل باشد.",
        }
    for thread in data:
        messages = ((thread.get("messages") or {}).get("data") or []) if isinstance(thread, dict) else []
        for msg in reversed(messages):
            mid = str(msg.get("id") or "")
            text = str(msg.get("message") or "").strip()
            from_user = msg.get("from") if isinstance(msg.get("from"), dict) else {}
            sender_id = str(from_user.get("id") or "")
            sender = str(from_user.get("username") or sender_id or "مشتری")
            if not mid or mid in seen:
                continue
            if me_id and sender_id == me_id:
                continue
            if handle and sender.lstrip("@") == handle.lstrip("@") and not sender_id:
                continue
            media = await media_from_graph_message(msg)
            if not text and not media:
                continue
            await inbox_service.handle_inbound(
                platform="instagram",
                sender=sender,
                text=text,
                sender_id=sender_id,
                external_id=mid,
                media=media,
            )
            _mark([mid])
            seen.add(mid)
            imported += 1
    return {"ok": True, "imported": imported}
