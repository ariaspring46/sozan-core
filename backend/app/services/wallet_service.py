from __future__ import annotations

import re
from datetime import UTC, datetime
from time import time
from uuid import uuid4

from app.config import settings as env
from app.services import plan_service
from app.services.tenant_lock import tenant_file_lock
from app.state_store import current_tenant, iter_tenants, read_json, tenant_scope, write_json

EMPTY = {
    "available": 0,
    "pendingWithdraw": 0,
    "lifetimeSales": 0,
    "lifetimeCommission": 0,
}

SHEBA = re.compile(r"^IR\d{24}$")


def get() -> dict:
    stored = read_json("wallet.json", {})
    if not isinstance(stored, dict):
        stored = {}
    out = dict(EMPTY)
    for key in EMPTY:
        try:
            out[key] = int(stored.get(key) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    return out


def _save(row: dict) -> dict:
    write_json("wallet.json", row)
    return row


def ledger(limit: int = 40) -> list[dict]:
    rows = read_json("wallet-ledger.json", [])
    if not isinstance(rows, list):
        return []
    return list(reversed(rows[-max(1, limit) :]))


def _append(kind: str, amount: int, *, order_id: str = "", note: str = "") -> dict:
    row = {
        "id": str(uuid4()),
        "at": int(time()),
        "kind": kind,
        "amount": int(amount),
        "orderId": order_id,
        "note": note,
    }
    rows = read_json("wallet-ledger.json", [])
    if not isinstance(rows, list):
        rows = []
    rows.append(row)
    write_json("wallet-ledger.json", rows[-400:])
    return row


def _sale_credited(order_id: str) -> bool:
    token = str(order_id or "").strip()
    if not token:
        return False
    rows = read_json("wallet-ledger.json", [])
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("orderId") or "") != token:
            continue
        if str(row.get("kind") or "") in {"sale_sozan", "sale_external"}:
            return True
    return False


def credit_sale(*, amount: int, commission: int, order_id: str, note: str, owner: str) -> dict:
    amount = int(amount)
    commission = max(0, int(commission))
    with tenant_file_lock("wallet"):
        if _sale_credited(order_id):
            return dict(get())
        wallet = get()
        wallet["lifetimeSales"] = int(wallet["lifetimeSales"]) + amount
        if owner == "hub":
            net = amount - commission
            wallet["available"] = int(wallet["available"]) + net
            wallet["lifetimeCommission"] = int(wallet["lifetimeCommission"]) + commission
            _append("sale_sozan", net, order_id=order_id, note=note)
            if commission:
                _append("commission", -commission, order_id=order_id, note="کمیسیون سوزان")
        else:
            _append("sale_external", amount, order_id=order_id, note=note or "تسویه روی درگاه شخصی")
        _save(wallet)
        return dict(wallet)


def debit(kind: str, amount: int, *, note: str = "", order_id: str = "") -> dict:
    amount = int(amount)
    if amount <= 0:
        raise ValueError("مبلغ نامعتبر است")
    with tenant_file_lock("wallet"):
        wallet = get()
        if int(wallet["available"]) < amount:
            raise ValueError("موجودی کیف پول کافی نیست")
        wallet["available"] = int(wallet["available"]) - amount
        _save(wallet)
        _append(kind, -amount, order_id=order_id, note=note)
        return dict(wallet)


def sms_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def sms_usage() -> dict:
    stored = read_json("sms-usage.json", {})
    if not isinstance(stored, dict):
        stored = {}
    month = sms_month()
    if str(stored.get("ym") or "") != month:
        return {"ym": month, "count": 0}
    try:
        count = int(stored.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    return {"ym": month, "count": max(0, count)}


def sms_quota() -> int:
    return int(plan_service.current().get("smsQuota") or 0)


def consume_sms() -> dict:
    overage = max(0, int(env.sms_overage_toman or 200))
    quota = sms_quota()
    with tenant_file_lock("wallet"):
        usage = sms_usage()
        count = int(usage["count"])
        charged = 0
        if count >= quota:
            if overage <= 0:
                raise ValueError("سقف پیامک این ماه تمام شد")
            wallet = get()
            if int(wallet["available"]) < overage:
                raise ValueError("سقف پیامک این ماه تمام شد")
            wallet["available"] = int(wallet["available"]) - overage
            _save(wallet)
            _append("sms", -overage, note="پیامک اضافه")
            charged = overage
        usage["count"] = count + 1
        usage["ym"] = sms_month()
        write_json("sms-usage.json", usage)
        return {"count": usage["count"], "quota": quota, "charged": charged}


def request_withdraw(*, amount: int, iban: str, name: str = "") -> dict:
    amount = int(amount)
    if amount <= 0:
        raise ValueError("مبلغ برداشت نامعتبر است")
    sheba = iban.strip().upper().replace(" ", "")
    if not SHEBA.match(sheba):
        raise ValueError("شبا باید با IR و ۲۴ رقم باشد")
    with tenant_file_lock("wallet"):
        wallet = get()
        if int(wallet["available"]) < amount:
            raise ValueError("موجودی قابل‌برداشت کافی نیست")
        wallet["available"] = int(wallet["available"]) - amount
        wallet["pendingWithdraw"] = int(wallet["pendingWithdraw"]) + amount
        _save(wallet)
        row = {
            "id": str(uuid4()),
            "at": int(time()),
            "amount": amount,
            "iban": sheba,
            "name": name.strip()[:80],
            "status": "pending",
            "phone": current_tenant(),
        }
        rows = read_json("withdrawals.json", [])
        if not isinstance(rows, list):
            rows = []
        rows.append(row)
        write_json("withdrawals.json", rows[-80:])
        _append("withdraw_hold", -amount, order_id=row["id"], note=sheba)
        return {"withdraw": row, "wallet": snapshot()}


def list_withdrawals() -> list[dict]:
    rows = read_json("withdrawals.json", [])
    return rows if isinstance(rows, list) else []


def decide_withdraw(withdraw_id: str, *, ok: bool, phone: str) -> dict:
    with tenant_scope(phone):
        with tenant_file_lock("wallet"):
            rows = list_withdrawals()
            found = next((row for row in rows if str(row.get("id")) == withdraw_id), None)
            if found is None:
                raise KeyError("درخواست پیدا نشد")
            if str(found.get("status") or "") != "pending":
                raise ValueError("این درخواست قبلاً رسیدگی شده")
            amount = int(found.get("amount") or 0)
            wallet = get()
            if ok:
                found["status"] = "paid"
                wallet["pendingWithdraw"] = max(0, int(wallet["pendingWithdraw"]) - amount)
                _append("withdraw_paid", 0, order_id=withdraw_id, note=str(found.get("iban") or ""))
            else:
                found["status"] = "rejected"
                wallet["pendingWithdraw"] = max(0, int(wallet["pendingWithdraw"]) - amount)
                wallet["available"] = int(wallet["available"]) + amount
                _append("withdraw_reject", amount, order_id=withdraw_id, note="برگشت به کیف")
            found["decidedAt"] = int(time())
            _save(wallet)
            write_json("withdrawals.json", rows)
            return {"withdraw": found, "wallet": snapshot()}


def admin_withdrawals() -> list[dict]:
    out = []
    for phone in iter_tenants():
        with tenant_scope(phone):
            for row in list_withdrawals():
                if str(row.get("status") or "") == "pending":
                    out.append({**row, "phone": phone})
    out.sort(key=lambda item: int(item.get("at") or 0))
    return out


def snapshot() -> dict:
    wallet = get()
    usage = sms_usage()
    quota = sms_quota()
    return {
        **wallet,
        "smsUsed": usage["count"],
        "smsQuota": quota,
        "smsOverageToman": max(0, int(env.sms_overage_toman or 200)),
        "commissionBps": int(env.commission_bps or 200),
        "ledger": ledger(),
        "withdrawals": list(reversed(list_withdrawals()[-20:])),
    }
