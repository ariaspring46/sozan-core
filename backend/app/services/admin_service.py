"""Prekhozan modiriat: users, payments, plan management. Admin_phone only.

Every action lands in admin-actions.json and in an observe event (phone masked
in the event, full in the admin UI — the owner is the data controller).
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from app.config import settings
from app.state_store import read_json, tenant_scope, write_json

AUDIT_FILE = "admin-actions.json"


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(str(phone or "").encode()).hexdigest()[:12]


def _audit_rows() -> list[dict]:
    rows = read_json(AUDIT_FILE, [], shared=True)
    return rows if isinstance(rows, list) else []


def _save_audit(rows: list[dict]) -> None:
    write_json(AUDIT_FILE, rows[-500:], shared=True)


def record_action(*, action: str, target: str, reason: str = "") -> None:
    row = {
        "at": int(time.time()),
        "action": str(action or "")[:40],
        "target": str(target or "")[:20],
        "reason": str(reason or "")[:300],
    }
    rows = _audit_rows()
    rows.append(row)
    _save_audit(rows)
    from app.services.observe_client import emit_later

    emit_later(
        kind="admin",
        title="admin-action",
        surface="admin",
        status="ok",
        payload={"action": row["action"], "target": _hash_phone(row["target"])},
    )


def audit_trail() -> list[dict]:
    return sorted(_audit_rows(), key=lambda r: -int(r.get("at") or 0))


def _tenant_dirs() -> list[Path]:
    root = settings.state_path / "tenants"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name and p.name != "_none")


def _sms_used(tenant: str) -> int:
    try:
        with tenant_scope(tenant):
            from app.services import storefront_service

            data = storefront_service.list_sales()
            return 0  # placeholder; sms quota from wallet if present
    except Exception:
        return 0


def _ai_spend(tenant: str) -> dict:
    from app.services import ai_budget_service

    try:
        st = ai_budget_service.tenant_status(tenant)
        return {"today": st.get("dailyUsedUsd", 0), "week": st.get("weeklyUsedUsd", 0)}
    except Exception:
        return {"today": 0, "week": 0}


def _user_row(tenant: str, user=None) -> dict:
    from app.services import plan_service
    from app.state_store import current_tenant, reset_tenant, set_tenant

    token = set_tenant(tenant)
    try:
        plan_raw = read_json("plan.json", {})
        shop = read_json("shop.json", {})
        channels = read_json("channels.json", [])
        inbox = read_json("inbox.json", {})
        billing = read_json("billing.json", [])
    finally:
        reset_tenant(token)

    plan = str(plan_raw.get("plan") or "free") if isinstance(plan_raw, dict) else "free"
    paid_until = int(plan_raw.get("paidUntil") or 0) if isinstance(plan_raw, dict) else 0
    days_left = max(0, (paid_until - int(time.time())) // 86400) if paid_until else 0
    expired = paid_until and time.time() >= paid_until
    blocked = bool(user and not user.is_active) if user else False

    sites_count = 1 if str(shop.get("slug") or "") else 0
    channels_count = len(channels) if isinstance(channels, list) else 0
    threads = inbox.get("threads") if isinstance(inbox, dict) else []
    last_activity = 0
    if isinstance(threads, list) and threads:
        last_activity = max(int(t.get("lastAt") or 0) for t in threads if isinstance(t, dict))

    ai = _ai_spend(tenant)

    return {
        "phone": tenant,
        "plan": "free" if expired else plan,
        "paidUntil": paid_until,
        "daysLeft": days_left,
        "status": "blocked" if blocked else ("expired" if expired else "active"),
        "sites": sites_count,
        "channels": channels_count,
        "aiToday": round(ai["today"], 4),
        "aiWeek": round(ai["week"], 4),
        "lastActivity": last_activity,
        "joinedAt": int(billing[0].get("at") or 0) if isinstance(billing, list) and billing else 0,
    }


async def list_users(session) -> list[dict]:
    from app.repositories.user_repository import UserRepository

    repo = UserRepository(session)
    users = await repo.list_all()
    user_map = {u.phone: u for u in users}
    rows = []
    for p in _tenant_dirs():
        if p.name not in user_map:
            continue
        rows.append(_user_row(p.name, user_map[p.name]))
    return rows


async def user_detail(session, phone: str) -> dict:
    from app.repositories.user_repository import UserRepository

    repo = UserRepository(session)
    user = await repo.get_by_phone(phone)
    if user is None:
        return {}
    base = _user_row(phone, user)
    with tenant_scope(phone):
        billing = read_json("billing.json", [])
        orders = read_json("pay-orders.json", [])
        tickets = read_json("support-tickets.json", [])
        shop = read_json("shop.json", {})
    base["billing"] = [
        {k: r.get(k) for k in ("plan", "amount", "status", "at", "refId", "coupon")}
        for r in (billing if isinstance(billing, list) else [])
    ]
    base["orders"] = [
        {k: r.get(k) for k in ("id", "amount", "status", "at")}
        for r in (orders if isinstance(orders, list) else [])[:20]
    ]
    base["tickets"] = [
        {k: r.get(k) for k in ("id", "subject", "status", "at")}
        for r in (tickets if isinstance(tickets, list) else [])[:20]
    ]
    base["site"] = {
        "slug": str(shop.get("slug") or ""),
        "status": str(shop.get("status") or ""),
        "publicHost": str(shop.get("publicHost") or ""),
    }
    base["blocked"] = not user.is_active
    return base


def set_user_plan(phone: str, plan: str, *, days: int, reason: str) -> dict:
    from app.services import plan_service

    if not str(reason or "").strip():
        raise ValueError("دلیل تغییر پلن اجباری است")
    with tenant_scope(phone):
        paid_until = int(time.time()) + max(0, int(days)) * 86400 if plan != "free" else 0
        plan_service.set_plan(plan, paid_until=paid_until or None)
    record_action(action="set-plan", target=phone, reason=f"{plan}/{days}d: {reason}")
    return {"ok": True, "plan": plan, "paidUntil": paid_until}


async def set_user_blocked(session, phone: str, blocked: bool, *, reason: str) -> dict:
    from app.repositories.user_repository import UserRepository

    if not str(reason or "").strip():
        raise ValueError("دلیل اجباری است")
    repo = UserRepository(session)
    await repo.set_active(phone, active=not blocked)
    record_action(action="block" if blocked else "unblock", target=phone, reason=reason)
    return {"ok": True, "blocked": blocked}


def global_payments() -> dict:
    """All billing rows across tenants, with today/week/month totals."""
    from collections import defaultdict

    now = time.time()
    today_start = now - (now % 86400)
    week_start = now - 7 * 86400
    month_start = now - 30 * 86400
    rows: list[dict] = []
    totals = {"today": 0, "week": 0, "month": 0, "all": 0}
    by_plan: dict[str, int] = defaultdict(int)
    for p in _tenant_dirs():
        with tenant_scope(p.name):
            billing = read_json("billing.json", [])
        for r in billing if isinstance(billing, list) else []:
            if str(r.get("status")) != "paid":
                continue
            at = int(r.get("at") or 0)
            amount = int(r.get("amount") or 0)
            plan = str(r.get("plan") or "")
            rows.append({"phone": p.name, "plan": plan, "amount": amount, "at": at, "refId": str(r.get("refId") or "")})
            totals["all"] += amount
            by_plan[plan] += amount
            if at >= today_start:
                totals["today"] += amount
            if at >= week_start:
                totals["week"] += amount
            if at >= month_start:
                totals["month"] += amount
    rows.sort(key=lambda r: -r["at"])
    return {"rows": rows[:200], "totals": totals, "byPlan": dict(by_plan)}
