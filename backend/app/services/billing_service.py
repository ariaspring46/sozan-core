from __future__ import annotations

from time import time
from uuid import uuid4

from app.config import settings as env
from app.services import payment_service, plan_service
from app.state_store import read_json, write_json


def _pending() -> dict:
    stored = read_json("billing-pending.json", {}, shared=True)
    return stored if isinstance(stored, dict) else {}


def _save_pending(rows: dict) -> None:
    write_json("billing-pending.json", rows, shared=True)


def _history() -> list[dict]:
    rows = read_json("billing.json", [])
    return rows if isinstance(rows, list) else []


def callback_url() -> str:
    base = str(env.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{base}/billing/zarinpal/callback"


def panel_return(status: str) -> str:
    base = str(env.panel_url or "https://app.sozan-core.ir").rstrip("/")
    return f"{base}/more/settings?pay={status}"


async def start_subscription(plan_id: str, *, phone: str) -> dict:
    wanted = str(plan_id or "").strip().lower()
    spec = plan_service.PLANS.get(wanted)
    if spec is None:
        raise ValueError("این اشتراک وجود ندارد")
    if wanted == plan_service.current_plan_id():
        return {"activated": True, "plan": wanted, "subscription": plan_service.snapshot()}
    amount = int(spec.get("priceToman") or 0)
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
        "at": int(time()),
    }
    pending = _pending()
    pending[authority] = row
    _save_pending(pending)
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
        pending.pop(key, None)
        _save_pending(pending)
        return panel_return("fail")
    from app.state_store import tenant_scope

    with tenant_scope(phone):
        history = _history()
        if not ok:
            pending.pop(key, None)
            _save_pending(pending)
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
        pending.pop(key, None)
        _save_pending(pending)
        plan_service.set_plan(str(row.get("plan") or "free"))
        for item in history:
            if item.get("authority") == key:
                item["status"] = "paid"
                item["refId"] = verified.get("refId") or ""
        write_json("billing.json", history[-80:])
    return panel_return("ok")
