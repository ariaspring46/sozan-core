from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import settings
from app.services import channel_service, inbox_service, plan_service
from app.state_store import iter_tenants, read_json, tenant_scope, write_json

LINK_TTL_MIN = 15


def configured() -> bool:
    return bool(base_url() and api_key())


def base_url() -> str:
    raw = (settings.unipile_dsn or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    return raw.rstrip("/")


def api_key() -> str:
    return (settings.unipile_api_key or "").strip()


def notify_secret() -> str:
    return hmac.new(settings.jwt_secret.encode(), b"unipile-notify", hashlib.sha256).hexdigest()


def notify_token_for(phone: str) -> str:
    tenant = phone.strip()
    return hmac.new(settings.jwt_secret.encode(), f"unipile-notify:{tenant}".encode(), hashlib.sha256).hexdigest()


def valid_notify_token(token: str, phone: str = "") -> bool:
    got = str(token or "").strip()
    if not got:
        return False
    tenant = str(phone or "").strip()
    if tenant:
        return hmac.compare_digest(got, notify_token_for(tenant))
    return hmac.compare_digest(got, notify_secret())


def notify_url(phone: str = "") -> str:
    origin = (settings.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    tenant = phone.strip()
    if tenant:
        token = notify_token_for(tenant)
        return f"{origin}/channels/unipile/notify?token={token}&tenant={quote(tenant, safe='')}"
    return f"{origin}/channels/unipile/notify?token={notify_secret()}"


def webhook_secret() -> str:
    return hmac.new(settings.jwt_secret.encode(), b"unipile-webhook", hashlib.sha256).hexdigest()


def valid_webhook_token(token: str) -> bool:
    got = str(token or "").strip()
    want = webhook_secret()
    return bool(got) and hmac.compare_digest(got, want)


def webhook_url() -> str:
    origin = (settings.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{origin}/channels/unipile/webhook?token={webhook_secret()}"


def panel_channels_url(query: str) -> str:
    base = (settings.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/more/channels?{query}"


def _expires_on() -> str:
    stamp = datetime.now(UTC) + timedelta(minutes=LINK_TTL_MIN)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(stamp.microsecond / 1000):03d}Z"


def _headers() -> dict[str, str]:
    return {"X-API-KEY": api_key(), "accept": "application/json"}


def http_proxy() -> str | None:
    raw = (settings.unipile_proxy or "").strip()
    return raw or None


def _client(*, timeout: float = 30) -> httpx.AsyncClient:
    # Hub Iran egress stalls the DSN. Dedicated SOCKS on the hub must exit via
    # the OVH Tailscale node; CHANNEL_PROXY/home reverse-SSH is not this path.
    return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=http_proxy())


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _error(payload: dict, fallback: str) -> str:
    if isinstance(payload, dict) and (payload.get("type") or payload.get("status") or payload.get("detail")):
        return fallback
    return fallback


def _attachment_kind(raw: str) -> str:
    blob = (raw or "").lower()
    if "video" in blob:
        return "video"
    if "audio" in blob or "voice" in blob:
        return "audio"
    return "image"


async def _download_attachment(message_id: str, attachment_id: str, kind_hint: str) -> dict | None:
    from app.services import chat_media_service

    mid = str(message_id or "").strip()
    att = str(attachment_id or "").strip()
    if not mid or not att or not base_url():
        return None
    try:
        async with _client(timeout=40) as client:
            response = await client.get(
                f"{base_url()}/api/v1/messages/{mid}/attachments/{att}",
                headers=_headers(),
            )
        if response.status_code >= 400 or not response.content:
            return None
        mime = (response.headers.get("content-type") or "").split(";")[0].strip()
        kind = chat_media_service.kind_of(mime, att) or kind_hint or "image"
        cap = chat_media_service.KIND_MAX.get(kind, 8_000_000)
        data = response.content[: cap + 1]
        if len(data) > cap:
            return None
        return chat_media_service.save(att, data, mime or f"{kind}/*")
    except Exception:
        return None


async def media_from_payload(payload: dict, *, message_id: str = "") -> dict | None:
    from app.services.inbound_media_service import fetch_and_store

    body = payload if isinstance(payload, dict) else {}
    attachments = body.get("attachments")
    if isinstance(attachments, dict):
        attachments = [attachments]
    if not isinstance(attachments, list):
        item = body.get("attachment")
        attachments = [item] if isinstance(item, dict) else []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        hint = _attachment_kind(str(item.get("type") or item.get("mimetype") or item.get("mime") or ""))
        url = str(item.get("url") or item.get("gif") or item.get("attachment_url") or "").strip()
        if url:
            stored = await fetch_and_store(url, kind_hint=hint)
            if stored:
                return stored
        att_id = str(item.get("id") or item.get("attachment_id") or "").strip()
        if att_id:
            stored = await _download_attachment(message_id or str(body.get("message_id") or ""), att_id, hint)
            if stored:
                return stored
    return None


def instagram_handle(account: dict) -> tuple[str, str]:
    params = account.get("connection_params") if isinstance(account.get("connection_params"), dict) else {}
    im = params.get("im") if isinstance(params.get("im"), dict) else {}
    handle = str(im.get("username") or account.get("name") or "").lstrip("@")
    user_id = str(im.get("id") or account.get("id") or "").strip()
    return handle, user_id


def _seen() -> set[str]:
    rows = read_json("unipile-seen.json", [])
    return {str(item) for item in rows} if isinstance(rows, list) else set()


def _mark(ids: list[str]) -> None:
    seen = _seen()
    seen.update(ids)
    write_json("unipile-seen.json", sorted(seen)[-400:])


def _items(payload: dict) -> list:
    rows = payload.get("items")
    if isinstance(rows, list):
        return rows
    rows = payload.get("data")
    return rows if isinstance(rows, list) else []


async def start_instagram(*, phone: str) -> dict:
    if not configured():
        raise ValueError("اتصال یونى‌پایل هنوز در سوزان تنظیم نشده.")
    tenant = phone.strip()
    if not tenant:
        raise ValueError("فروشنده برای ورود اینستاگرام شناخته نشد. دوباره وارد پنل شو.")
    payload = {
        "type": "create",
        "providers": ["INSTAGRAM"],
        "api_url": base_url(),
        "expiresOn": _expires_on(),
        "name": tenant,
        "notify_url": notify_url(tenant),
        "success_redirect_url": panel_channels_url("instagram=ok"),
        "failure_redirect_url": panel_channels_url("instagram=error"),
        "bypass_success_screen": True,
    }
    async with _client() as client:
        response = await client.post(
            f"{base_url()}/api/v1/hosted/accounts/link",
            headers={**_headers(), "content-type": "application/json"},
            json=payload,
        )
    body = _json(response)
    url = str(body.get("url") or "").strip()
    if response.status_code >= 400 or not url:
        raise ValueError(_error(body, "یونى‌پایل نشانی ورود اینستاگرام را نداد. کمی بعد دوباره امتحان کن."))
    return {"configured": True, "provider": "unipile", "url": url}


async def fetch_account(account_id: str) -> dict:
    ident = str(account_id or "").strip()
    if not ident:
        raise ValueError("شناسه حساب اینستاگرام یونى‌پایل نیست.")
    async with _client() as client:
        response = await client.get(f"{base_url()}/api/v1/accounts/{ident}", headers=_headers())
    payload = _json(response)
    if response.status_code >= 400 or not payload.get("id"):
        raise ValueError(_error(payload, "حساب اینستاگرام از یونى‌پایل خوانده نشد."))
    return payload


def tenant_for_unipile_account(account_id: str) -> str:
    ident = str(account_id or "").strip()
    if not ident:
        return ""
    for phone in iter_tenants():
        with tenant_scope(phone):
            for row in channel_service.iter_accounts():
                if channel_service.unipile_account_id(row) == ident:
                    return phone
    return ""


async def ensure_messaging_webhook() -> dict:
    if not configured():
        raise ValueError("اتصال یونى‌پایل هنوز در سوزان تنظیم نشده.")
    url = webhook_url()
    secret = webhook_secret()
    async with _client() as client:
        listed = await client.get(f"{base_url()}/api/v1/webhooks", headers=_headers())
        for row in _items(_json(listed) if listed.status_code < 400 else {}):
            if not isinstance(row, dict):
                continue
            if str(row.get("request_url") or "").strip() == url:
                return {"ok": True, "existing": True, "url": url}
        response = await client.post(
            f"{base_url()}/api/v1/webhooks",
            headers={**_headers(), "content-type": "application/json"},
            json={
                "request_url": url,
                "source": "messaging",
                "name": "sozan-instagram",
                "format": "json",
                "enabled": True,
                "events": ["message_received"],
                "headers": [
                    {"key": "Content-Type", "value": "application/json"},
                    {"key": "Unipile-Auth", "value": secret},
                ],
            },
        )
    body = _json(response)
    if response.status_code >= 400:
        raise ValueError(_error(body, "یونى‌پایل وب‌هوک دایرکت را ثبت نکرد."))
    return {"ok": True, "existing": False, "url": url}


def _norm_name(value: str) -> str:
    return "".join(ch for ch in (value or "").lstrip("@").lower() if ch.isalnum())


def webhook_is_self(body: dict, *, sender_id: str, sender_name: str) -> bool:
    if body.get("is_sender") is True:
        return True
    sender = body.get("sender") if isinstance(body.get("sender"), dict) else {}
    if sender.get("is_self") is True:
        return True
    account_info = body.get("account_info") if isinstance(body.get("account_info"), dict) else {}
    own_id = str(account_info.get("user_id") or "").strip()
    attendee_id = str(sender.get("attendee_id") or "").strip()
    if own_id and sender_id and own_id == sender_id:
        return True
    if own_id and attendee_id and own_id == attendee_id:
        return True
    from app.services import channel_service

    row = channel_service.account_for_platform("instagram") or {}
    creds = channel_service.credentials_for(row)
    user_id = str(creds.get("userId") or "").strip()
    handle = _norm_name(str(row.get("handle") or ""))
    display = _norm_name(str(row.get("display") or ""))
    name = _norm_name(sender_name)
    if user_id and sender_id and user_id == sender_id:
        return True
    if handle and name and handle == name:
        return True
    if display and name and display == name:
        return True
    return False


async def accept_webhook(payload: dict) -> dict:
    body = payload if isinstance(payload, dict) else {}
    event = str(body.get("event") or "").strip()
    if event != "message_received":
        return {"ok": True, "ignored": event or "unknown"}
    account_type = str(body.get("account_type") or "").upper()
    if account_type != "INSTAGRAM":
        return {"ok": True, "ignored": account_type or "unknown"}
    account_id = str(body.get("account_id") or "").strip()
    phone = tenant_for_unipile_account(account_id)
    if not phone:
        return {"ok": True, "ignored": "tenant"}
    message_id = str(body.get("message_id") or "").strip()
    text = str(body.get("message") or "").strip()
    chat_id = str(body.get("chat_id") or "").strip()
    if not message_id:
        return {"ok": True, "ignored": "empty"}
    sender = body.get("sender") if isinstance(body.get("sender"), dict) else {}
    sender_id = str(sender.get("attendee_provider_id") or "").strip()
    sender_name = str(sender.get("attendee_name") or "مشتری").strip()
    with tenant_scope(phone):
        if message_id in _seen():
            return {"ok": True, "duplicate": True}
        if webhook_is_self(body, sender_id=sender_id, sender_name=sender_name):
            _mark([message_id])
            return {"ok": True, "ignored": "self"}
        if not plan_service.current().get("dmSync"):
            _mark([message_id])
            return {"ok": True, "ignored": "plan"}
        media = await media_from_payload(body, message_id=message_id)
        if not text and not media:
            _mark([message_id])
            return {"ok": True, "ignored": "empty"}
        result = await inbox_service.handle_inbound(
            platform="instagram",
            sender=sender_name,
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            external_id=message_id,
            media=media,
        )
        _mark([message_id])
        if result.get("echo") or result.get("duplicate"):
            return {"ok": True, "ignored": "echo" if result.get("echo") else "duplicate"}
    return {"ok": True, "imported": 1}


async def bind_instagram(*, account_id: str, phone: str) -> dict:
    ident = str(account_id or "").strip()
    tenant = str(phone or "").strip()
    if not ident:
        raise ValueError("شناسه حساب اینستاگرام یونى‌پایل نیست.")
    if not tenant:
        raise ValueError("فروشنده برای اتصال اینستاگرام شناخته نشد.")
    account = await fetch_account(ident)
    handle, user_id = instagram_handle(account)
    handle = handle or ident
    with tenant_scope(tenant):
        saved = channel_service.upsert_instagram(
            handle=handle,
            user_id=user_id,
            credentials={"unipileAccountId": ident, "userId": user_id},
            display=handle,
        )
        verified = channel_service.apply_verify(
            str(saved["id"]),
            {"ok": True, "connected": True, "handle": handle, "display": handle, "error": ""},
        )
    await ensure_messaging_webhook()
    return verified


async def claim_account(*, account_id: str, phone: str) -> dict:
    account = await bind_instagram(account_id=account_id, phone=phone)
    with tenant_scope(phone.strip()):
        return {**channel_service.list_accounts(), "account": account}


async def accept_notify(payload: dict, phone: str = "") -> dict:
    body = payload if isinstance(payload, dict) else {}
    status = str(body.get("status") or "").upper()
    account_id = str(body.get("account_id") or "").strip()
    tenant = str(phone or "").strip() or str(body.get("name") or "").strip()
    if status not in {"CREATION_SUCCESS", "RECONNECTED"}:
        raise ValueError("اتصال اینستاگرام کامل نشد.")
    if not account_id or not tenant:
        raise ValueError("اعلان یونى‌پایل ناقص است.")
    return await bind_instagram(account_id=account_id, phone=tenant)


async def publish_media(*, account_id: str, path, caption: str, kind: str) -> None:
    ident = str(account_id or "").strip()
    file_path = Path(path)
    if not ident:
        raise ValueError("حساب اینستاگرام یونى‌پایل وصل نیست.")
    if not file_path.is_file():
        raise ValueError("فایل برای اینستاگرام پیدا نشد")
    mime = "video/mp4" if kind == "video" else "image/jpeg"
    if file_path.suffix.lower() == ".png":
        mime = "image/png"
    data = {"account_id": ident, "text": (caption or "")[:2200], "post_type": "feed"}
    async with _client(timeout=90) as client:
        with file_path.open("rb") as handle:
            response = await client.post(
                f"{base_url()}/api/v1/posts",
                headers=_headers(),
                data=data,
                files={"attachments": (file_path.name, handle, mime)},
            )
    payload = _json(response)
    created = payload.get("object") == "PostCreated" or bool(payload.get("post_id"))
    if response.status_code >= 400 or not created:
        raise ValueError(_error(payload, "اینستاگرام پست را از یونى‌پایل منتشر نکرد."))


async def send_message(*, account_id: str, chat_id: str, text: str) -> None:
    ident = str(account_id or "").strip()
    thread = str(chat_id or "").strip()
    body = text.strip()
    if not ident:
        raise ValueError("حساب اینستاگرام یونى‌پایل وصل نیست.")
    if not thread:
        raise ValueError("شناسه گفتگوی اینستاگرام نیست. اول پیام مشتری را همگام کن.")
    if not body:
        raise ValueError("متن پاسخ خالی است")
    async with _client() as client:
        response = await client.post(
            f"{base_url()}/api/v1/chats/{thread}/messages",
            headers=_headers(),
            data={"account_id": ident, "text": body[:1000]},
        )
    if response.status_code >= 400:
        raise ValueError("اینستاگرام پیام را از یونى‌پایل نفرستاد.")


async def pull_directs(*, account_id: str, handle: str = "") -> dict:
    ident = str(account_id or "").strip()
    if not ident:
        return {"ok": False, "error": "حساب اینستاگرام یونى‌پایل وصل نیست", "imported": 0}
    imported = 0
    seen = _seen()
    own = handle.lstrip("@").lower()
    try:
        async with _client() as client:
            chats = await client.get(
                f"{base_url()}/api/v1/chats",
                headers=_headers(),
                params={"account_id": ident, "limit": 40},
            )
            chat_payload = _json(chats) if chats.status_code < 400 else {}
            for chat in _items(chat_payload):
                if not isinstance(chat, dict):
                    continue
                chat_id = str(chat.get("id") or "").strip()
                if not chat_id:
                    continue
                sender = str(chat.get("name") or chat.get("attendee_provider_id") or "مشتری")
                sender_id = str(chat.get("attendee_provider_id") or chat.get("provider_id") or "")
                if own and sender.lstrip("@").lower() == own:
                    continue
                messages = await client.get(
                    f"{base_url()}/api/v1/chats/{chat_id}/messages",
                    headers=_headers(),
                    params={"account_id": ident, "limit": 20},
                )
                msg_payload = _json(messages) if messages.status_code < 400 else {}
                for msg in reversed(_items(msg_payload)):
                    if not isinstance(msg, dict):
                        continue
                    mid = str(msg.get("id") or "").strip()
                    text = str(msg.get("text") or msg.get("message") or "").strip()
                    if not mid or mid in seen:
                        continue
                    if msg.get("is_sender") is True:
                        _mark([mid])
                        seen.add(mid)
                        continue
                    media = await media_from_payload(msg, message_id=mid)
                    if not text and not media:
                        continue
                    result = await inbox_service.handle_inbound(
                        platform="instagram",
                        sender=sender,
                        text=text,
                        sender_id=sender_id,
                        chat_id=chat_id,
                        external_id=mid,
                        media=media,
                    )
                    _mark([mid])
                    seen.add(mid)
                    if not result.get("duplicate"):
                        imported += 1
    except Exception:
        return {"ok": False, "imported": 0, "error": "خواندن دایرکت اینستاگرام به یونى‌پایل نرسید."}
    return {"ok": True, "imported": imported}
