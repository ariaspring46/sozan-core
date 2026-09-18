from __future__ import annotations

import json
import secrets
import time
from urllib.parse import urlencode

from app.config import settings
from app.redis_client import redis_client
from app.services import channel_service
from app.services.channel_http import async_client
from app.state_store import tenant_scope

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
SCOPES = (
    "instagram_business_basic",
    "instagram_business_content_publish",
    "instagram_business_manage_messages",
)
STATE_TTL_SEC = 600
REFRESH_BEFORE_SEC = 10 * 24 * 3600
REFRESH_MIN_AGE_SEC = 24 * 3600


def configured() -> bool:
    return bool(app_id() and app_secret())


def app_id() -> str:
    return (settings.instagram_app_id or "").strip()


def app_secret() -> str:
    return (settings.instagram_app_secret or "").strip()


def redirect_uri() -> str:
    raw = (settings.instagram_redirect_uri or "").strip()
    if raw:
        return raw
    return f"{(settings.public_api_url or '').rstrip('/')}/channels/instagram/callback"


def panel_channels_url(query: str) -> str:
    base = (settings.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/more/channels?{query}"


def strip_auth_code(code: str) -> str:
    return str(code or "").replace("#_", "").strip()


def short_token_from(payload: dict) -> tuple[str, str]:
    token = str(payload.get("access_token") or "").strip()
    user_id = str(payload.get("user_id") or payload.get("userId") or "").strip()
    if token:
        return token, user_id
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        return str(first.get("access_token") or "").strip(), str(first.get("user_id") or "").strip()
    return "", ""


def _json(response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _meta_error(payload: dict, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    err = payload.get("error")
    if isinstance(err, dict) and err.get("message"):
        return fallback
    if payload.get("error_message") or payload.get("error_type"):
        return fallback
    return fallback


async def start_login(*, phone: str) -> dict:
    if not configured():
        raise ValueError("اتصال اینستاگرام هنوز در سوزان تنظیم نشده. شناسه و رمز اپ متا لازم است.")
    tenant = phone.strip()
    if not tenant:
        raise ValueError("فروشنده برای ورود اینستاگرام شناخته نشد. دوباره وارد پنل شو.")
    nonce = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"ig-oauth:{nonce}",
        STATE_TTL_SEC,
        json.dumps({"phone": tenant}, ensure_ascii=False),
    )
    params = {
        "client_id": app_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": nonce,
        # Default enable_fb_login is true and Instagram then sends users to a Facebook-login
        # page that returns "Page isn't available". Instagram Login needs the IG-only path.
        "enable_fb_login": "0",
    }
    return {"configured": True, "url": f"{AUTHORIZE_URL}?{urlencode(params)}"}


async def consume_state(state: str) -> str:
    nonce = str(state or "").strip()
    if not nonce:
        raise ValueError("نشست ورود اینستاگرام ناقص است. دوباره از پنل وصل کن.")
    key = f"ig-oauth:{nonce}"
    raw = await redis_client.get(key)
    await redis_client.delete(key)
    if not raw:
        raise ValueError("نشست ورود اینستاگرام منقضی شد. دوباره از پنل وصل کن.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("نشست ورود اینستاگرام نامعتبر است. دوباره از پنل وصل کن.") from exc
    phone = str(payload.get("phone") or "").strip() if isinstance(payload, dict) else ""
    if not phone:
        raise ValueError("نشست ورود اینستاگرام فروشنده را نداشت. دوباره از پنل وصل کن.")
    return phone


async def exchange_code(code: str) -> tuple[str, str]:
    code = strip_auth_code(code)
    if not code:
        raise ValueError("اینستاگرام کد ورود را نداد. دوباره از پنل وصل کن.")
    async with async_client(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": app_id(),
                "client_secret": app_secret(),
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
                "code": code,
            },
        )
    payload = _json(response)
    token, user_id = short_token_from(payload)
    if response.status_code >= 400 or not token:
        raise ValueError(_meta_error(payload, "اینستاگرام توکن کوتاه را نداد. حساب حرفه‌ای را دوباره وصل کن."))
    return token, user_id


async def exchange_long_lived(short_token: str) -> tuple[str, int]:
    async with async_client(timeout=20) as client:
        response = await client.get(
            f"{GRAPH}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret(),
                "access_token": short_token,
            },
        )
    payload = _json(response)
    token = str(payload.get("access_token") or "").strip()
    expires_in = int(payload.get("expires_in") or 0)
    if response.status_code >= 400 or not token:
        return short_token, 3600
    return token, expires_in or 5_184_000


async def refresh_long_lived(token: str) -> tuple[str, int]:
    async with async_client(timeout=20) as client:
        response = await client.get(
            f"{GRAPH}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
        )
    payload = _json(response)
    next_token = str(payload.get("access_token") or "").strip()
    expires_in = int(payload.get("expires_in") or 0)
    if response.status_code >= 400 or not next_token:
        raise ValueError(_meta_error(payload, "تمدید توکن اینستاگرام شکست خورد."))
    return next_token, expires_in or 5_184_000


async def fetch_profile(token: str) -> dict:
    async with async_client(timeout=20) as client:
        response = await client.get(
            f"{GRAPH}/v21.0/me",
            params={"fields": "id,username"},
            headers={"Authorization": f"Bearer {token}"},
        )
    payload = _json(response)
    user_id = str(payload.get("id") or "").strip()
    username = str(payload.get("username") or "").lstrip("@")
    if response.status_code >= 400 or not user_id:
        raise ValueError(_meta_error(payload, "توکن اینستاگرام صفحه را نداد. حساب حرفه‌ای را دوباره وصل کن."))
    return {"id": user_id, "username": username}


def _expires_at(expires_in: int) -> int:
    ttl = int(expires_in or 0)
    if ttl <= 0:
        ttl = 5_184_000
    return int(time.time()) + ttl


async def complete_login(*, phone: str, code: str) -> dict:
    short, user_id = await exchange_code(code)
    token, expires_in = await exchange_long_lived(short)
    profile = await fetch_profile(token)
    handle = str(profile.get("username") or user_id).lstrip("@")
    ig_user = str(profile.get("id") or user_id)
    issued = int(time.time())
    creds = {
        "accessToken": token,
        "userId": ig_user,
        "tokenExpiresAt": str(_expires_at(expires_in)),
        "tokenIssuedAt": str(issued),
    }
    with tenant_scope(phone):
        account = channel_service.upsert_instagram(
            handle=handle,
            user_id=ig_user,
            credentials=creds,
            display=handle,
        )
        return channel_service.apply_verify(
            str(account["id"]),
            {"ok": True, "connected": True, "handle": handle, "display": handle, "error": ""},
        )


async def finish_redirect(*, code: str, state: str, error: str) -> str:
    if str(error or "").strip():
        return panel_channels_url("instagram=denied")
    if not configured():
        return panel_channels_url("instagram=config")
    try:
        phone = await consume_state(state)
        await complete_login(phone=phone, code=code)
    except ValueError as exc:
        text = str(exc)
        if "نشست ورود" in text:
            return panel_channels_url("instagram=expired")
        return panel_channels_url("instagram=error")
    except Exception:
        return panel_channels_url("instagram=error")
    return panel_channels_url("instagram=ok")


def should_refresh(row: dict, *, now: int | None = None) -> bool:
    creds = channel_service.credentials_for(row)
    token = str(creds.get("accessToken") or "").strip()
    if not token:
        return False
    clock = int(now if now is not None else time.time())
    try:
        expires_at = int(creds.get("tokenExpiresAt") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    try:
        issued_at = int(creds.get("tokenIssuedAt") or 0)
    except (TypeError, ValueError):
        issued_at = 0
    if expires_at and expires_at - clock > REFRESH_BEFORE_SEC:
        return False
    if issued_at and clock - issued_at < REFRESH_MIN_AGE_SEC:
        return False
    return True


async def refresh_row(row: dict) -> None:
    if not should_refresh(row):
        return
    creds = channel_service.credentials_for(row)
    token = str(creds.get("accessToken") or "").strip()
    try:
        next_token, expires_in = await refresh_long_lived(token)
    except ValueError:
        return
    channel_service.update_instagram_token(
        str(row.get("id") or ""),
        access_token=next_token,
        expires_at=_expires_at(expires_in),
        issued_at=int(time.time()),
    )
