"""تیکت پشتیبانی ویترین و رسید کارت‌به‌کارت.

خریدار از ویترین تیکت می‌سازد یا رسید می‌گذارد؛ فروشنده در پنل جواب می‌دهد یا
پرداخت رسیدی را تأیید/رد می‌کند. شمارهٔ مشتری و متنش فقط در پروندهٔ خود فروشنده
می‌ماند و در لاگ نمی‌آید.
"""

from __future__ import annotations

import re
from time import time
from uuid import uuid4

from app.state_store import current_tenant, read_json, write_json

TICKET_FILE = "support-tickets.json"
TICKET_STATUSES = ("open", "working", "closed")
RECEIPT_STATUS = "awaiting_receipt"


def _tickets() -> list[dict]:
    rows = read_json(TICKET_FILE, [])
    return rows if isinstance(rows, list) else []


def _save_tickets(rows: list[dict]) -> None:
    write_json(TICKET_FILE, rows[-400:])


def _clean(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def create_ticket(
    *,
    subject: str,
    text: str,
    phone: str = "",
    order_no: str = "",
    image_name: str = "",
) -> dict:
    row = {
        "id": uuid4().hex[:12],
        "subject": _clean(subject, 80) or "تیکت ویترین",
        "text": _clean(text, 2000),
        "phone": _clean(phone, 20),
        "orderNo": _clean(order_no, 40),
        "image": _clean(image_name, 120),
        "status": "open",
        "replies": [],
        "at": int(time()),
        "tenant": current_tenant() or "",
    }
    rows = _tickets()
    rows.append(row)
    _save_tickets(rows)
    return {"ticketId": row["id"], "status": row["status"]}


def list_tickets() -> list[dict]:
    return sorted(_tickets(), key=lambda row: -int(row.get("at") or 0))


def reply_ticket(ticket_id: str, *, text: str, status: str = "") -> dict:
    ident = str(ticket_id or "").strip()
    rows = _tickets()
    row = next((item for item in rows if str(item.get("id")) == ident), None)
    if row is None:
        raise ValueError("تیکت پیدا نشد")
    message = _clean(text, 2000)
    if message:
        row.setdefault("replies", []).append({"text": message, "at": int(time()), "by": "seller"})
    wanted = str(status or "").strip().lower()
    if wanted in TICKET_STATUSES:
        row["status"] = wanted
    _save_tickets(rows)
    return row


def find_ticket(ticket_id: str) -> dict | None:
    ident = str(ticket_id or "").strip()
    return next((item for item in _tickets() if str(item.get("id")) == ident), None)
