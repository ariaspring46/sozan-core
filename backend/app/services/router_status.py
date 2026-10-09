"""The `status` tool: what the seller's shop, scan, plan, wallet, domain and catalog look like right now.

Read-only. router_tools routes the tool here; router_service re-exports the names it and its tests use.
"""

from __future__ import annotations



class _Router:
    """router_service, looked up at call time: either module may be imported first (router_service imports this
    one at its end), and a test that patches router_service still reaches the code here."""

    def __getattr__(self, name: str):
        from app.services import router_service

        return getattr(router_service, name)


rs = _Router()

async def _status_payload() -> dict:
    from app.services import channel_service, plan_service, shop_service, wallet_service

    snap = shop_service.snapshot()
    shop = snap.get("shop") or {}
    scan = snap.get("scan") or {}
    build = snap.get("build") or {}
    accounts = channel_service.list_accounts().get("accounts") or []
    plan = plan_service.snapshot()
    wallet = wallet_service.get()
    return {
        "shopStatus": shop.get("status") or "",
        "slug": shop.get("slug") or "",
        "cnameOk": rs._domain_ok(shop),
        "scanStatus": scan.get("status") or "",
        "scanNoPrice": scan.get("noPrice"),
        "scanNoImage": scan.get("noImage"),
        "buildStatus": build.get("status") or "",
        "channels": [
            {
                "platform": row.get("platform"),
                "handle": row.get("handle"),
                "connected": bool(row.get("connected")),
            }
            for row in accounts
        ],
        "plan": plan.get("plan") or plan.get("id") or "",
        "walletAvailable": int(wallet.get("available") or 0),
        "missingImages": _missing_image_titles(),
    }


def _missing_image_titles() -> list[str]:
    from app.services.storefront_service import _list, _row_images

    titles: list[str] = []
    for row in _list("products.json"):
        if _row_images(row):
            continue
        title = str(row.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    return titles[:8]


_STATUS_FA = {
    "ready": "آماده",
    "running": "در حال ساخت",
    "queued": "در صف",
    "failed": "ناموفق",
    "idle": "بیکار",
    "done": "تمام",
    "free": "رایگان",
    "pro": "پرو",
    "pro_max": "پرو مکس",
    "promax": "پرو مکس",
    "ultra": "اولترا",
}


def _format_status(data: dict) -> str:
    chans = data.get("channels") or []
    parts: list[str] = []
    for c in chans:
        handle = str(c.get("handle") or "").strip().lstrip("@")
        label = rs._CHANNEL_FA.get(str(c.get("platform")), str(c.get("platform") or ""))
        part = f"{label}{f' ({handle})' if handle else ''} {'وصل است' if c.get('connected') else 'وصل نیست'}"
        if part not in parts:
            parts.append(part)
    chan = "، ".join(parts)
    state = str(data.get("shopStatus") or "")
    build = str(data.get("buildStatus") or "")
    host = rs._shop_public()
    if "failed" in (state, build):
        shop_line = "ساخت فروشگاه کامل نشد."
    elif state in {"running", "queued"} or build in {"running", "queued"}:
        shop_line = "فروشگاه در حال ساخت است."
    elif state == "ready":
        shop_line = f"فروشگاه آماده است: {host}" if host else "فروشگاه آماده است."
    else:
        shop_line = "فروشگاه هنوز ساخته نشده."
    lines = [
        shop_line,
        f"دامنه: {'وصل است' if data.get('cnameOk') else 'هنوز وصل نشده'}",
        f"پلن: {rs._fa_status(data.get('plan'))}",
        f"موجودی کیف پول: {rs.router_text.fa_money(data.get('walletAvailable') or 0)} تومان",
        f"کانال‌ها: {chan or 'هنوز وصل نشده'}",
    ]
    missing = [str(item).strip() for item in (data.get("missingImages") or []) if str(item).strip()]
    if missing:
        lines.append("بدون عکس: " + "، ".join(missing))
    text = "\n".join(lines)
    if "failed" in (state, build):
        text += "\nبگو «فروشگاه را از نو بساز» تا دوباره بسازم."
    return text
