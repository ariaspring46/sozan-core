from __future__ import annotations

import hashlib
import hmac
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings
from app.phone import normalize_phone
from app.services import channel_service, inbox_service, plan_service
from app.state_store import iter_tenants, read_json, tenant_scope, write_json

CONNECT_TTL = 30 * 60
PENDING_FILE = "sendbox-pending.json"


def configured() -> bool:
    return bool(api_key() and oauth_base())


def api_key() -> str:
    return (settings.sendbox_api_key or "").strip()


def base_url() -> str:
    raw = (settings.sendbox_base_url or "https://api.sendbox.chat/api/v1").strip()
    return raw.rstrip("/")


def oauth_base() -> str:
    return (settings.sendbox_oauth_url or "").strip()


def _derive(source: str) -> str:
    return hmac.new(source.encode(), b"sendbox-webhook", hashlib.sha256).hexdigest()


def webhook_secret() -> str:
    # جدا از JWT_SECRET؛ اگر SENDBOX_WEBHOOK_SECRET ست نشده باشد رفتار قدیمی.
    dedicated = str(settings.sendbox_webhook_secret or "").strip()
    return _derive(dedicated or settings.jwt_secret)


def _legacy_window_open() -> bool:
    import datetime as _dt

    raw = str(settings.sendbox_webhook_legacy_until or "").strip()
    try:
        return _dt.date.today() <= _dt.date.fromisoformat(raw)
    except ValueError:
        return False


def valid_webhook_token(token: str) -> bool:
    got = str(token or "").strip()
    if not got:
        return False
    if hmac.compare_digest(got, webhook_secret()):
        return True
    # دورهٔ چرخش: توکن قدیمی (مشتق از JWT) تا تاریخ LEGACY_UNTIL هم قبول است.
    if str(settings.sendbox_webhook_secret or "").strip() and _legacy_window_open():
        return hmac.compare_digest(got, _derive(settings.jwt_secret))
    return False


def webhook_url() -> str:
    origin = (settings.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{origin}/channels/sendbox/webhook?token={webhook_secret()}"


def _pending_rows() -> dict:
    data = read_json(PENDING_FILE, {}, shared=True)
    return data if isinstance(data, dict) else {}


def mark_connect_started(phone: str) -> str:
    """نقطهٔ شروع اتصال رسمی؛ یک nonce می‌سازد که Sendbox باید در بازگشت echo کند."""
    import secrets as _secrets
    import time

    tenant = normalize_phone(phone)
    nonce = _secrets.token_hex(16)
    rows = _pending_rows()
    rows[tenant] = {"t": time.time(), "n": nonce}
    write_json(PENDING_FILE, rows, shared=True)
    return nonce


def consume_connect(phone: str) -> tuple[bool, str]:
    """اتصال در جریان را مصرف کن؛ (درست‌بودن، nonce) را برمی‌گرداند."""
    import time

    try:
        tenant = normalize_phone(phone)
    except ValueError:
        return False, ""
    rows = _pending_rows()
    row = rows.get(tenant)
    if tenant in rows:
        rows.pop(tenant, None)
        write_json(PENDING_FILE, rows, shared=True)
    if not isinstance(row, dict):
        return False, ""
    started = float(row.get("t") or 0)
    return bool(started) and time.time() - started <= CONNECT_TTL, str(row.get("n") or "")


def panel_channels_url(query: str) -> str:
    base = (settings.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/more/channels?{query}"


def panel_onboard_url(query: str) -> str:
    base = (settings.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/onboard?{query}"


def login_url(*, phone: str, oauth: str = "", state: str = "") -> str:
    tenant = phone.strip()
    if not tenant:
        raise ValueError("فروشنده برای ورود اینستاگرام شناخته نشد. دوباره وارد پنل شو.")
    raw = (oauth or oauth_base()).strip()
    if not raw:
        raise ValueError("لینک ورود رسمی BoxAPI در سوزان تنظیم نشده.")
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["id"] = tenant
    if state:
        query["state"] = state
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
    """فقط حساب‌های همین فروشنده؛ حساب‌های آزادِ دیگران هرگز فهرست نمی‌شوند."""
    tenant = str(phone or "").strip()
    out = []
    for row in rows:
        ident = str(row.get("id") or "").strip()
        if not ident:
            continue
        owner = tenant_for_sendbox_account(ident)
        if owner != tenant:
            continue
        out.append({**row, "bound": True})
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
    nonce = mark_connect_started(phone)
    url = login_url(phone=phone, oauth=live, state=nonce)
    return {
        "configured": True,
        "provider": "sendbox",
        "url": url,
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
    from app.services import tenant_index_service

    def owns(phone: str) -> bool:
        with tenant_scope(phone):
            return any(channel_service.sendbox_account_id(row) == ident for row in channel_service.iter_accounts())

    return tenant_index_service.lookup("sendbox", ident, owns) or ""


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
        from app.services import tenant_index_service

        tenant_index_service.upsert(phone=tenant, sendbox_id=ident)
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


def finish_redirect(*, status: str, account_id: str, username: str, seller_id: str, error: str = "", state: str = "") -> str:
    try:
        phone = normalize_phone(seller_id)
    except ValueError:
        return panel_channels_url("instagram=error")
    ident = str(account_id or "").strip()
    name = str(username or "").lstrip("@").strip()
    provided_state = str(state or "").strip()
    if ident:
        fresh, nonce = consume_connect(phone)
        if not fresh:
            return _after_bind_url(phone, username=name, flag="error")
        owner = tenant_for_sendbox_account(ident)
        # حساب تازه فقط با nonce همان نشست رسمی بسته می‌شود؛ حساب خودی بدون آن هم دوباره وصل می‌شود.
        if not owner:
            if not nonce or not provided_state or not hmac.compare_digest(nonce, provided_state):
                return _after_bind_url(phone, username=name, flag="error")
        try:
            bind_instagram(account_id=ident, phone=phone, handle=name)
        except ValueError:
            return _after_bind_url(phone, username=name, flag="error")
        return _after_bind_url(phone, account_id=ident, username=name, flag="ok")
    return _after_bind_url(phone, username=name, flag="exists")


async def claim_account(*, account_id: str, phone: str, handle: str = "") -> dict:
    ident = str(account_id or "").strip()
    if tenant_for_sendbox_account(ident) != str(phone or "").strip():
        raise ValueError("اتصال حساب تازه فقط با ورود رسمی Sendbox از صفحهٔ کانال‌ها.")
    account = bind_instagram(account_id=ident, phone=phone, handle=handle)
    with tenant_scope(phone.strip()):
        return {**channel_service.list_accounts(), "account": account}


async def send_message(
    *,
    account_id: str,
    recipient_id: str,
    text: str,
    media_url: str = "",
    media_kind: str = "",
) -> None:
    ident = str(account_id or "").strip()
    target = str(recipient_id or "").strip()
    body = text.strip()
    media = str(media_url or "").strip()
    if not ident:
        raise ValueError("حساب اینستاگرام BoxAPI وصل نیست.")
    if not target:
        raise ValueError("شناسه مشتری اینستاگرام نیست. اول پیام مشتری را همگام کن.")
    if not body:
        body = "ویدیو استودیو" if str(media_kind or "").lower() == "video" else "تصویر استودیو" if media else ""
    if not body:
        raise ValueError("متن پاسخ خالی است")
    payload: dict = {"account_id": ident, "recipient_id": target, "message": body[:1000]}
    if media:
        title = "دیدن ویدیو" if str(media_kind or "").lower() == "video" else "دیدن تصویر"
        payload["buttons"] = [{"type": "web_url", "title": title, "url": media[:2000]}]
    async with _client() as client:
        response = await client.post(
            f"{base_url()}/service/actions/send_message",
            headers=_headers(),
            json=payload,
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
