"""Seller-chat tools for an order after payment: move it (preparing, shipped with a tracking code, delivered,
cancelled) and approve or reject a card-to-card receipt. Both are writes, so both show a card first; the card
names the order, the customer and how the customer will be told. The work itself is order_flow_service and
pay_service.review_receipt; this module only finds the order the seller means and words the card.
"""

from __future__ import annotations

import re

from app.services.router_text import fa_digits, fa_money, fold
from app.services.router_tools import Tool, register

NAMES = frozenset({"update_order", "approve_receipt"})

_SHIPPED = re.compile(
    r"فرستادم|فرستادیم|ارسال\s*(?:کردم|کردیم|شد)|ارسالش\s*کردم|پست\s*(?:کردم|شد)|(?:دادم|دادیم)\s*(?:پست|پیک|تیپاکس|چاپار)"
    r"|تحویل\s*(?:پست|پیک|تیپاکس|چاپار)\s*(?:دادم|شد)"
)
_DELIVERED = re.compile(r"تحویل\s*(?:شد|داده\s*شد|گرفت|دادم)(?!\s*(?:پست|پیک|تیپاکس))|(?:به\s*)?دستش\s*رسید|رسید\s*دستش")
_PREPARING = re.compile(r"دارم\s*آماده|آماده\s*(?:می\s*‌?کنم|میکنم|سازی)|بسته\s*‌?بندی")
_CANCELLED = re.compile(r"لغو|کنسل")
_RECEIPT_OK = re.compile(r"رسید\S*\s.{0,30}(?:تأیید|تایید|قبول|درسته|اوکیه)|(?:تأیید|تایید)\S*\s.{0,20}رسید")
_RECEIPT_NO = re.compile(r"رسید\S*\s.{0,30}(?:رد\s*کن|رد\s*بشه|قبول\s*نیست|جعلی|نرسیده|نیومده)")
_TRACKING = re.compile(r"(?:رهگیری|پیگیری|بارکد|کد)\D{0,14}?([0-9A-Za-z-]{6,30})")
_LONG_CODE = re.compile(r"(?<![0-9A-Za-z])(\d{10,30})(?![0-9A-Za-z])")
_LATEST = re.compile(r"سفارش\s*آخر|آخرین\s*سفارش|سفارش\s*آخری")
_CONTENT = re.compile(r"اینستا|کپشن|استوری|ریلز|تبلیغ")
_CARRIERS = (("تیپاکس", "تیپاکس"), ("چاپار", "چاپار"), ("ماهکس", "ماهکس"), ("پیک", "پیک"), ("پست", "پست"))


def _loose(value: str) -> str:
    return fold(value).replace(" ", "")


def _quote(value: object) -> str:
    return f"«{value}»"


def stage_in(text: str) -> str:
    if _CANCELLED.search(text):
        return "cancelled"
    if _DELIVERED.search(text):
        return "delivered"
    if _SHIPPED.search(text):
        return "shipped"
    if _PREPARING.search(text):
        return "preparing"
    return ""


def tracking_in(text: str) -> str:
    folded = fold(text)
    found = _TRACKING.search(folded) or _LONG_CODE.search(folded)
    return found.group(1) if found else ""


def carrier_in(text: str) -> str:
    return next((label for word, label in _CARRIERS if word in (text or "") and not _CONTENT.search(text or "")), "")


def _orders() -> list[dict]:
    from app.services.pay_service import list_orders

    return list_orders(limit=400)


def find_orders(name: str, spoken: str, *, want: str) -> list[dict]:
    """The orders the seller means. `want`: «stage» (open paid orders; a cancel may also take an unpaid one) or «receipt»."""
    rows = _orders()
    if want == "receipt":
        pool = [row for row in rows if row.get("status") == "awaiting_receipt"]
    else:
        open_rows = [row for row in rows if str(row.get("stage") or "") not in {"delivered", "cancelled"}]
        unpaid_ok = stage_in(spoken) == "cancelled"
        pool = [row for row in open_rows if row.get("status") == "paid" or (unpaid_ok and row.get("status") in {"pending", "awaiting_receipt"})]
    if not pool:
        return []
    blob = _loose(f"{name} {spoken}")
    by_id = [row for row in pool if str(row.get("id") or "") and str(row.get("id")).lower() in blob.lower()]
    if by_id:
        return by_id[:1]
    named = [
        row
        for row in pool
        if (len(_loose(str(row.get("customer") or ""))) >= 3 and _loose(str(row.get("customer"))) in blob)
        or (len(_loose(str(row.get("title") or ""))) >= 3 and _loose(str(row.get("title"))) in blob)
    ]
    if named:
        return named
    if _LATEST.search(spoken or "") or len(pool) == 1:
        return pool[:1]  # list_orders is newest first
    return pool


def _label(row: dict) -> str:
    who = str(row.get("customer") or "").strip()
    who = f"، {who}" if who and who != "مشتری" else ""
    return f"{_quote(row.get('title') or 'سفارش')} ({fa_money(row.get('amount'))} تومان{who})"


def _which(rows: list[dict], what: str) -> str:
    if not rows:
        return f"{what} پیدا نکردم."
    return "کدام سفارش؟ " + "، ".join(_label(row) for row in rows[:5])


# ---------------------------------------------------------------- update_order


def _order_plan(args: dict, spoken: str) -> dict:
    from app.services.order_flow_service import STAGES, notify_channel, stage_problem

    text = spoken or ""
    stage = str(args.get("stage") or "").strip() or stage_in(text)
    if stage not in STAGES:
        return {"problem": "سفارش چه شود؟ آماده‌سازی، ارسال‌شده، تحویل‌شده یا لغو."}
    tracking = str(args.get("tracking") or "").strip() or (tracking_in(text) if stage == "shipped" else "")
    carrier = str(args.get("carrier") or "").strip() or (carrier_in(text) if stage == "shipped" else "")
    rows = find_orders(str(args.get("order") or ""), text, want="stage")
    if len(rows) != 1:
        return {"problem": _which(rows, "سفارش بازِ پرداخت‌شده‌ای")}
    row = rows[0]
    problem = stage_problem(row, stage, tracking)
    if problem:
        return {"problem": problem}
    return {"row": row, "stage": stage, "tracking": tracking, "carrier": carrier, "channel": notify_channel(row, stage)}


_TOLD = {
    "dm": " به مشتری در دایرکت خبر دادم.",
    "sms": " برای مشتری پیامک رفت.",
    "dm-failed": " پیام دایرکت به مشتری نرسید؛ خودت خبر بده.",
    "sms-failed": " پیامک به مشتری نرسید؛ خودت خبر بده.",
    "sms-quota": " سقف پیامک این ماه تمام است؛ خودت به مشتری خبر بده.",
    "none": " راهی برای خبر دادن به مشتری نبود؛ خودت خبر بده.",
}


def _order_card(args: dict, spoken: str) -> str:
    from app.services.order_flow_service import STAGE_FA, TELLS_SHOPPER

    plan = _order_plan(args, spoken)
    if plan.get("problem"):
        return ""
    line = f"سفارش {_label(plan['row'])} «{STAGE_FA[plan['stage']]}» شود"
    if plan["stage"] == "shipped":
        extra = [part for part in (plan["carrier"], f"کد رهگیری {fa_digits(plan['tracking'])}" if plan["tracking"] else "بدون کد رهگیری") if part]
        line += "، " + "، ".join(extra)
    line += "؟"
    if plan["stage"] in TELLS_SHOPPER:
        line += {
            "dm": "\nبه مشتری در دایرکت خبر می‌دهم.",
            "sms": "\nبرای مشتری پیامک می‌رود.",
        }.get(plan["channel"], "\nراهی برای خبر دادن به مشتری نیست؛ بعد خودت خبر بده.")
    if plan["stage"] == "cancelled" and plan["row"].get("status") == "paid":
        line += "\nبرگرداندن پول با خودت است؛ سوزان پول را برنمی‌گرداند."
    return line


def _order_check(args: dict, spoken: str) -> str:
    return str(_order_plan(args, spoken).get("problem") or "")


async def _update_order(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services import order_flow_service

    plan = _order_plan(args, spoken)
    if plan.get("problem"):
        return plan["problem"], {}
    try:
        out = await order_flow_service.advance_order(
            str(plan["row"]["id"]), plan["stage"], tracking=plan["tracking"], carrier=plan["carrier"], note="از چت"
        )
    except (KeyError, ValueError) as exc:
        return str(exc), {}
    reply = f"سفارش {_quote(plan['row'].get('title') or 'سفارش')} {order_flow_service.STAGE_FA[plan['stage']]} شد."
    if plan["stage"] in order_flow_service.TELLS_SHOPPER:
        reply += _TOLD.get(str(out.get("notified") or "none"), _TOLD["none"])
    return reply, {}


# ---------------------------------------------------------------- approve_receipt


def _receipt_plan(args: dict, spoken: str) -> dict:
    text = spoken or ""
    raw = args.get("approve")
    approve = bool(raw) if isinstance(raw, bool) else not _RECEIPT_NO.search(text)
    rows = find_orders(str(args.get("order") or ""), text, want="receipt")
    if len(rows) != 1:
        return {"problem": _which(rows, "رسیدِ منتظر تأییدی")}
    return {"row": rows[0], "approve": approve}


def _receipt_card(args: dict, spoken: str) -> str:
    plan = _receipt_plan(args, spoken)
    if plan.get("problem"):
        return ""
    if plan["approve"]:
        return f"رسید سفارش {_label(plan['row'])} تأیید شود؟\nفقط اگر پول به حسابت نشسته؛ بعد از تأیید موجودی کم و فروش ثبت می‌شود."
    return f"رسید سفارش {_label(plan['row'])} رد شود؟\nمشتری می‌تواند دوباره رسید بفرستد."


def _receipt_check(args: dict, spoken: str) -> str:
    return str(_receipt_plan(args, spoken).get("problem") or "")


async def _approve_receipt(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services import pay_service

    plan = _receipt_plan(args, spoken)
    if plan.get("problem"):
        return plan["problem"], {}
    try:
        out = pay_service.review_receipt(order_no=str(plan["row"]["id"]), approve=plan["approve"], note="از چت")
    except ValueError as exc:
        return str(exc), {}
    title = _quote(plan["row"].get("title") or "سفارش")
    if not plan["approve"]:
        return f"رسید سفارش {title} رد شد.", {}
    if out.get("needsAction"):
        return f"رسید {title} تأیید شد ولی موجودی کم بود؛ سفارش در صفحهٔ «فروش» زیر «نیازمند اقدام» است.", {}
    return f"رسید {title} تأیید شد؛ فروش ثبت و موجودی کم شد. وقتی فرستادی بگو «سفارش رو فرستادم، کد رهگیری …».", {}


# ---------------------------------------------------------------- the seller's sentence


def route(text: str) -> str:
    """Only plain sentences; the caller has already sent questions to the read tools."""
    if _RECEIPT_OK.search(text) or _RECEIPT_NO.search(text):
        return "approve_receipt"
    if _CONTENT.search(text):
        return ""
    stage = stage_in(text)
    if not stage:
        return ""
    if "سفارش" in text or (stage == "shipped" and tracking_in(text)) or any(_named(row, text) for row in _orders()):
        return "update_order"
    return ""


def _named(row: dict, text: str) -> bool:
    blob = _loose(text)
    who = _loose(str(row.get("customer") or ""))
    return len(who) >= 3 and who in blob


def _schema(name: str, description: str, properties: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties}}}


register(
    Tool(
        name="update_order",
        schema=_schema(
            "update_order",
            "وضعیت یک سفارش پرداخت‌شده: آماده‌سازی، ارسال‌شده با کد رهگیری، تحویل‌شده یا لغو. order نام مشتری یا کالای سفارش است.",
            {
                "order": {"type": "string"},
                "stage": {"type": "string", "enum": ["preparing", "shipped", "delivered", "cancelled"]},
                "tracking": {"type": "string"},
                "carrier": {"type": "string"},
            },
        ),
        level="write",
        rank=0,
        groups=("sales",),
        run=_update_order,
        summary=_order_card,
        check=_order_check,
    )
)
register(
    Tool(
        name="approve_receipt",
        schema=_schema(
            "approve_receipt",
            "تأیید یا رد رسید کارت‌به‌کارت یک سفارش. order نام مشتری یا کالای سفارش است.",
            {"order": {"type": "string"}, "approve": {"type": "boolean"}},
        ),
        level="write",
        rank=0,
        groups=("sales",),
        run=_approve_receipt,
        summary=_receipt_card,
        check=_receipt_check,
    )
)
