"""The seller hears about an event outside the panel: a web push on the phone or computer, else an SMS.

Every seller_events.announce also calls `alert`. Web push (RFC 8030/8291/8292) needs no account: Sozan makes its
own VAPID key once (PUSH_KEY_FILE, shared state) and the panel's service worker (`/sozan-push-sw.js`) shows the
notification; the payload is encrypted end to end (aes128gcm), so the push service (Google, Mozilla, Apple) cannot
read it. A subscription endpoint is only ever one of the known push services, so the server never posts to an
address a browser made up. A seller with no subscription gets an SMS for the urgent events only (an order paid, a
receipt, a stock shortage), through an approved Melipayamak template (MELIPAYAMAK_SELLER_BODY_ID; empty = off),
at most SMS_PER_DAY a day, paid by Sozan and not counted against the seller's plan.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.observe_client import emit_later
from app.state_store import current_tenant, read_json, shared_lock, write_json

log = logging.getLogger("sozan.alerts")

PUSH_KEY_FILE = "push-vapid.json"
SUBS_FILE = "push-subs.json"
SMS_FILE = "seller-alert-sms.json"
MAX_SUBS = 5
SMS_PER_DAY = 5
URGENT = frozenset({"paid", "receipt", "short"})
SMS_WORDS = {"paid": "سفارش تازه", "receipt": "رسید کارت‌به‌کارت تازه", "short": "سفارشی که نیازمند اقدام است"}
PUSH_HOSTS = re.compile(
    r"^(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|[a-z0-9-]+\.push\.services\.mozilla\.com"
    r"|web\.push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com)$"
)
TTL = 24 * 3600


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------- Sozan's own VAPID key


def _key() -> dict:
    """{"private": PEM, "public": base64url point}; made once and kept."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    with shared_lock():
        stored = read_json(PUSH_KEY_FILE, {}, shared=True)
        if isinstance(stored, dict) and stored.get("private") and stored.get("public"):
            return stored
        private = ec.generate_private_key(ec.SECP256R1())
        pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        point = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        stored = {"private": pem, "public": _b64(point), "at": int(time.time())}
        write_json(PUSH_KEY_FILE, stored, shared=True)
        return stored


def public_key() -> str:
    return str(_key()["public"])


# ---------------------------------------------------------------- the seller's devices


def _subs() -> list[dict]:
    rows = read_json(SUBS_FILE, [])
    return [row for row in rows if isinstance(row, dict) and row.get("endpoint")] if isinstance(rows, list) else []


def subscribe(endpoint: str, p256dh: str, auth: str, agent: str = "") -> int:
    parts = urlsplit(str(endpoint or ""))
    if parts.scheme != "https" or not PUSH_HOSTS.match(parts.hostname or ""):
        raise ValueError("این نشانی اعلان پذیرفته نیست.")
    try:
        if len(_unb64(p256dh)) != 65 or len(_unb64(auth)) != 16:
            raise ValueError
    except Exception as exc:
        raise ValueError("کلید اعلان درست نیست.") from exc
    rows = [row for row in _subs() if row.get("endpoint") != endpoint]
    rows.append({"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "agent": str(agent or "")[:120], "at": int(time.time())})
    write_json(SUBS_FILE, rows[-MAX_SUBS:])
    return len(rows[-MAX_SUBS:])


def unsubscribe(endpoint: str) -> int:
    rows = [row for row in _subs() if row.get("endpoint") != endpoint]
    write_json(SUBS_FILE, rows)
    return len(rows)


def devices() -> int:
    return len(_subs())


# ---------------------------------------------------------------- web push


def _encrypt(sub: dict, payload: bytes) -> bytes:
    import http_ece
    from cryptography.hazmat.primitives.asymmetric import ec

    server = ec.generate_private_key(ec.SECP256R1())
    return http_ece.encrypt(
        payload,
        private_key=server,
        dh=_unb64(str(sub["p256dh"])),
        auth_secret=_unb64(str(sub["auth"])),
        version="aes128gcm",
    )


def _vapid(endpoint: str) -> str:
    import jwt

    parts = urlsplit(endpoint)
    key = _key()
    token = jwt.encode(
        {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": "https://app.sozan-core.ir"},
        key["private"],
        algorithm="ES256",
    )
    return f"vapid t={token}, k={key['public']}"


async def push(title: str, body: str, *, url: str = "/chat", tag: str = "") -> dict:
    """Send to every device of the current tenant. Gone devices (404/410) are dropped."""
    rows = _subs()
    if not rows:
        return {"sent": 0, "devices": 0}
    payload = json.dumps({"title": title, "body": body[:180], "url": url, "tag": tag or "sozan"}, ensure_ascii=False).encode()
    sent = 0
    gone: list[str] = []
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for sub in rows:
            endpoint = str(sub["endpoint"])
            try:
                res = await client.post(
                    endpoint,
                    content=_encrypt(sub, payload),
                    headers={
                        "Authorization": _vapid(endpoint),
                        "Content-Encoding": "aes128gcm",
                        "Content-Type": "application/octet-stream",
                        "TTL": str(TTL),
                        "Urgency": "high",
                    },
                )
            except Exception as exc:
                log.warning("push failed host=%s err=%s", urlsplit(endpoint).hostname, type(exc).__name__)
                continue
            if res.status_code in (404, 410):
                gone.append(endpoint)
            elif res.status_code < 300:
                sent += 1
            else:
                log.warning("push rejected host=%s http=%s", urlsplit(endpoint).hostname, res.status_code)
    for endpoint in gone:
        unsubscribe(endpoint)
    return {"sent": sent, "devices": len(rows) - len(gone), "gone": len(gone)}


# ---------------------------------------------------------------- SMS when there is no device


def _sms_allowed() -> bool:
    today = time.strftime("%Y-%m-%d")
    row = read_json(SMS_FILE, {})
    count = int(row.get("count") or 0) if isinstance(row, dict) and row.get("day") == today else 0
    if count >= SMS_PER_DAY:
        return False
    write_json(SMS_FILE, {"day": today, "count": count + 1})
    return True


async def _sms(kind: str) -> str:
    body_id = str(settings.melipayamak_seller_body_id or "").strip()
    phone = current_tenant()
    if not body_id or kind not in URGENT or not phone:
        return ""
    if not _sms_allowed():
        return "sms-cap"
    from app.services import melipayamak_otp_service

    try:
        await melipayamak_otp_service.send_pattern(phone, SMS_WORDS[kind], body_id=body_id, surface="alerts")
    except Exception as exc:
        log.warning("seller sms failed err=%s", type(exc).__name__)
        return "sms-failed"
    return "sms"


async def alert(kind: str, text: str) -> str:
    """push, sms, or nothing. `kind` is the event's key prefix (paid, receipt, short, ship48, …)."""
    first = re.split(r"(?<=[.؟!])\s", str(text or "").strip(), maxsplit=1)[0]
    try:
        out = await push("سوزان", first, url="/chat", tag=kind)
    except Exception:
        log.exception("push alert failed")
        out = {"sent": 0, "devices": 0}
    channel = "push" if out.get("sent") else ""
    if not channel and not out.get("devices"):
        channel = await _sms(kind)
    emit_later(kind="agent", title="seller-alert", surface="router", status="ok" if channel in {"push", "sms"} else "skipped", payload={"event": kind, "channel": channel or "none"})
    return channel or "none"


def alert_soon(kind: str, text: str) -> None:
    """From synchronous code (a payment callback, the sweep thread): never block or fail the caller."""
    import asyncio
    import contextvars

    async def run() -> None:
        try:
            await alert(kind, text)
        except Exception:
            log.exception("alert failed")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(run(), context=contextvars.copy_context())
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)
        return
    try:
        asyncio.run(run())
    except Exception:
        log.exception("alert failed")


_PENDING: set = set()
