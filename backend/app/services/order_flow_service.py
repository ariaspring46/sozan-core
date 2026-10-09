"""What happens to an order after payment: preparing → shipped (tracking code) → delivered, or cancelled.

`status` stays the payment state (pending, paid, …) and `stage` is the seller's work on it, so nothing that reads
payments changes. Every step lands in the order's timeline (pay_service.log_event). The shopper hears about a
shipment or a cancellation through the conversation the order came from (DM), else by SMS when an approved
template is configured (MELIPAYAMAK_ORDER_BODY_ID), and can always see the stage on the public order page.
Refunds stay with the seller: Sozan never moves money back.
"""

from __future__ import annotations

import logging
import re
from time import time

from app.config import settings
from app.services import pay_service
from app.services.tenant_lock import tenant_file_lock
from app.state_store import tenant_scope

log = logging.getLogger("sozan.orders")

STAGES = ("preparing", "shipped", "delivered", "cancelled")
STAGE_FA = {
    "": "منتظر ارسال",
    "preparing": "در حال آماده‌سازی",
    "shipped": "ارسال‌شده",
    "delivered": "تحویل‌شده",
    "cancelled": "لغوشده",
}
TELLS_SHOPPER = frozenset({"shipped", "cancelled"})
ADDRESS_MIN, ADDRESS_MAX = 10, 400
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def stage_problem(row: dict, stage: str, tracking: str = "") -> str:
    """Why this order cannot move to `stage`; empty when it can."""
    current = str(row.get("stage") or "")
    paid = str(row.get("status") or "") == "paid"
    if stage not in STAGES:
        return "این وضعیت سفارش را نمی‌شناسم."
    if current in {"cancelled", "delivered"}:
        return f"این سفارش {STAGE_FA[current]} است."
    if stage == "cancelled":
        if current == "shipped":
            return "سفارش ارسال‌شده لغو نمی‌شود؛ اگر برگشت خورد با مشتری هماهنگ کن."
        return ""
    if not paid:
        return "این سفارش هنوز پرداخت نشده است."
    if stage == current and not (stage == "shipped" and tracking and tracking != str(row.get("tracking") or "")):
        return f"این سفارش همین الان {STAGE_FA[stage]} است."
    if stage == "preparing" and current == "shipped":
        return "این سفارش ارسال شده است."
    return ""


def notify_channel(row: dict, stage: str) -> str:
    """How the shopper will hear about `stage`: dm, sms, or nothing."""
    if stage not in TELLS_SHOPPER:
        return ""
    if str(row.get("threadId") or "").strip():
        return "dm"
    if str(row.get("customerMobile") or "").strip() and stage == "shipped" and str(settings.melipayamak_order_body_id or "").strip():
        return "sms"
    return ""


def _shop_name() -> str:
    from app.services.shop_service import current_shop

    shop = current_shop()
    return str((shop or {}).get("brand") or "فروشگاه").strip() or "فروشگاه"


def shopper_text(row: dict, stage: str) -> str:
    title = str(row.get("title") or "سفارش")
    shop = _shop_name()
    if stage == "shipped":
        tracking = str(row.get("tracking") or "").strip()
        carrier = str(row.get("carrier") or "").strip()
        line = f"سفارش «{title}» از {shop} ارسال شد"
        if carrier:
            line += f" با {carrier}"
        line += "."
        if tracking:
            line += f" کد رهگیری: {tracking}"
        return line + f"\nپیگیری: {pay_service.panel_pay_url(str(row.get('id') or ''))}"
    if stage == "cancelled":
        if str(row.get("status") or "") != "paid":
            return f"سفارش «{title}» از {shop} لغو شد."
        return f"سفارش «{title}» از {shop} لغو شد. فروشنده برای برگشت پول با شما هماهنگ می‌کند."
    return ""


async def _tell_shopper(row: dict, stage: str) -> str:
    """dm, sms, none, or the channel plus «-failed». Never raises: the stage is already saved."""
    channel = notify_channel(row, stage)
    if not channel:
        return "none"
    text = shopper_text(row, stage)
    if channel == "dm":
        from app.services import inbox_service

        try:
            await inbox_service.reply(str(row.get("threadId")), text, deliver=True)
        except Exception as exc:
            log.warning("order dm failed order=%s err=%s", row.get("id"), type(exc).__name__)
            return "dm-failed"
        return "dm"
    from app.services import melipayamak_otp_service, wallet_service

    try:
        charged = int(wallet_service.consume_sms().get("charged") or 0)
    except ValueError:
        return "sms-quota"
    values = [
        str(row.get("title") or "سفارش"),
        _shop_name(),
        str(row.get("tracking") or "-"),
        pay_service.panel_pay_url(str(row.get("id") or "")),
    ]
    try:
        await melipayamak_otp_service.send_pattern(
            str(row.get("customerMobile")),
            ";".join(value.replace(";", ",")[:60] for value in values),
            body_id=str(settings.melipayamak_order_body_id).strip(),
            surface="orders",
        )
    except Exception as exc:
        wallet_service.refund_sms(charged)
        log.warning("order sms failed order=%s err=%s", row.get("id"), type(exc).__name__)
        return "sms-failed"
    return "sms"


def _find(orders: list[dict], order_id: str) -> dict | None:
    wanted = str(order_id or "").strip()
    return next((row for row in orders if str(row.get("id")) == wanted), None)


async def advance_order(order_id: str, stage: str, *, tracking: str = "", carrier: str = "", note: str = "") -> dict:
    """Move one order of the current tenant; returns the seller view plus how the shopper was told (`notified`)."""
    tracking = re.sub(r"\s+", "", str(tracking or "")).translate(_ASCII)[:40]
    carrier = str(carrier or "").strip()[:40]
    with tenant_file_lock("pay-orders"):
        orders = pay_service._orders()
        row = _find(orders, order_id)
        if row is None:
            raise KeyError("سفارش پیدا نشد")
        problem = stage_problem(row, stage, tracking)
        if problem:
            raise ValueError(problem)
        row["stage"] = stage
        if tracking:
            row["tracking"] = tracking
        if carrier:
            row["carrier"] = carrier
        row["stageAt"] = int(time())
        pay_service.log_event(row, stage, " ".join(part for part in (carrier, tracking, str(note or "").strip()) if part))
        pay_service._save_orders(orders)
        snapshot = dict(row)
    notified = await _tell_shopper(snapshot, stage) if stage in TELLS_SHOPPER else "none"
    with tenant_file_lock("pay-orders"):
        orders = pay_service._orders()
        row = _find(orders, order_id) or snapshot
        if stage in TELLS_SHOPPER:
            pay_service.log_event(row, "notified", notified)
            pay_service._save_orders(orders)
        out = pay_service.seller_order(row)
    out["notified"] = notified
    return out


def set_address(order_id: str, address: str) -> dict:
    """The shopper writes the shipping address on their order page. It can change until the order ships."""
    text = re.sub(r"\s+", " ", str(address or "")).strip()
    if len(text) < ADDRESS_MIN:
        raise ValueError("آدرس کامل را بنویس: شهر، خیابان، پلاک و کد پستی.")
    text = text[:ADDRESS_MAX]
    found = pay_service.locate_order(order_id)
    if found is None:
        raise KeyError("سفارش پیدا نشد")
    phone, _row = found
    with tenant_scope(phone), tenant_file_lock("pay-orders"):
        orders = pay_service._orders()
        row = _find(orders, order_id)
        if row is None:
            raise KeyError("سفارش پیدا نشد")
        if str(row.get("status") or "") in {"failed", "receipt_rejected"}:
            raise ValueError("این سفارش پرداخت نشده است.")
        if str(row.get("stage") or "") in {"shipped", "delivered", "cancelled"}:
            raise ValueError("سفارش ارسال شده؛ آدرس دیگر عوض نمی‌شود. با فروشنده تماس بگیر.")
        changed = bool(str(row.get("address") or "").strip())
        row["address"] = text
        pay_service.log_event(row, "address", "عوض شد" if changed else "ثبت شد")
        pay_service._save_orders(orders)
        return pay_service.public_order(row)


def stage_line(row: dict) -> str:
    """«منتظر ارسال» / «ارسال‌شده، رهگیری ۱۲۳» for chat and lists; payment states for unpaid orders."""
    if str(row.get("status") or "") != "paid":
        return ""
    stage = str(row.get("stage") or "")
    label = STAGE_FA.get(stage, stage)
    tracking = str(row.get("tracking") or "")
    return f"{label}، رهگیری {tracking.translate(_FA)}" if stage == "shipped" and tracking else label
