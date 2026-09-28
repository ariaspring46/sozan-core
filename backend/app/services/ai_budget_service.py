"""Cloud-cost caps per tenant plan: counting, thresholds and the block decision.

Costs arrive from OpenRouter-style ``usage.cost`` on every cloud reply. The
ledger is one shared JSON file per day so a restart never loses spend, and the
cap table lives in ``ai-budget.json`` so numbers change without a deploy.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from app.services import plan_service
from app.state_store import current_tenant, read_json, shared_lock, tenant_scope, write_json

# The marketing phone is Sozan's own cost. It never eats a tenant cap and the
# company cap never silences a live call.
VOICE_BUCKETS = {"voice", "phone"}
SOZAN_BUCKET = "#sozan-voice"

# Tehran is UTC+03:30 with no DST; caps roll over on the seller's day.
_TZ_OFFSET_SEC = 12600
_KEEP_DAYS = 8

DEFAULTS: dict[str, Any] = {
    # Proposal numbers; the owner approves or edits ai-budget.json in place.
    "company": {"dailyUsd": 3.0},
    # Owner-approved 2026-09-28: monthly cloud spend = 30% of the discounted
    # plan price; weekly = /4, daily = weekly/3, at ~230,000 toman per USD.
    "plans": {
        "free": {"dailyUsd": 0.002, "weeklyUsd": 0.006},
        "pro": {"dailyUsd": 0.15, "weeklyUsd": 0.46},
        "promax": {"dailyUsd": 0.21, "weeklyUsd": 0.63},
        "ultra": {"dailyUsd": 0.29, "weeklyUsd": 0.88},
    },
    "notifyRatio": 0.8,
}


def _day_key(when: float | None = None) -> str:
    import datetime as _dt

    moment = time.time() if when is None else when
    return _dt.datetime.fromtimestamp(moment + _TZ_OFFSET_SEC, tz=_dt.timezone.utc).strftime("%Y-%m-%d")


def _config() -> dict[str, Any]:
    stored = read_json("ai-budget.json", {}, shared=True)
    if not isinstance(stored, dict) or not stored:
        return DEFAULTS
    plans = {key: dict(value) for key, value in DEFAULTS["plans"].items()}
    for key, value in (stored.get("plans") or {}).items():
        plans[key] = {**plans.get(key, {}), **value}
    return {
        "company": {**DEFAULTS["company"], **(stored.get("company") or {})},
        "plans": plans,
        "notifyRatio": stored.get("notifyRatio", DEFAULTS["notifyRatio"]),
    }


def _ledger() -> dict[str, dict[str, float]]:
    stored = read_json("ai-spend.json", {}, shared=True)
    days = stored.get("days") if isinstance(stored, dict) else None
    if not isinstance(days, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for day, tenants in days.items():
        if isinstance(tenants, dict):
            out[str(day)] = {str(k): float(v or 0) for k, v in tenants.items() if isinstance(v, (int, float))}
    return out


def _save_ledger(days: dict[str, dict[str, float]]) -> None:
    keep = sorted(days)[-_KEEP_DAYS:]
    write_json("ai-spend.json", {"days": {day: days[day] for day in keep}}, shared=True)


def _tenant_bucket(surface: str) -> str:
    if str(surface or "").strip().lower() in VOICE_BUCKETS:
        return SOZAN_BUCKET
    tenant = str(current_tenant() or "").strip()
    return tenant or "#anonymous"


def record_cost(*, surface: str, usd: float, tenant: str | None = None) -> None:
    """Add one cloud reply's cost to the day ledger. Never raises."""
    try:
        value = float(usd)
    except (TypeError, ValueError):
        return
    if value <= 0:
        return
    bucket = str(tenant or "").strip() or _tenant_bucket(surface)
    day = _day_key()
    with shared_lock():
        days = _ledger()
        day_row = days.setdefault(day, {})
        day_row[bucket] = round(float(day_row.get(bucket, 0.0)) + value, 6)
        _save_ledger(days)


def _window(days: dict[str, dict[str, float]], *, span: int, buckets: list[str]) -> float:
    keys = sorted(days)[-span:]
    return round(sum(float(days[k].get(b, 0.0)) for k in keys for b in buckets), 6)


def _company_window(days: dict[str, dict[str, float]], *, span: int) -> float:
    keys = sorted(days)[-span:]
    return round(sum(float(v) for k in keys for v in days[k].values()), 6)


def _plan_of(tenant: str) -> str:
    if tenant in {SOZAN_BUCKET, "#anonymous"}:
        return "free"
    if tenant == str(current_tenant() or ""):
        plan = str(plan_service.current_plan_id() or "free").strip().lower()
    else:
        try:
            with tenant_scope(tenant):
                plan = str(plan_service.current_plan_id() or "free").strip().lower()
        except Exception:
            plan = "free"
    return plan if plan in DEFAULTS["plans"] else "free"


def tenant_status(tenant: str | None = None) -> dict[str, Any]:
    """Cap usage for one seller: used vs cap on both windows plus a tier."""
    bucket = str(tenant or "").strip() or _tenant_bucket("llm")
    cfg = _config()
    days = _ledger()
    daily_used = _window(days, span=1, buckets=[bucket])
    weekly_used = _window(days, span=7, buckets=[bucket])
    caps = cfg["plans"].get(_plan_of(bucket)) or cfg["plans"]["free"]
    daily_cap = float(caps.get("dailyUsd") or 0.0)
    weekly_cap = float(caps.get("weeklyUsd") or 0.0)
    ratio = float(cfg.get("notifyRatio") or 0.8)
    capped = (daily_cap > 0 and daily_used >= daily_cap) or (weekly_cap > 0 and weekly_used >= weekly_cap)
    warn = (daily_cap > 0 and daily_used >= daily_cap * ratio) or (
        weekly_cap > 0 and weekly_used >= weekly_cap * ratio
    )
    return {
        "tenant": "self" if bucket not in {SOZAN_BUCKET, "#anonymous"} else bucket,
        "plan": _plan_of(bucket),
        "dailyUsedUsd": daily_used,
        "dailyCapUsd": daily_cap,
        "weeklyUsedUsd": weekly_used,
        "weeklyCapUsd": weekly_cap,
        "tier": "capped" if capped else ("warn" if warn else "ok"),
    }


def cloud_blocked(*, surface: str) -> str | None:
    """Reason this surface must skip cloud now, or None when cloud is allowed.

    The live phone never blocks; a tenant at 100% of either window and the
    whole company at its daily cap go to the local model instead.
    """
    if str(surface or "").strip().lower() in VOICE_BUCKETS:
        return None
    cfg = _config()
    days = _ledger()
    company_cap = float(cfg["company"].get("dailyUsd") or 0.0)
    if company_cap > 0 and _company_window(days, span=1) >= company_cap:
        return "company"
    bucket = _tenant_bucket(surface)
    caps = cfg["plans"].get(_plan_of(bucket)) or cfg["plans"]["free"]
    daily_cap = float(caps.get("dailyUsd") or 0.0)
    weekly_cap = float(caps.get("weeklyUsd") or 0.0)
    if daily_cap > 0 and _window(days, span=1, buckets=[bucket]) >= daily_cap:
        return "daily"
    if weekly_cap > 0 and _window(days, span=7, buckets=[bucket]) >= weekly_cap:
        return "weekly"
    return None


def _hash_tenant(tenant: str) -> str:
    return hashlib.sha256(tenant.encode("utf-8")).hexdigest()[:12]


def report() -> dict[str, Any]:
    """Admin view: per-plan totals, company totals, top tenants hashed."""
    cfg = _config()
    days = _ledger()
    by_tenant: dict[str, float] = {}
    for day in sorted(days)[-7:]:
        for tenant, value in days[day].items():
            by_tenant[tenant] = round(float(by_tenant.get(tenant, 0.0)) + float(value), 6)
    plans: dict[str, dict[str, float]] = {}
    for tenant, value in by_tenant.items():
        plan = _plan_of(tenant)
        row = plans.setdefault(plan, {"weekUsd": 0.0, "tenants": 0})
        row["weekUsd"] = round(row["weekUsd"] + value, 6)
        row["tenants"] += 1
    top = sorted(by_tenant.items(), key=lambda item: -item[1])[:10]
    return {
        "company": {
            "dailyUsedUsd": _company_window(days, span=1),
            "dailyCapUsd": float(cfg["company"].get("dailyUsd") or 0.0),
            "weeklyUsedUsd": _company_window(days, span=7),
        },
        "plans": {plan: row for plan, row in sorted(plans.items())},
        "topTenants": [{"tenant": _hash_tenant(name), "weekUsd": value} for name, value in top],
        "sozanVoiceWeekUsd": round(float(by_tenant.get(SOZAN_BUCKET, 0.0)), 6),
    }
