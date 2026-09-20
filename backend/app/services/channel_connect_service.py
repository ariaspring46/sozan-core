from __future__ import annotations

import httpx

from app.services.channel_http import async_client

GRAPH_WA = "https://graph.facebook.com/v21.0"


async def verify_credentials(*, platform: str, handle: str, credentials: dict) -> dict:
    key = platform.strip().lower()
    creds = credentials if isinstance(credentials, dict) else {}
    if key == "instagram":
        return await _instagram(creds, handle)
    if key == "telegram":
        return await _telegram(creds, handle)
    if key == "whatsapp":
        return await _whatsapp(creds, handle)
    if key == "bale":
        return await _bale(creds, handle)
    if key == "rubika":
        return await _rubika(creds, handle)
    raise ValueError("این پلتفرم پشتیبانی نمی‌شود")


def _token(creds: dict, *keys: str) -> str:
    for key in keys:
        value = str(creds.get(key) or "").strip()
        if value:
            return value
    return ""


async def _instagram(creds: dict, handle: str) -> dict:
    from app.services.channel_service import IG_RECONNECT

    sendbox_id = str(creds.get("sendboxAccountId") or "").strip()
    if sendbox_id:
        name = handle.lstrip("@").strip() or sendbox_id
        return _ok(name, name)
    if str(creds.get("unipileAccountId") or "").strip() or _token(creds, "accessToken"):
        name = handle.lstrip("@").strip()
        return _unverified(name, IG_RECONNECT)
    return _unverified(handle, "ورود رسمی BoxAPI را بزن.")


async def _telegram(creds: dict, handle: str) -> dict:
    token = _token(creds, "botToken")
    if not token:
        from app.services.channel_service import _hub_telegram_token

        token = _hub_telegram_token()
    if not token:
        return _unverified(handle, "توکن بات را از ‎@BotFather بگیر یا بات هاب سوزان را وصل کن.")
    async with async_client(timeout=20) as client:
        response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    payload = _json(response)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if response.status_code >= 400 or payload.get("ok") is not True:
        return _failed("توکن تلگرام قبول نشد. توکن را از ‎@BotFather دوباره کپی کن.")
    username = str(result.get("username") or "").lstrip("@")
    return _ok(handle or (f"@{username}" if username else ""), result.get("first_name") or username)


async def _whatsapp(creds: dict, handle: str) -> dict:
    token = _token(creds, "accessToken")
    phone_id = str(creds.get("phoneNumberId") or "").strip()
    if not token or not phone_id:
        return _unverified(handle, "شناسه شماره و توکن دائمی Cloud API را از Meta بگذار.")
    async with async_client(timeout=20) as client:
        response = await client.get(
            f"{GRAPH_WA}/{phone_id}",
            params={"fields": "display_phone_number,verified_name", "access_token": token},
        )
    payload = _json(response)
    if response.status_code >= 400 or payload.get("error"):
        return _failed("واتساپ وصل نشد. Phone Number ID و توکن سیستم‌یوزر را در پنل Meta بررسی کن.")
    display = str(payload.get("display_phone_number") or handle)
    return _ok(handle or display, payload.get("verified_name") or display)


async def _bale(creds: dict, handle: str) -> dict:
    token = _token(creds, "botToken")
    if not token:
        return _unverified(handle, "توکن بازو را از BotFather بله بگیر.")
    async with async_client(timeout=20) as client:
        response = await client.get(f"https://tapi.bale.ai/bot{token}/getMe")
    payload = _json(response)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if response.status_code >= 400 or payload.get("ok") is not True:
        return _failed("توکن بله قبول نشد. از BotFather بله توکن تازه بگیر.")
    username = str(result.get("username") or "").lstrip("@")
    return _ok(handle or (f"@{username}" if username else ""), result.get("first_name") or username)


async def _rubika(creds: dict, handle: str) -> dict:
    token = _token(creds, "botToken")
    if not token:
        return _unverified(handle, "توکن بات را از BotFather روبیکا بگیر.")
    async with async_client(timeout=20) as client:
        response = await client.post(f"https://botapi.rubika.ir/v3/{token}/getMe")
    payload = _json(response)
    bot = payload.get("bot") if isinstance(payload.get("bot"), dict) else payload.get("data")
    if isinstance(bot, dict) and (bot.get("username") or bot.get("bot_id") or bot.get("id")):
        username = str(bot.get("username") or handle)
        return _ok(handle or username, bot.get("title") or username)
    if response.status_code < 400 and payload.get("status") == "OK":
        return _ok(handle, handle)
    if response.status_code >= 400:
        return _failed("توکن روبیکا قبول نشد. توکن BotFather را دوباره کپی کن.")
    return _ok(handle, handle)


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ok(handle: str, display: object) -> dict:
    return {"ok": True, "connected": True, "handle": handle, "display": str(display or handle), "error": ""}


def _unverified(handle: str, error: str) -> dict:
    return {"ok": True, "connected": False, "handle": handle, "display": "", "error": error}


def _failed(error: str) -> dict:
    return {"ok": False, "connected": False, "handle": "", "display": "", "error": error}
