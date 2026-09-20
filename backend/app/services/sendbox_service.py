from __future__ import annotations

import hashlib
import hmac
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings
from app.phone import normalize_phone
from app.services import channel_service, inbox_service, plan_service
from app.state_store import iter_tenants, read_json, tenant_scope, write_json


def configured() -> bool:
    return bool(api_key() and oauth_base())


def api_key() -> str:
    return (settings.sendbox_api_key or "").strip()


def base_url() -> str:
    raw = (settings.sendbox_base_url or "https://api.sendbox.chat/api/v1").strip()
    return raw.rstrip("/")


def oauth_base() -> str:
    raw = (settings.sendbox_oauth_url or "").strip()
    if raw:
        return raw
    key = api_key()
    if not key:
        return ""
    return f"https://api.sendbox.chat/instagram-oauth?token={key}"


def webhook_secret() -> str:
    return hmac.new(settings.jwt_secret.encode(), b"sendbox-webhook", hashlib.sha256).hexdigest()


def valid_webhook_token(token: str) -> bool:
    got = str(token or "").strip()
    want = webhook_secret()
    return bool(got) and hmac.compare_digest(got, want)


def webhook_url() -> str:
    origin = (settings.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{origin}/channels/sendbox/webhook?token={webhook_secret()}"


def panel_channels_url(query: str) -> str:
    base = (settings.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/more/channels?{query}"


def panel_onboard_url(query: str) -> str:
    base = (settings.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/onboard?{query}"


def login_url(*, phone: str, oauth: str = "") -> str:
    tenant = phone.strip()
    if not tenant:
        raise ValueError("فروشنده برای ورود اینستاگرام شناخته نشد. دوباره وارد پنل شو.")
    raw = (oauth or oauth_base()).strip()
    if not raw:
        raise ValueError("لینک ورود رسمی BoxAPI در سوزان تنظیم نشده.")
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if not query.get("token") and api_key():
        query["token"] = api_key()
    query["id"] = tenant
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def fetch_oauth_url() -> str:
    async with _client(timeout=12) as client:
        response = await client.get(f"{base_url()}/service/info", headers=_headers())
    if response.status_code >= 400:
        return ""
    data = _json(response).get("data")
    if not isinstance(data, dict):
        return ""
    return str(data.get("instagram_oauth_url") or "").strip()


async def list_remote_accounts() -> list[dict]:
    async with _client(timeout=12) as client:
        response = await client.get(f"{base_url()}/service/accounts", headers=_headers())
    if response.status_code >= 400:
        return []
    payload = _json(response)
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or "").strip()
        if not ident:
            continue
        out.append(
            {
                "id": ident,
                "username": str(row.get("username") or "").lstrip("@").strip(),
                "active": bool(row.get("is_active", True)),
            }
        )
    return out


def unused_remote_accounts(rows: list[dict], *, phone: str) -> list[dict]:
    tenant = str(phone or "").strip()
    out = []
    for row in rows:
        ident = str(row.get("id") or "").strip()
        if not ident:
            continue
        owner = tenant_for_sendbox_account(ident)
        if owner and owner != tenant:
            continue
        out.append({**row, "bound": bool(owner and owner == tenant)})
    return out


async def start_instagram(*, phone: str) -> dict:
    if not configured():
        raise ValueError("اتصال رسمی BoxAPI هنوز در سوزان تنظیم نشده.")
    live = ""
    existing: list[dict] = []
    try:
        # Login token can rotate in the Sendbox panel independently of SENDBOX_API_KEY.
        live = await fetch_oauth_url()
    except Exception:
        live = ""
    try:
        existing = unused_remote_accounts(await list_remote_accounts(), phone=phone)
    except Exception:
        existing = []
    return {
        "configured": True,
        "provider": "sendbox",
        "url": login_url(phone=phone, oauth=live),
        "existing": existing,
    }


async def request_list_posts(*, account_id: str, limit: int = 24) -> None:
    ident = str(account_id or "").strip()
    if not ident:
        return
    async with _client(timeout=20) as client:
        await client.post(
            f"{base_url()}/service/actions/list_posts",
            headers=_headers(),
            json={
                "account_id": ident,
                "fields": ["id", "media_type", "media_url", "permalink", "caption", "timestamp"],
                "limit": max(1, min(int(limit or 24), 50)),
            },
        )


def take_list_posts(account_id: str) -> list[dict]:
    ident = str(account_id or "").strip()
    if not ident:
        return []
    store = read_json("sendbox-posts.json", {})
    if not isinstance(store, dict):
        return []
    rows = store.get(ident)
    return [dict(item) for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _store_list_posts(account_id: str, posts: list[dict]) -> None:
    ident = str(account_id or "").strip()
    if not ident:
        return
    store = read_json("sendbox-posts.json", {})
    if not isinstance(store, dict):
        store = {}
    store[ident] = posts[:50]
    write_json("sendbox-posts.json", store)


def _posts_from_webhook(body: dict) -> list[dict]:
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    cands = []
    for key in ("posts", "items", "media", "data"):
        raw = data.get(key) if isinstance(data, dict) else None
        if isinstance(raw, list):
            cands = raw
            break
    if not cands and isinstance(body.get("posts"), list):
        cands = body["posts"]
    out = []
    for item in cands:
        if not isinstance(item, dict):
            continue
        caption = item.get("caption")
        if isinstance(caption, dict):
            caption = caption.get("text") or caption.get("caption") or ""
        media = str(item.get("media_url") or item.get("mediaUrl") or item.get("url") or "").strip()
        text = str(caption or item.get("text") or "").strip()
        if not media and not text:
            continue
        out.append(
            {
                "id": str(item.get("id") or ""),
                "caption": text[:800],
                "media_url": media,
                "permalink": str(item.get("permalink") or ""),
            }
        )
    return out


def _headers() -> dict[str, str]:
    return {"X-Api-Key": api_key(), "accept": "application/json", "content-type": "application/json"}


def _client(*, timeout: float = 30) -> httpx.AsyncClient:
    from app.services.channel_http import async_client

    return async_client(timeout=timeout)


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def media_from_message(message: dict) -> dict | None:
    from app.services.inbound_media_service import fetch_and_store

    body = message if isinstance(message, dict) else {}
    attachments = body.get("attachments")
    if not isinstance(attachments, list):
        return None
    for item in attachments:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        url = str(payload.get("url") or item.get("url") or "").strip()
        kind = str(item.get("type") or payload.get("type") or "").lower()
        hint = "video" if "video" in kind else "audio" if "audio" in kind else "image"
        if url:
            stored = await fetch_and_store(url, kind_hint=hint)
            if stored:
                return stored
    return None


def _seen() -> set[str]:
    rows = read_json("sendbox-seen.json", [])
    return {str(item) for item in rows} if isinstance(rows, list) else set()


def _mark(ids: list[str]) -> None:
    seen = _seen()
    seen.update(ids)
    write_json("sendbox-seen.json", sorted(seen)[-400:])


def tenant_for_sendbox_account(account_id: str) -> str:
    ident = str(account_id or "").strip()
    if not ident:
        return ""
    for phone in iter_tenants():
        with tenant_scope(phone):
            for row in channel_service.iter_accounts():
                if channel_service.sendbox_account_id(row) == ident:
                    return phone
    return ""


def bind_instagram(*, account_id: str, phone: str, handle: str = "") -> dict:
    ident = str(account_id or "").strip()
    tenant = str(phone or "").strip()
    name = handle.lstrip("@").strip() or ident
    if not ident:
        raise ValueError("شناسه حساب اینستاگرام BoxAPI نیست.")
    if not tenant:
        raise ValueError("فروشنده برای اتصال اینستاگرام شناخته نشد.")
    owner = tenant_for_sendbox_account(ident)
    if owner and owner != tenant:
        raise ValueError("این پیج اینستاگرام به فروشندهٔ دیگری وصل است.")
    with tenant_scope(tenant):
        saved = channel_service.upsert_instagram(
            handle=name,
            user_id=ident,
            credentials={"sendboxAccountId": ident},
            display=name,
        )
        verified = channel_service.apply_verify(
            str(saved["id"]),
            {"ok": True, "connected": True, "handle": name, "display": name, "error": ""},
        )
        _kick_scan(handle=name, sendbox_id=ident)
        return verified


def _kick_scan(*, handle: str, sendbox_id: str) -> None:
    from app.services import channel_scan_service

    try:
        channel_scan_service.start_scan(
            [{"platform": "instagram", "handle": handle, "sendboxAccountId": sendbox_id}]
        )
    except RuntimeError:
        return


def _after_bind_url(phone: str, *, account_id: str = "", username: str = "", flag: str = "ok") -> str:
    from app.services import profile_service
    from urllib.parse import urlencode

    try:
        profile = profile_service.get_profile(phone)
    except Exception:
        profile = {}
    query = {"instagram": flag}
    if account_id:
        query["account_id"] = account_id
    if username:
        query["username"] = username
    packed = urlencode(query)
    if not bool((profile or {}).get("onboarded")):
        return panel_onboard_url(packed)
    return panel_channels_url(packed)


def finish_redirect(*, status: str, account_id: str, username: str, seller_id: str, error: str = "") -> str:
    try:
        phone = normalize_phone(seller_id)
    except ValueError:
        return panel_channels_url("instagram=error")
    ident = str(account_id or "").strip()
    name = str(username or "").lstrip("@").strip()
    if ident:
        try:
            bind_instagram(account_id=ident, phone=phone, handle=name)
        except ValueError:
            return _after_bind_url(phone, username=name, flag="error")
        return _after_bind_url(phone, account_id=ident, username=name, flag="ok")
    return _after_bind_url(phone, username=name, flag="exists")


async def claim_account(*, account_id: str, phone: str, handle: str = "") -> dict:
    account = bind_instagram(account_id=account_id, phone=phone, handle=handle)
    with tenant_scope(phone.strip()):
        return {**channel_service.list_accounts(), "account": account}


async def send_message(*, account_id: str, recipient_id: str, text: str) -> None:
    ident = str(account_id or "").strip()
    target = str(recipient_id or "").strip()
    body = text.strip()
    if not ident:
        raise ValueError("حساب اینستاگرام BoxAPI وصل نیست.")
    if not target:
        raise ValueError("شناسه مشتری اینستاگرام نیست. اول پیام مشتری را همگام کن.")
    if not body:
        raise ValueError("متن پاسخ خالی است")
    async with _client() as client:
        response = await client.post(
            f"{base_url()}/service/actions/send_message",
            headers=_headers(),
            json={"account_id": ident, "recipient_id": target, "message": body[:1000]},
        )
    if response.status_code in {401, 403}:
        raise ValueError(channel_service.IG_RECONNECT)
    if response.status_code >= 400:
        raise ValueError("اینستاگرام پیام را از BoxAPI نفرستاد.")


async def set_account_active(*, account_id: str, active: bool) -> None:
    ident = str(account_id or "").strip()
    if not ident or not configured():
        return
    async with _client(timeout=20) as client:
        response = await client.put(
            f"{base_url()}/service/accounts/{ident}",
            headers=_headers(),
            json={"is_active": bool(active)},
        )
    if response.status_code >= 400:
        raise ValueError("غیرفعال‌سازی پیج اینستاگرام در BoxAPI انجام نشد.")


async def release_local_account(account_id: str) -> dict:
    row = channel_service.secret_for(account_id)
    sendbox_id = channel_service.sendbox_account_id(row) if row else ""
    if sendbox_id:
        try:
            await set_account_active(account_id=sendbox_id, active=False)
        except ValueError:
            pass
    return channel_service.remove_account(account_id)


async def accept_webhook(payload: dict) -> dict:
    body = payload if isinstance(payload, dict) else {}
    event = str(body.get("event_type") or body.get("event") or "").strip().lower()
    account_id = str(body.get("account_id") or "").strip()
    if "post" in event or event in {"list_posts", "media", "feed"}:
        posts = _posts_from_webhook(body)
        phone = tenant_for_sendbox_account(account_id)
        if account_id and posts and phone:
            with tenant_scope(phone):
                _store_list_posts(account_id, posts)
        return {"ok": True, "posts": len(posts)}
    if event and event not in {"messaging", "message", "message_received", ""}:
        posts = _posts_from_webhook(body)
        phone = tenant_for_sendbox_account(account_id)
        if account_id and posts and phone:
            with tenant_scope(phone):
                _store_list_posts(account_id, posts)
            return {"ok": True, "posts": len(posts)}
        return {"ok": True, "ignored": event}
    phone = tenant_for_sendbox_account(account_id)
    if not phone:
        return {"ok": True, "ignored": "tenant"}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    rows = data.get("messaging") if isinstance(data.get("messaging"), list) else [data]
    imported = 0
    with tenant_scope(phone):
        if not plan_service.current().get("dmSync"):
            return {"ok": True, "ignored": "plan"}
        for item in rows:
            if not isinstance(item, dict):
                continue
            sender = item.get("sender") if isinstance(item.get("sender"), dict) else {}
            recipient = item.get("recipient") if isinstance(item.get("recipient"), dict) else {}
            message = item.get("message") if isinstance(item.get("message"), dict) else {}
            sender_id = str(sender.get("id") or "").strip()
            own_id = str(recipient.get("id") or "").strip()
            mid = str(message.get("mid") or item.get("mid") or "").strip()
            if own_id and sender_id and own_id == sender_id:
                if mid:
                    _mark([mid])
                continue
            text = str(message.get("text") or item.get("text") or item.get("message") or "").strip()
            if not mid or mid in _seen():
                continue
            media = await media_from_message(message)
            if not text and not media:
                continue
            result = await inbox_service.handle_inbound(
                platform="instagram",
                sender=str(sender.get("username") or sender.get("name") or "مشتری"),
                text=text,
                sender_id=sender_id,
                chat_id=sender_id,
                external_id=mid,
                media=media,
            )
            _mark([mid])
            imported += 1
    return {"ok": True, "imported": imported}
