from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from time import time

from app.config import settings as env
from app.state_store import read_json, write_json

_MONTHS = ("", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

PLANS = {
    "free": {
        "id": "free",
        "label": "رایگان",
        "sites": 1,
        "workspaces": 1,
        "channels": 2,
        "autoReply": "",
        "dmSync": False,
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
        "sites": 1,
        "workspaces": 1,
        "channels": 5,
        "autoReply": "draft",
        "dmSync": True,
        "smsQuota": int(env.sms_quota_pro or 500),
        "features": [
            "یک فروشگاه",
            "یادگیری لحن فروشنده",
            "خواندن دایرکت اینستاگرام",
            "پیش‌نویس پاسخ با لحن فروشنده",
        ],
    },
    "promax": {
        "id": "promax",
        "label": "پرو مکس",
        "sites": 1,
        "workspaces": 1,
        "channels": 0,
        "autoReply": "send",
        "dmSync": True,
        "smsQuota": int(env.sms_quota_promax or 2000),
        "features": [
            "یک فروشگاه",
            "همه کانال‌ها",
            "پاسخ خودکار دایرکت با لحن فروشنده",
        ],
    },
    "ultra": {
        "id": "ultra",
        "label": "اولترا",
        "sites": 1,
        "workspaces": 2,
        "channels": 0,
        "autoReply": "send",
        "dmSync": True,
        "smsQuota": int(env.sms_quota_promax or 2000),
        "features": [
            "همهٔ امکانات پرو مکس",
            "تا ۲ فضای کاری کامل",
        ],
    },
}


def list_price(plan_id: str) -> int:
    plan = str(plan_id or "").strip().lower()
    if plan == "pro":
        return max(0, int(env.plan_price_pro))
    if plan == "promax":
        return max(0, int(env.plan_price_promax))
    if plan == "ultra":
        return max(0, int(env.plan_price_ultra))
    return 0


def discount_percent() -> int:
    return max(0, min(90, int(env.plan_discount_percent or 0)))


def discount_until() -> datetime | None:
    raw = str(env.plan_discount_until or "").strip()
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def effective_price(plan_id: str, now: datetime | None = None) -> int:
    listed = list_price(plan_id)
    if listed <= 0:
        return 0
    until = discount_until()
    percent = discount_percent()
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if until and moment < until and percent:
        discounted = listed * (100 - percent)
        return ((discounted + 50_000) // 100_000) * 1000
    return listed


def purchasable(plan_id: str) -> bool:
    return str(plan_id or "").strip().lower() != "ultra"


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def shamsi_label(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo("Asia/Tehran"))
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    text = f"{jd} {_MONTHS[jm]} {jy}"
    return text.translate(_DIGITS)


def _card(item: dict, now: datetime | None = None) -> dict:
    plan_id = str(item["id"])
    listed = list_price(plan_id)
    price = effective_price(plan_id, now)
    return {
        "id": plan_id,
        "label": item["label"],
        "sites": int(item["sites"]),
        "workspaces": int(item.get("workspaces") or 1),
        "channels": int(item["channels"]),
        "listPrice": listed,
        "price": price,
        "priceToman": price,
        "period": "monthly",
        "smsQuota": int(item.get("smsQuota") or 0),
        "features": list(item["features"]),
        "purchasable": purchasable(plan_id),
        "checkout": "soon" if plan_id == "ultra" else ("free" if price <= 0 else "open"),
    }


def public_catalog(now: datetime | None = None) -> dict:
    until = discount_until()
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    active = bool(until and moment < until and discount_percent())
    return {
        "discountPercent": discount_percent() if active else 0,
        "discountUntil": until.isoformat() if active and until else None,
        "discountUntilLabel": shamsi_label(until) if active and until else "",
        "plans": [_card(item, moment) for item in PLANS.values()],
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
    catalog = public_catalog()
    return {
        "plan": plan["id"],
        "label": plan["label"],
        "sitesUsed": used,
        "sitesLimit": limit,
        "workspaces": int(plan.get("workspaces") or 1),
        "channelsLimit": int(plan["channels"]),
        "autoReply": plan["autoReply"],
        "dmSync": bool(plan["dmSync"]),
        "smsQuota": int(plan.get("smsQuota") or 0),
        "features": list(plan["features"]),
        "discountUntil": catalog["discountUntil"],
        "discountUntilLabel": catalog["discountUntilLabel"],
        "plans": catalog["plans"],
    }


def allow_new_site() -> str | None:
    plan = current()
    limit = int(plan["sites"])
    if limit == 0:
        return None
    if len(_sites()) >= limit:
        return f"پلن {plan['label']} فقط {limit} وب‌سایت می‌سازد."
    return None


def allow_new_channel(already: int) -> str | None:
    plan = current()
    limit = int(plan["channels"])
    if limit == 0:
        return None
    if already >= limit:
        return f"پلن {plan['label']} تا {limit} کانال می‌پذیرد."
    return None
