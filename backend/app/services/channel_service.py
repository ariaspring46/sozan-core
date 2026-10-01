from __future__ import annotations

import time
from uuid import uuid4

from app.services.plan_service import allow_new_channel
from app.state_store import read_json, write_json

SPECS = {
    "instagram": {
        "id": "instagram",
        "label": "اینستاگرام",
        "docs": "",
        "help": "اینستاگرام را با ورود رسمی وصل کن تا دایرکت مشتری بیاید. رمز را در فرم سوزان نگذار. اسکن ویترین عمومی با نام کاربری جداست.",
        "handleLabel": "نام کاربری صفحه",
        "handlePlaceholder": "@shop",
        "fields": [],
    },
    "telegram": {
        "id": "telegram",
        "label": "تلگرام",
        "docs": "https://core.telegram.org/bots/api",
        "help": "اگر بات سوزان روی هاب باشد، فقط مقصد کانال را بگذار. وگرنه در تلگرام به ‎@BotFather برو، بات بساز و توکن را همین‌جا بگذار. برای ارسال پست استودیو، بات را ادمین کانال یا گروه کن و آیدی همان کانال را در مقصد پست بگذار.",
        "handleLabel": "نام کاربری بات",
        "handlePlaceholder": "@shop_bot",
        "fields": [
            {"key": "botToken", "label": "توکن بات تلگرام", "secret": True, "required": False},
            {"key": "postTarget", "label": "مقصد پست (مثلاً @myshop یا شناسه کانال)", "secret": False, "required": False},
        ],
    },
    "whatsapp": {
        "id": "whatsapp",
        "label": "واتساپ",
        "docs": "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
        "help": "واتساپ فید عمومی ندارد. شناسهٔ شماره، شناسهٔ حساب کسب‌وکار و توکن دائمی را از پنل واتساپ بردار. پست استودیو به شمارهٔ مقصدی که اینجا ثبت می‌کنی می‌رود.",
        "handleLabel": "شماره نمایشی کسب‌وکار",
        "handlePlaceholder": "98912…",
        "fields": [
            {"key": "phoneNumberId", "label": "شناسهٔ شماره", "secret": False, "required": True},
            {"key": "wabaId", "label": "شناسهٔ حساب کسب‌وکار", "secret": False, "required": False},
            {"key": "accessToken", "label": "توکن دائمی واتساپ", "secret": True, "required": True},
            {"key": "postTarget", "label": "شماره مقصد ارسال (با کد کشور، مثل 98912…)", "secret": False, "required": False},
        ],
    },
    "bale": {
        "id": "bale",
        "label": "بله",
        "docs": "https://docs.bale.ai/",
        "help": "بازو را در بله بساز و توکن را همین‌جا بگذار.",
        "handleLabel": "نام کاربری بازو",
        "handlePlaceholder": "@shop_bot",
        "fields": [
            {"key": "botToken", "label": "توکن بازوی بله", "secret": True, "required": True},
        ],
    },
    "rubika": {
        "id": "rubika",
        "label": "روبیکا",
        "docs": "https://rubika.ir/botapi",
        "help": "بات را در روبیکا بساز و توکن را همین‌جا بگذار.",
        "handleLabel": "نام کاربری بات",
        "handlePlaceholder": "@shop_bot",
        "fields": [
            {"key": "botToken", "label": "توکن بات روبیکا", "secret": True, "required": True},
        ],
    },
}

PLATFORMS = {key: spec["label"] for key, spec in SPECS.items()}
IG_RECONNECT = "این پیج را دوباره با ورود رسمی وصل کن."
IG_STUDIO_WAIT = "انتشار پست اینستاگرام از استودیو هنوز برای این اتصال آماده نیست."


def _rows() -> list[dict]:
    rows = read_json("channels.json", [])
    return rows if isinstance(rows, list) else []


def _save(rows: list[dict]) -> None:
    write_json("channels.json", rows)


def _hub_telegram_token() -> str:
    from app.config import settings as env

    return str(env.telegram_hub_bot_token or "").strip()


def _credentials(row: dict) -> dict:
    creds = row.get("credentials")
    if isinstance(creds, dict):
        return {str(key): str(value).strip() for key, value in creds.items() if str(value).strip()}
    secret = str(row.get("secret") or "").strip()
    platform = str(row.get("platform") or "")
    if not secret:
        return {}
    if platform in {"telegram", "bale", "rubika"}:
        return {"botToken": secret}
    return {"accessToken": secret}


def credentials_for(row: dict) -> dict:
    creds = _credentials(row)
    if str(row.get("platform") or "") == "telegram" and not creds.get("botToken"):
        token = _hub_telegram_token()
        if token:
            creds = {**creds, "botToken": token}
    return creds


def uses_hub_bot(row: dict) -> bool:
    """Telegram row with no bot of its own: it only borrows the shared hub bot to post.

    A bot shared by many sellers must never be polled for messages; every seller
    would pull everyone's customers.
    """
    if str(row.get("platform") or "") != "telegram":
        return False
    return not _credentials(row).get("botToken") and bool(_hub_telegram_token())


def token_for(row: dict) -> str:
    creds = credentials_for(row)
    platform = str(row.get("platform") or "")
    if platform in {"telegram", "bale", "rubika"}:
        return str(creds.get("botToken") or "")
    return str(creds.get("accessToken") or "")


def unipile_account_id(row: dict) -> str:
    return str(_credentials(row).get("unipileAccountId") or "").strip()


def sendbox_account_id(row: dict) -> str:
    return str(_credentials(row).get("sendboxAccountId") or "").strip()


def is_connected(row: dict) -> bool:
    platform = str(row.get("platform") or "")
    creds = _credentials(row)
    if platform == "whatsapp":
        return bool(token_for(row) and creds.get("phoneNumberId"))
    if platform == "instagram":
        return bool(sendbox_account_id(row) or unipile_account_id(row) or token_for(row))
    return bool(token_for(row))


def post_target_for(row: dict) -> str:
    creds = _credentials(row)
    return str(row.get("postTarget") or creds.get("postTarget") or "").strip()


def publish_targets() -> list[dict]:
    rows = []
    for row in _rows():
        pub = public(row)
        platform = str(pub.get("platform") or "")
        if platform not in {"telegram", "instagram", "whatsapp"}:
            continue
        ready = bool(pub.get("connected"))
        hint = ""
        if platform == "telegram" and not pub.get("postTarget"):
            ready = False
            hint = "بات را ادمین کانال کن و آیدی کانال را در مقصد پست بگذار."
        elif platform == "whatsapp" and not pub.get("postTarget"):
            ready = False
            hint = "شماره مقصد را در کانال‌ها بگذار."
        elif platform == "instagram":
            if not sendbox_account_id(row):
                ready = False
                hint = IG_RECONNECT if (unipile_account_id(row) or token_for(row)) else str(
                    pub.get("error") or "این حساب وصل نیست."
                )
            else:
                ready = True
                hint = "قبل از ارسال، مخاطب دایرکت را انتخاب کن."
        elif not ready:
            hint = str(pub.get("error") or "این حساب وصل نیست.")
        rows.append({**pub, "ready": ready, "hint": hint})
    return rows


def public(row: dict) -> dict:
    creds = _credentials(row)
    platform = str(row.get("platform") or "")
    connected = is_connected(row)
    if platform == "whatsapp":
        connected = connected and bool(creds.get("phoneNumberId"))
    error = str(row.get("error") or "")
    needs_reconnect = False
    if platform == "instagram" and not sendbox_account_id(row) and (
        unipile_account_id(row) or token_for(row)
    ):
        connected = False
        needs_reconnect = True
        error = error or IG_RECONNECT
    post_target = str(row.get("postTarget") or creds.get("postTarget") or "").strip()
    return {
        "id": row.get("id"),
        "platform": platform,
        "label": PLATFORMS.get(platform, platform),
        "handle": row.get("handle") or "",
        "display": row.get("display") or "",
        "postTarget": post_target,
        "connected": connected,
        "verified": bool(row.get("verified")),
        "error": error,
        "needsReconnect": needs_reconnect,
        "voiceReady": bool(row.get("voiceReady")),
        "at": row.get("at") or 0,
    }


def list_accounts() -> dict:
    platforms = []
    hub_token = _hub_telegram_token()
    for spec in SPECS.values():
        item = dict(spec)
        item["fields"] = [dict(field) for field in spec["fields"]]
        if item["id"] == "telegram" and hub_token:
            item["hubBot"] = True
            item["help"] = (
                "بات سوزان روی هاب آماده است. بات را ادمین کانال یا گروه کن و آیدی همان کانال را در مقصد پست بگذار. "
                "برای انتشار پست توکن BotFather لازم نیست؛ برای دریافت دایرکت تلگرام باید بات خودت را وصل کنی."
            )
            for field in item["fields"]:
                if field["key"] == "botToken":
                    field["required"] = False
        platforms.append(item)
    return {
        "platforms": platforms,
        "accounts": [public(row) for row in _rows()],
        "hubTelegram": bool(hub_token),
    }


def add_account(
    *,
    platform: str,
    handle: str,
    secret: str = "",
    credentials: dict | None = None,
    skip_limit: bool = False,
) -> dict:
    key = platform.strip().lower()
    spec = SPECS.get(key)
    if spec is None:
        raise ValueError("این پلتفرم پشتیبانی نمی‌شود")
    creds = {str(name): str(value).strip() for name, value in dict(credentials or {}).items() if str(value).strip()}
    if secret.strip() and not any(str(creds.get(field["key"]) or "").strip() for field in spec["fields"] if field["secret"]):
        first_secret = next((field["key"] for field in spec["fields"] if field["secret"]), "accessToken")
        creds[first_secret] = secret.strip()
    handle = handle.strip()
    post_target = str(creds.pop("postTarget", "") or "").strip()
    if key == "telegram" and not handle and post_target:
        handle = post_target.lstrip("@")
    if key == "telegram" and not post_target and handle and not creds.get("botToken") and _hub_telegram_token():
        post_target = handle if handle.startswith("@") or handle.startswith("-") else f"@{handle.lstrip('@')}"
    if key == "whatsapp" and not post_target and handle:
        post_target = handle.lstrip("+").replace(" ", "")
    if not handle and not creds and not post_target:
        raise ValueError("شناسه حساب یا توکن اتصال را بنویس")
    if key == "telegram" and not creds.get("botToken") and not _hub_telegram_token() and not post_target:
        raise ValueError("توکن بات تلگرام را بگذار یا بات هاب سوزان را وصل کن.")
    if not skip_limit:
        blocked = allow_new_channel(len(_rows()))
        if blocked:
            raise ValueError(blocked)
    row = {
        "id": str(uuid4()),
        "platform": key,
        "handle": handle,
        "postTarget": post_target,
        "credentials": {str(name): str(value).strip() for name, value in creds.items() if str(value).strip()},
        "secret": "",
        "verified": False,
        "display": "",
        "error": "",
        "at": int(time.time()),
    }
    rows = _rows()
    rows.append(row)
    _save(rows)
    return {"account": public(row), **list_accounts()}


def apply_verify(account_id: str, result: dict) -> dict:
    rows = _rows()
    for row in rows:
        if str(row.get("id")) != account_id:
            continue
        handle = str(result.get("handle") or row.get("handle") or "").strip()
        if handle:
            row["handle"] = handle
        row["verified"] = bool(result.get("ok")) and bool(result.get("connected"))
        row["display"] = str(result.get("display") or "")
        row["error"] = "" if row["verified"] else str(result.get("error") or "")
        _save(rows)
        return public(row)
    raise KeyError("حساب پیدا نشد")


def mark_voice(account_id: str) -> None:
    rows = _rows()
    for row in rows:
        if str(row.get("id")) == account_id:
            row["voiceReady"] = True
            _save(rows)
            return


def mark_voice_handle(*, platform: str, handle: str) -> None:
    rows = _rows()
    for row in rows:
        if str(row.get("platform")) == platform and str(row.get("handle") or "") == handle:
            row["voiceReady"] = True
            _save(rows)
            return


def iter_accounts() -> list[dict]:
    return list(_rows())


def account_for_platform(platform: str) -> dict | None:
    key = platform.strip().lower()
    for row in _rows():
        if str(row.get("platform") or "") == key and is_connected(row):
            return row
    return None


def secret_for(account_id: str) -> dict | None:
    for row in _rows():
        if str(row.get("id")) == account_id:
            return row
    return None


def _ig_handle_key(handle: str) -> str:
    return handle.lstrip("@").lower().replace("-", "_").strip()


def _instagram_same(row: dict, *, handle: str, user_id: str, unipile_id: str = "", sendbox_id: str = "") -> bool:
    if str(row.get("platform") or "") != "instagram":
        return False
    creds = _credentials(row)
    if sendbox_id and str(creds.get("sendboxAccountId") or "") == sendbox_id:
        return True
    if unipile_id and str(creds.get("unipileAccountId") or "") == unipile_id:
        return True
    if user_id and str(creds.get("userId") or "") == user_id:
        return True
    left = _ig_handle_key(str(row.get("handle") or ""))
    right = _ig_handle_key(handle)
    return bool(left and right and left == right)


def upsert_instagram(
    *,
    handle: str,
    user_id: str,
    credentials: dict,
    display: str = "",
) -> dict:
    handle = handle.lstrip("@").strip()
    user_id = str(user_id or "").strip()
    creds = {str(name): str(value).strip() for name, value in dict(credentials or {}).items() if str(value).strip()}
    unipile_id = str(creds.get("unipileAccountId") or "").strip()
    sendbox_id = str(creds.get("sendboxAccountId") or "").strip()
    rows = _rows()
    now = int(time.time())
    match = None
    for row in rows:
        if _instagram_same(
            row, handle=handle, user_id=user_id, unipile_id=unipile_id, sendbox_id=sendbox_id
        ):
            match = row
            break
    if match is None:
        ig_rows = [row for row in rows if str(row.get("platform") or "") == "instagram"]
        if len(ig_rows) == 1:
            match = ig_rows[0]
    if match is not None:
        if handle:
            match["handle"] = handle
        if display:
            match["display"] = display
        match["credentials"] = {**_credentials(match), **creds}
        match["secret"] = ""
        match["error"] = ""
        match["at"] = now
        _save(rows)
        return public(match)
    added = add_account(platform="instagram", handle=handle, credentials=creds)
    account_id = str((added.get("account") or {}).get("id") or "")
    rows = _rows()
    for row in rows:
        if str(row.get("id")) != account_id:
            continue
        if display:
            row["display"] = display
        _save(rows)
        return public(row)
    return public(secret_for(account_id) or added["account"])


def update_instagram_token(account_id: str, *, access_token: str, expires_at: int, issued_at: int) -> dict:
    rows = _rows()
    for row in rows:
        if str(row.get("id")) != account_id:
            continue
        creds = _credentials(row)
        creds["accessToken"] = access_token.strip()
        creds["tokenExpiresAt"] = str(int(expires_at))
        creds["tokenIssuedAt"] = str(int(issued_at))
        row["credentials"] = creds
        row["at"] = int(time.time())
        _save(rows)
        return public(row)
    raise KeyError("حساب پیدا نشد")


def update_account(account_id: str, *, post_target: str | None = None) -> dict:
    rows = _rows()
    for row in rows:
        if str(row.get("id")) != account_id:
            continue
        if post_target is not None:
            row["postTarget"] = post_target.strip()
        _save(rows)
        return public(row)
    raise KeyError("حساب پیدا نشد")


def remove_account(account_id: str) -> dict:
    kept = [row for row in _rows() if str(row.get("id")) != account_id]
    _save(kept)
    return list_accounts()
