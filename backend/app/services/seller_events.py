"""Sozan speaks first: events from the shop reach the seller's chat without the seller asking.

Two sources:
- the moment something happens (pay_service: a receipt arrived, an order was paid, stock ran short), and
- a sweep every SWEEP_SECONDS over every shop that finds work left lying: a paid order not shipped after two days,
  a receipt waiting a day, a shipment a week old that was never marked delivered, a «needs action» order still open.

Every event is said once (its key is kept in EVENTS_FILE) and lands in the seller's active chat thread. When the
next step is clear, a confirmation card for it comes with the message (approve this receipt, mark it delivered); the
agent never does the step itself. A card is only placed when the thread has none open and no turn is running, so an
event never replaces what the seller is doing. Each order reminder is also written into the order's timeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from app.services.observe_client import emit_later
from app.state_store import iter_tenants, read_json, tenant_scope, write_json

log = logging.getLogger("sozan.events")

EVENTS_FILE = "seller-events.json"
SWEEP_SECONDS = 900
KEEP_KEYS = 500
HOUR = 3600
SHIP_LATE = 48 * HOUR
RECEIPT_LATE = 24 * HOUR
DELIVERY_CHECK = 7 * 24 * HOUR
ACTION_LATE = 24 * HOUR
# Orders made before stages existed (2026-10-10 00:00 UTC) have no stage although many were shipped long ago:
# reminding about them would be wrong, so the sweep starts after this moment.
SINCE = 1791590400
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _state() -> dict:
    row = read_json(EVENTS_FILE, {})
    if not isinstance(row, dict):
        row = {}
    row["sent"] = row.get("sent") if isinstance(row.get("sent"), dict) else {}
    row["unseen"] = int(row.get("unseen") or 0)
    return row


def _save(row: dict) -> None:
    sent = row.get("sent") or {}
    if len(sent) > KEEP_KEYS:
        row["sent"] = dict(sorted(sent.items(), key=lambda item: int(item[1] or 0))[-KEEP_KEYS:])
    write_json(EVENTS_FILE, row)


def unseen() -> int:
    return int(_state().get("unseen") or 0)


def mark_seen() -> None:
    row = _state()
    if row["unseen"]:
        row["unseen"] = 0
        _save(row)


def _place_card(tool: str, args: dict) -> bool:
    """The card for the next step, in the bound thread, unless one is open or a turn is running."""
    from app.services import router_service as rs, router_tools

    if rs.turn_busy() or rs._card_open(rs._pending()):
        return False
    if router_tools.check(tool, args, "") or rs._reject_write(tool, args):
        return False
    summary = router_tools.summary(tool, args, "")
    if not summary:
        return False
    card_id = str(uuid4())
    stored = {
        "id": card_id,
        "tool": tool,
        "arguments": dict(args),
        "summary": summary,
        "sourceText": "",
        "viewPath": "",
        "viewTarget": "",
        "expiresAt": time.time() + rs.CARD_TTL,
        "turnId": "",
        "event": True,
    }
    rs._commit("assistant", summary, set_pending=stored, kind="confirm", confirmId=card_id, tool=tool)
    return True


def announce(key: str, text: str, *, card: tuple[str, dict] | None = None) -> bool:
    """Say `text` once (per `key`) in the seller's active thread, with the card when it can be placed."""
    row = _state()
    if key in row["sent"]:
        return False
    from app.services import router_service as rs

    try:
        thread = rs.resolve_thread("")
        rs.post_notice(thread, text)
        carded = _place_card(*card) if card else False
    except Exception:
        log.exception("seller event failed key=%s", key)
        return False
    row = _state()
    row["sent"][key] = int(time.time())
    row["unseen"] = int(row.get("unseen") or 0) + 1
    _save(row)
    emit_later(kind="agent", title="seller-event", surface="router", status="ok", payload={"event": key.split(":")[0], "card": carded})
    from app.services import seller_alerts

    seller_alerts.alert_soon(key.split(":")[0], text)  # outside the panel: push, else SMS for urgent ones
    return True


def _money(amount: object) -> str:
    return f"{int(amount or 0):,}".replace(",", "٬").translate(_FA)


def _label(row: dict) -> str:
    who = str(row.get("customer") or "").strip()
    who = f"، {who}" if who and who != "مشتری" else ""
    return f"«{row.get('title') or 'سفارش'}» ({_money(row.get('amount'))} تومان{who})"


def _say_name(row: dict) -> str:
    who = str(row.get("customer") or "").strip()
    return who if who and who != "مشتری" else str(row.get("title") or "")


# ---------------------------------------------------------------- at the moment it happens (pay_service)


def receipt_arrived(row: dict) -> None:
    announce(
        f"receipt:{row.get('id')}",
        f"رسید کارت‌به‌کارت برای {_label(row)} آمد. حسابت را ببین؛ اگر پول نشسته کارت زیر را تأیید کن، اگر نه بگو «رسید {_say_name(row)} رو رد کن».",
        card=("approve_receipt", {"order": str(row.get("id")), "approve": True}),
    )


def order_paid(row: dict, text: str) -> None:
    announce(f"paid:{row.get('id')}", text)


def shortage(row: dict, text: str) -> None:
    announce(f"short:{row.get('id')}", text)


# ---------------------------------------------------------------- the sweep


def _since(row: dict, event: str, fallback: str = "at") -> int:
    for item in reversed(row.get("history") or []):
        if isinstance(item, dict) and item.get("event") == event:
            return int(item.get("at") or 0)
    return int(row.get(fallback) or 0)


def due(rows: list[dict], now: float) -> list[tuple[str, dict, str, tuple[str, dict] | None]]:
    """(key, order, sentence, card) for every reminder this shop is owed now; `rows` are raw orders."""
    out: list[tuple[str, dict, str, tuple[str, dict] | None]] = []
    for row in rows:
        oid = str(row.get("id") or "")
        status = str(row.get("status") or "")
        stage = str(row.get("stage") or "")
        if not oid or int(row.get("at") or 0) < SINCE:
            continue
        if status == "paid" and isinstance(row.get("needsAction"), dict) and stage not in {"cancelled", "shipped", "delivered"}:
            if now - _since(row, "needsAction", "paidAt") >= ACTION_LATE:
                out.append((f"action24:{oid}", row, f"سفارش {_label(row)} هنوز «نیازمند اقدام» است: موجودی کم بود. با مشتری هماهنگ کن و بعد بگو «سفارش {_say_name(row)} رو لغو کن» یا وقتی جایگزین را فرستادی «… رو فرستادم».", None))
                continue
        if status == "paid" and stage in {"", "preparing"} and now - int(row.get("paidAt") or row.get("at") or 0) >= SHIP_LATE:
            out.append((f"ship48:{oid}", row, f"سفارش {_label(row)} دو روز است پرداخت شده و هنوز ارسال نشده. وقتی فرستادی بگو «سفارش {_say_name(row)} رو فرستادم، کد رهگیری …».", None))
        elif status == "awaiting_receipt" and now - _since(row, "receipt") >= RECEIPT_LATE:
            out.append((f"receipt24:{oid}", row, f"رسید {_label(row)} از دیروز منتظر تأیید توست.", ("approve_receipt", {"order": oid, "approve": True})))
        elif status == "paid" and stage == "shipped" and now - int(row.get("stageAt") or _since(row, "shipped")) >= DELIVERY_CHECK:
            out.append((f"delivered7:{oid}", row, f"سفارش {_label(row)} یک هفته پیش ارسال شد. اگر به دست مشتری رسیده، تحویلش را ثبت کن.", ("update_order", {"order": oid, "stage": "delivered"})))
    return out


def sweep_shop(now: float | None = None) -> int:
    """Reminders for the current tenant. Returns how many were said."""
    from app.services import pay_service
    from app.services.tenant_lock import tenant_file_lock

    now = time.time() if now is None else now
    said = 0
    for key, row, text, card in due(pay_service._orders(), now):
        if not announce(key, text, card=card):
            continue
        said += 1
        with tenant_file_lock("pay-orders"):
            orders = pay_service._orders()
            fresh = next((item for item in orders if str(item.get("id")) == str(row.get("id"))), None)
            if fresh is not None:
                pay_service.log_event(fresh, "reminded", key.split(":")[0])
                pay_service._save_orders(orders)
    return said


def sweep_all(now: float | None = None) -> dict:
    shops = said = 0
    for phone in iter_tenants():
        try:
            with tenant_scope(phone):
                if not read_json("pay-orders.json", []):
                    continue
                shops += 1
                said += sweep_shop(now)
        except Exception:
            log.exception("seller sweep failed")
    return {"shops": shops, "said": said}


async def loop() -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(sweep_all)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("seller sweep loop failed")
        await asyncio.sleep(SWEEP_SECONDS)
