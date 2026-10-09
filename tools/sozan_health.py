#!/usr/bin/env python3
"""Read-only health of the running hub, then one live turn on each harness loop.

The live turns use only the lab phone. They cancel any seller card, never confirm,
and fail if the lab shop files change. Nothing here restarts a service.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.lab_account import LAB_PHONE  # noqa: E402
from app.models.user import User  # noqa: E402
from app.redis_client import redis_client  # noqa: E402
from app.security import encode_token  # noqa: E402
from app.services import admin_health_service  # noqa: E402
from app.services.pipeline_release import BEHAVIOR_VERSION  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

API = "http://127.0.0.1:8012"
PANEL = "http://127.0.0.1:3010/login"
OBSERVE = ("127.0.0.1", 9292)
LIVE_SHOP = "09135409482"
WRITE_CARDS = frozenset({"edit_shop", "add_product", "shop_chat", "publish_post"})
FINGERPRINTS = (
    "shop.json",
    "products.json",
    "shop-workspace/files/app/brand-vars.css",
)
SELLER_TEXT = "وضعیت فروشگاه را بگو"
SHOP_TEXT = "فروشگاه الان آماده‌ست؟"
INBOX_TEXT = "قیمت چنده؟"
TURN_TIMEOUT = 70.0


def _say(level: str, name: str, detail: str) -> None:
    print(f"{level}  {name}  {detail}")


def _fingerprints(tenant: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in FINGERPRINTS:
        path = tenant / rel
        if not path.is_file():
            out[rel] = "missing"
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _jsonl_from(path: Path, start: int) -> list[dict]:
    if not path.is_file():
        return []
    size = path.stat().st_size
    if size < start:
        start = 0
    raw = path.read_bytes()[start:].decode("utf-8", errors="replace")
    rows: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _last_text(payload: dict) -> str:
    rows = payload.get("messages")
    if not isinstance(rows, list):
        return str(payload.get("text") or "")
    for item in reversed(rows):
        if isinstance(item, dict) and item.get("role") == "assistant":
            return str(item.get("text") or "")
    return ""


def _observe_open() -> bool:
    try:
        with socket.create_connection(OBSERVE, timeout=2):
            return True
    except OSError:
        return False


async def _db_ok() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return ""
    except Exception as exc:
        return type(exc).__name__


async def _redis_ok() -> str:
    try:
        pong = await redis_client.ping()
        return "" if pong else "no-pong"
    except Exception as exc:
        return type(exc).__name__


async def _lab_token() -> str:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.phone == LAB_PHONE))).scalar_one_or_none()
    if user is None or user.phone != LAB_PHONE or user.phone == LIVE_SHOP:
        return ""
    return encode_token(user.id, user.role, ttl_minutes=15)


def components(db_error: str, redis_error: str) -> int:
    """Service lines are shown here. A down service is counted once, inside the snapshot alerts."""
    red = 0
    snap = admin_health_service.snapshot()
    services = snap.get("services") if isinstance(snap.get("services"), dict) else {}
    for name in admin_health_service.SERVICES:
        state = str(services.get(name) or "unknown")
        _say("سبز" if state == "active" else "قرمز", name, state)
    try:
        res = httpx.get(f"{API}/health", timeout=6, trust_env=False)
        ok = res.status_code == 200
        _say("سبز" if ok else "قرمز", "api-health", str(res.status_code))
        if not ok:
            red += 1
    except Exception as exc:
        _say("قرمز", "api-health", type(exc).__name__)
        red += 1
    try:
        panel = httpx.get(PANEL, timeout=6, trust_env=False)
        _say("سبز", "panel", str(panel.status_code))
    except Exception as exc:
        _say("قرمز", "panel", type(exc).__name__)
        red += 1
    if db_error:
        _say("قرمز", "postgres", db_error)
        red += 1
    else:
        _say("سبز", "postgres", "پاسخ داد")
    if redis_error:
        _say("قرمز", "redis", redis_error)
        red += 1
    else:
        _say("سبز", "redis", "پاسخ داد")
    if _observe_open():
        _say("سبز", "observe", "9292 باز است")
    else:
        _say("زرد", "observe", "9292 بسته است؛ رویداد در صندوق خروجی می‌ماند")
    machine = snap.get("machine") if isinstance(snap.get("machine"), dict) else {}
    backups = snap.get("backups") if isinstance(snap.get("backups"), dict) else {}
    ai = snap.get("ai") if isinstance(snap.get("ai"), dict) else {}
    _say("گزارش", "disk", f"{machine.get('diskFreeGb', '?')} گیگ آزاد")
    _say("گزارش", "backup", f"سن {backups.get('lastAgeHours', '?')} ساعت")
    left = ai.get("openrouterLeftUsd")
    _say("گزارش", "openrouter", f"اعتبار {left if left is not None else '?'}")
    for alert in snap.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        level = "قرمز" if alert.get("level") == "red" else "زرد"
        if level == "قرمز":
            red += 1
        _say(level, "هشدار", str(alert.get("text") or ""))
    return red


async def _drill_async() -> int:
    if LAB_PHONE == LIVE_SHOP:
        _say("قرمز", "دور", "حساب آزمایشی با فروشگاه زنده یکی است")
        return 1
    token = await _lab_token()
    if not token:
        _say("قرمز", "دور", "حساب آزمایشی در پایگاه نیست")
        return 1
    tenant = settings.state_path / "tenants" / LAB_PHONE
    if LIVE_SHOP in tenant.parts:
        _say("قرمز", "دور", "مسیر تنانت فروشگاه زنده است")
        return 1
    before = _fingerprints(tenant)
    turns = tenant / "router-turns.jsonl"
    outbox = tenant / "observe-outbox.jsonl"
    turns_at = turns.stat().st_size if turns.is_file() else 0
    outbox_at = outbox.stat().st_size if outbox.is_file() else 0
    red = 0
    headers = {"Authorization": f"Bearer {token}"}
    card_turn = ""
    cancelled = False
    async with httpx.AsyncClient(timeout=TURN_TIMEOUT, trust_env=False) as client:
        opened = await client.post(f"{API}/chat/threads", headers=headers)
        thread_id = ""
        if opened.status_code == 200:
            thread_id = str((opened.json() or {}).get("threadId") or "")
        if not thread_id:
            _say("قرمز", "فروشنده", f"رشته باز نشد ({opened.status_code})")
            red += 1
        else:
            res = await client.post(
                f"{API}/chat",
                headers={**headers, "Idempotency-Key": f"health-{uuid.uuid4().hex}"},
                json={"text": SELLER_TEXT, "threadId": thread_id},
            )
            body = res.json() if res.status_code == 200 else {}
            text = _last_text(body if isinstance(body, dict) else {})
            pending = body.get("pendingConfirm") if isinstance(body, dict) else None
            tool = str((pending or {}).get("tool") or "") if isinstance(pending, dict) else ""
            if res.status_code != 200 or not text.strip():
                _say("قرمز", "فروشنده", f"کد {res.status_code}")
                red += 1
            elif tool in WRITE_CARDS:
                _say("قرمز", "فروشنده", f"کارت نوشتنی {tool}")
                red += 1
            else:
                _say("سبز", "فروشنده", text.strip()[:80])
            if isinstance(pending, dict) and pending.get("id"):
                new_rows = _jsonl_from(turns, turns_at)
                card_turn = str((new_rows[-1] if new_rows else {}).get("turnId") or "")
                cancel = await client.post(
                    f"{API}/chat",
                    headers={**headers, "Idempotency-Key": f"health-cancel-{uuid.uuid4().hex}"},
                    json={"text": "", "threadId": thread_id, "cancelId": pending["id"]},
                )
                cancelled = cancel.status_code == 200
                if not cancelled:
                    _say("قرمز", "فروشنده", "کارت بسته نشد")
                    red += 1
        shop = await client.post(
            f"{API}/shop/chat",
            headers={**headers, "Idempotency-Key": f"health-shop-{uuid.uuid4().hex}"},
            json={"text": SHOP_TEXT},
        )
        shop_body = shop.json() if shop.status_code == 200 else {}
        shop_text = _last_text(shop_body if isinstance(shop_body, dict) else {})
        if shop.status_code != 200 or not shop_text.strip():
            _say("قرمز", "فروشگاه", f"کد {shop.status_code}")
            red += 1
        else:
            _say("سبز", "فروشگاه", shop_text.strip()[:80])
        inbox = await client.post(
            f"{API}/inbox/lab-turn",
            headers={**headers, "Idempotency-Key": f"health-inbox-{uuid.uuid4().hex}"},
            json={"text": INBOX_TEXT},
        )
        inbox_body = inbox.json() if inbox.status_code == 200 else {}
        inbox_text = str((inbox_body or {}).get("text") or "") if isinstance(inbox_body, dict) else ""
        if inbox.status_code != 200 or not inbox_text.strip():
            _say("قرمز", "دایرکت", f"کد {inbox.status_code}")
            red += 1
        else:
            _say("سبز", "دایرکت", inbox_text.strip()[:80])
    after = _fingerprints(tenant)
    changed = [name for name in FINGERPRINTS if before.get(name) != after.get(name)]
    if changed:
        _say("قرمز", "فایل", "، ".join(changed))
        red += 1
    else:
        _say("سبز", "فایل", "اثرانگشت فروشگاه آزمایشی همان است")
    fresh = _jsonl_from(turns, turns_at)
    if not fresh or not str(fresh[0].get("turnId") or "").strip():
        _say("قرمز", "پاکت", "ردیف نوبت شناسه ندارد")
        red += 1
    else:
        _say("سبز", "پاکت", "شناسهٔ نوبت هست")
    await asyncio.sleep(1.5)
    events = _jsonl_from(outbox, outbox_at)
    for row in events:
        if row.get("dropped") and not row.get("behaviorVersion"):
            continue
        if str(row.get("behaviorVersion") or "") != BEHAVIOR_VERSION:
            _say("قرمز", "پاکت", "نسخهٔ رفتار صندوق خروجی فرق دارد")
            red += 1
            break
    if cancelled:
        cancel_rows = [row for row in events if row.get("title") == "router-cancel"]
        if cancel_rows:
            parent = str(cancel_rows[-1].get("parentId") or "")
            if not card_turn or parent != card_turn:
                _say("قرمز", "پاکت", "شناسهٔ والد لغو با نوبت کارت یکی نیست")
                red += 1
            else:
                _say("سبز", "پاکت", "لغو به همان نوبت وصل است")
        elif _observe_open():
            _say("زرد", "پاکت", "رویداد لغو به مشاهده رفته است")
        else:
            _say("قرمز", "پاکت", "رویداد لغو در صندوق خروجی نیست")
            red += 1
    return red


async def _amain() -> int:
    try:
        db_error, redis_error = await asyncio.gather(_db_ok(), _redis_ok())
        red = await asyncio.to_thread(components, db_error, redis_error)
        red += await _drill_async()
        return red
    finally:
        await redis_client.aclose()
        await engine.dispose()


def main() -> int:
    red = asyncio.run(_amain())
    print("سالم" if red == 0 else f"خراب  {red}")
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
