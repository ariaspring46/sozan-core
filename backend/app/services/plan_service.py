from __future__ import annotations

from copy import deepcopy
from time import time

from app.config import settings as env
from app.state_store import read_json, write_json

PLANS = {
    "free": {
        "id": "free",
        "label": "رایگان",
        "sites": 1,
        "channels": 2,
        "autoReply": "",
        "dmSync": False,
        "priceToman": 0,
        "smsQuota": int(env.sms_quota_free or 50),
        "features": [
            "ساخت یک وب‌سایت",
            "انبار کالا",
            "چت دستی مشتریان",
        ],
    },
    "pro": {
        "id": "pro",
        "label": "پرو",
        "sites": 3,
        "channels": 5,
        "autoReply": "draft",
        "dmSync": True,
        "priceToman": int(env.plan_price_pro or 490000),
        "smsQuota": int(env.sms_quota_pro or 500),
        "features": [
            "تا سه وب‌سایت",
            "یادگیری لحن فروشنده",
            "خواندن دایرکت اینستاگرام",
            "پیش‌نویس پاسخ با لحن فروشنده",
        ],
    },
    "promax": {
        "id": "promax",
        "label": "پرو مکس",
        "sites": 0,
        "channels": 0,
        "autoReply": "send",
        "dmSync": True,
        "priceToman": int(env.plan_price_promax or 1490000),
        "smsQuota": int(env.sms_quota_promax or 2000),
        "features": [
            "وب‌سایت نامحدود",
            "همه کانال‌ها",
            "پاسخ خودکار دایرکت با لحن فروشنده",
        ],
    },
}


def _sites() -> list[str]:
    rows = read_json("sites.json", [])
    if isinstance(rows, list) and rows:
        return [str(item) for item in rows if str(item).strip()]
    shop = read_json("shop.json", {})
    slug = str(shop.get("slug") or "").strip() if isinstance(shop, dict) else ""
    return [slug] if slug else []


def record_site(slug: str) -> None:
    slug = slug.strip()
    if not slug:
        return
    rows = _sites()
    if slug not in rows:
        rows.append(slug)
        write_json("sites.json", rows)


def current_plan_id() -> str:
    stored = read_json("plan.json", {})
    if isinstance(stored, dict):
        plan = str(stored.get("plan") or "").strip().lower()
        if plan in PLANS:
            return plan
    return "free"


def set_plan(plan_id: str) -> dict:
    plan = str(plan_id or "free").strip().lower()
    if plan not in PLANS:
        raise ValueError("این اشتراک وجود ندارد")
    write_json("plan.json", {"plan": plan, "at": int(time())})
    return snapshot()


def current() -> dict:
    return deepcopy(PLANS[current_plan_id()])


def snapshot() -> dict:
    plan = current()
    used = len(_sites())
    limit = int(plan["sites"])
    return {
        "plan": plan["id"],
        "label": plan["label"],
        "sitesUsed": used,
        "sitesLimit": limit,
        "channelsLimit": int(plan["channels"]),
        "autoReply": plan["autoReply"],
        "dmSync": bool(plan["dmSync"]),
        "smsQuota": int(plan.get("smsQuota") or 0),
        "features": list(plan["features"]),
        "plans": [
            {
                "id": item["id"],
                "label": item["label"],
                "sites": item["sites"],
                "priceToman": int(item.get("priceToman") or 0),
                "smsQuota": int(item.get("smsQuota") or 0),
                "features": item["features"],
            }
            for item in PLANS.values()
        ],
    }


def allow_new_site() -> str | None:
    plan = current()
    limit = int(plan["sites"])
    if limit == 0:
        return None
    if len(_sites()) >= limit:
        return f"پلن {plan['label']} فقط {limit} وب‌سایت می‌سازد. برای فروشگاه جدید پرو یا پرو مکس لازم است."
    return None


def allow_new_channel(already: int) -> str | None:
    plan = current()
    limit = int(plan["channels"])
    if limit == 0:
        return None
    if already >= limit:
        return f"پلن {plan['label']} تا {limit} کانال می‌پذیرد."
    return None
