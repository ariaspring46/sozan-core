from __future__ import annotations

import re
from datetime import datetime, timezone
from time import time
from uuid import uuid4

from app.config import settings as env
from app.services import payment_service, plan_service
from app.state_store import read_json, shared_lock, write_json

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_COUPON_ALIASES = {
    "سوزانسی": "sozan30",
    "سوزان30": "sozan30",
}


def _pending() -> dict:
    stored = read_json("billing-pending.json", {}, shared=True)
    return stored if isinstance(stored, dict) else {}


def _save_pending(rows: dict) -> None:
    write_json("billing-pending.json", rows, shared=True)


def _put_pending(authority: str, row: dict) -> None:
    with shared_lock():
        pending = _pending()
        pending[authority] = row
        _save_pending(pending)


def _drop_pending(key: str) -> None:
    with shared_lock():
        pending = _pending()
        pending.pop(key, None)
        _save_pending(pending)


def _history() -> list[dict]:
    rows = read_json("billing.json", [])
    return rows if isinstance(rows, list) else []


def normalize_coupon(value: str) -> str:
    blob = (value or "").translate(_DIGITS)
    blob = blob.replace("\u200c", "").replace("-", "").replace("_", "")
    blob = re.sub(r"\s+", "", blob)
    blob = blob.casefold()
    blob = blob.replace("ي", "ی").replace("ك", "ک")
    return _COUPON_ALIASES.get(blob, blob)


def coupon_already_used() -> bool:
    for item in _history():
        if item.get("coupon") and item.get("status") == "paid":
            return True
    return False


def _coupon_expiry() -> datetime | None:
    raw = str(env.phone_coupon_until or "").strip()
    if raw:
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("این کد تخفیف معتبر نیست") from exc
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment
    return plan_service.discount_until()


def apply_phone_coupon(plan_id: str, amount: int, code: str | None) -> tuple[int, str | None, int]:
    full = int(amount)
    raw = (code or "").strip()
    if not raw:
        return full, None, full
    if str(plan_id or "").strip().lower() not in {"pro", "promax", "ultra"}:
        raise ValueError("این کد تخفیف معتبر نیست")
    wanted = normalize_coupon(raw)
    configured = normalize_coupon(str(env.phone_coupon_code or ""))
    if not configured or wanted != configured:
        raise ValueError("این کد تخفیف معتبر نیست")
    expiry = _coupon_expiry()
    if expiry is not None and datetime.now(timezone.utc) >= expiry:
        raise ValueError("این کد تخفیف معتبر نیست")
    if coupon_already_used():
        raise ValueError("این کد تخفیف معتبر نیست")
    percent = int(env.phone_coupon_percent or 0)
    if percent <= 0 or percent >= 100:
        raise ValueError("این کد تخفیف معتبر نیست")
    discounted = full * (100 - percent) // 100
    if discounted < 1:
        raise ValueError("این کد تخفیف معتبر نیست")
    return discounted, str(env.phone_coupon_code or raw).strip(), full


def preview_coupon(plan_id: str, code: str) -> dict:
    wanted = str(plan_id or "").strip().lower()
    if wanted not in plan_service.PLANS:
        raise ValueError("این اشتراک وجود ندارد")
    base = plan_service.effective_price(wanted)
    amount, coupon, _listed = apply_phone_coupon(wanted, base, code)
    return {"plan": wanted, "amount": amount, "code": coupon or ""}


def callback_url() -> str:
    base = str(env.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{base}/billing/zarinpal/callback"


def panel_return(status: str) -> str:
    base = str(env.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/more/settings?pay={status}"


async def start_subscription(plan_id: str, *, phone: str, code: str | None = None) -> dict:
    wanted = str(plan_id or "").strip().lower()
    spec = plan_service.PLANS.get(wanted)
    if spec is None:
        raise ValueError("این اشتراک وجود ندارد")
    if wanted == "ultra":
        raise ValueError("خرید اولترا به‌زودی باز می‌شود")
    if wanted == plan_service.current_plan_id():
        return {"activated": True, "plan": wanted, "subscription": plan_service.snapshot()}
    amount = plan_service.effective_price(wanted)
    final, coupon, _listed = apply_phone_coupon(wanted, amount, code)
    amount = final
    if amount <= 0:
        plan_service.set_plan(wanted)
        return {"activated": True, "plan": wanted, "subscription": plan_service.snapshot()}
    from app.services import wallet_service

    try:
        available = int(wallet_service.get().get("available") or 0)
    except (TypeError, ValueError):
        available = 0
    if available >= amount:
        wallet_service.debit("plan", amount, note=f"اشتراک {spec['label']}")
        plan_service.set_plan(wanted)
        history = _history()
        history.append(
            {
                "id": str(uuid4()),
                "phone": phone,
                "plan": wanted,
                "amount": amount,
                "status": "paid",
                "source": "wallet",
                "coupon": coupon or "",
                "at": int(time()),
            }
        )
        write_json("billing.json", history[-80:])
        return {
            "activated": True,
            "fromWallet": True,
            "plan": wanted,
            "amount": amount,
            "subscription": plan_service.snapshot(),
        }
    if not payment_service.merchant_id():
        raise ValueError("درگاه زرین‌پال هاب هنوز تنظیم نشده.")
    paid = await payment_service.zarinpal_request(
        amount_toman=amount,
        description=f"اشتراک {spec['label']} سوزان",
        callback_url=callback_url(),
        mobile=phone,
    )
    authority = str(paid.get("authority") or "").strip()
    row = {
        "id": str(uuid4()),
        "phone": phone,
        "plan": wanted,
        "amount": amount,
        "authority": authority,
        "status": "pending",
        "coupon": coupon or "",
        "at": int(time()),
    }
    _put_pending(authority, row)
    history = _history()
    history.append(row)
    write_json("billing.json", history[-80:])
    return {
        "activated": False,
        "plan": wanted,
        "amount": amount,
        "authority": authority,
        "startPayUrl": paid["startPayUrl"],
    }


def peek_pending(authority: str) -> dict | None:
    row = _pending().get(str(authority or "").strip())
    return dict(row) if isinstance(row, dict) else None


async def finish_subscription(*, authority: str, ok: bool) -> str:
    key = str(authority or "").strip()
    pending = _pending()
    row = pending.get(key)
    if not isinstance(row, dict):
        return panel_return("ok" if ok else "missing")
    phone = str(row.get("phone") or "").strip()
    if not phone:
        _drop_pending(key)
        return panel_return("fail")
    from app.state_store import tenant_scope

    with tenant_scope(phone):
        history = _history()
        if not ok:
            _drop_pending(key)
            for item in history:
                if item.get("authority") == key:
                    item["status"] = "failed"
            write_json("billing.json", history[-80:])
            return panel_return("cancel")
        try:
            verified = await payment_service.zarinpal_verify(
                amount_toman=int(row.get("amount") or 0),
                authority=key,
            )
        except ValueError:
            return panel_return("fail")
        _drop_pending(key)
        plan_service.set_plan(str(row.get("plan") or "free"))
        for item in history:
            if item.get("authority") == key:
                item["status"] = "paid"
                item["refId"] = verified.get("refId") or ""
        write_json("billing.json", history[-80:])
    return panel_return("ok")
