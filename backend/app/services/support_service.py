"""تیکت پشتیبانی ویترین و رسید کارت‌به‌کارت.

خریدار از ویترین تیکت می‌سازد یا رسید می‌گذارد؛ فروشنده در پنل جواب می‌دهد یا
پرداخت رسیدی را تأیید/رد می‌کند. شمارهٔ مشتری و متنش فقط در پروندهٔ خود فروشنده
می‌ماند و در لاگ نمی‌آید.
"""

from __future__ import annotations

import re
from time import time
from uuid import uuid4

from app.services.tenant_lock import tenant_file_lock
from app.state_store import current_tenant, iter_tenants, read_json, tenant_scope, write_json

TICKET_FILE = "support-tickets.json"
TICKET_STATUSES = ("open", "working", "closed")
TICKET_CATEGORIES = ("billing", "technical", "other")
RECEIPT_STATUS = "awaiting_receipt"


def _tickets() -> list[dict]:
    rows = read_json(TICKET_FILE, [])
    return rows if isinstance(rows, list) else []


def _save_tickets(rows: list[dict]) -> None:
    write_json(TICKET_FILE, rows[-400:])


def _clean(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _seller_category(category: str) -> str:
    token = str(category or "").strip().lower()
    if not token:
        return "other"
    if token not in TICKET_CATEGORIES:
        raise ValueError("دسته نامعتبر است")
    return token


def _with_category(row: dict) -> dict:
    return {**row, "category": str(row.get("category") or "") or "other"}


def create_ticket(
    *,
    subject: str,
    text: str,
    phone: str = "",
    order_no: str = "",
    image_name: str = "",
    kind: str = "storefront",
    category: str = "",
) -> dict:
    kind_name = str(kind or "storefront").strip()[:16]
    row = {
        "id": uuid4().hex[:12],
        "subject": _clean(subject, 80) or "تیکت ویترین",
        "text": _clean(text, 2000),
        "phone": _clean(phone, 20),
        "orderNo": _clean(order_no, 40),
        "image": _clean(image_name, 120),
        "kind": kind_name,
        "status": "open",
        "replies": [],
        "at": int(time()),
        "tenant": current_tenant() or "",
    }
    if kind_name == "seller":
        row["category"] = _seller_category(category)
    with tenant_file_lock("support"):
        rows = _tickets()
        rows.append(row)
        _save_tickets(rows)
    if kind_name == "seller":
        # تیکت فروشنده به پشتیبانی سوزان؛ رویداد پایش + هشدار تلگرام به مالک.
        from app.services.observe_client import emit_later

        emit_later(
            kind="support",
            title="seller-ticket",
            surface="panel",
            status="open",
            payload={"ticketId": row["id"]},
        )

        async def _ping_telegram() -> None:
            from app.services import telegram_alert_service

            await telegram_alert_service.seller_ticket_alert(
                row["id"], row["subject"], row.get("tenant") or "", str(row.get("category") or "")
            )

        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(_ping_telegram())
        except RuntimeError:
            import threading

            threading.Thread(target=lambda: asyncio.run(_ping_telegram()), daemon=True).start()
    return {"ticketId": row["id"], "status": row["status"]}


def list_tickets(*, kind: str = "") -> list[dict]:
    rows = _tickets()
    wanted = str(kind or "").strip().lower()
    if wanted:
        rows = [row for row in rows if str(row.get("kind") or "storefront") == wanted]
    rows = sorted(rows, key=lambda row: -int(row.get("at") or 0))
    if wanted == "seller":
        rows = [_with_category(row) for row in rows]
    return rows


def list_all_tickets_for_hub_admin() -> list[dict]:
    """تیکت‌های همهٔ فروشندگان به پشتیبانی سوزان؛ فقط مدیر هاب می‌بیند (بدون راز)."""
    out: list[dict] = []
    for phone in iter_tenants():
        with tenant_scope(phone):
            for row in _tickets():
                if str(row.get("kind") or "storefront") == "seller":
                    out.append(_with_category({**row, "tenant": phone}))
    return sorted(out, key=lambda row: -int(row.get("at") or 0))


def reply_hub_ticket(ticket_id: str, *, text: str, status: str = "") -> dict:
    """پاسخ مدیر به تیکت یک فروشنده؛ تیکت در پوشهٔ همان فروشنده می‌ماند."""
    ident = str(ticket_id or "").strip()
    for phone in iter_tenants():
        with tenant_scope(phone):
            row = next(
                (
                    item
                    for item in _tickets()
                    if str(item.get("id")) == ident and str(item.get("kind") or "storefront") == "seller"
                ),
                None,
            )
            if row is None:
                continue
            return {**reply_ticket(ident, text=text, status=status, by="support"), "tenant": phone}
    raise ValueError("تیکت پیدا نشد")


def reply_ticket(ticket_id: str, *, text: str, status: str = "", by: str = "seller") -> dict:
    ident = str(ticket_id or "").strip()
    with tenant_file_lock("support"):
        rows = _tickets()
        row = next((item for item in rows if str(item.get("id")) == ident), None)
        if row is None:
            raise ValueError("تیکت پیدا نشد")
        message = _clean(text, 2000)
        if message:
            row.setdefault("replies", []).append({"text": message, "at": int(time()), "by": by})
        wanted = str(status or "").strip().lower()
        if wanted in TICKET_STATUSES:
            row["status"] = wanted
        _save_tickets(rows)
        return row


def find_ticket(ticket_id: str) -> dict | None:
    ident = str(ticket_id or "").strip()
    return next((item for item in _tickets() if str(item.get("id")) == ident), None)
