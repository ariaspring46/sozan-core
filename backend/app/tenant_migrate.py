from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.config import settings
from app.phone import normalize_phone
from app.state_store import TENANT_JSON, tenant_scope, write_json


def _operator() -> str:
    return normalize_phone(settings.admin_phone)


def _root() -> Path:
    return settings.state_path


def _tenant_path(phone: str) -> Path:
    path = _root() / "tenants" / phone
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_brand(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("profile.json", "logo.png", "character.png"):
        item = src / name
        if item.is_file() and not (dest / name).is_file():
            shutil.copy2(item, dest / name)


def _handles_for_profile(row: dict) -> set[str]:
    brand = str(row.get("brandName") or "").strip()
    handles = set()
    if "زاویتا" in brand:
        handles.add("zavita_shose")
    return handles


def _seed_from_operator(phone: str, row: dict, operator: str) -> None:
    dest = _tenant_path(phone)
    if (dest / "shop.json").is_file():
        return
    op = _tenant_path(operator)
    handles = _handles_for_profile(row)
    products = _load(op / "products.json", [])
    channels = _load(op / "channels.json", [])
    scan = _load(op / "channel-scan.json", {})
    kept_products = [
        item
        for item in products
        if isinstance(item, dict) and str(item.get("sourceHandle") or "") in handles
    ]
    kept_channels = [
        item for item in channels if isinstance(item, dict) and str(item.get("handle") or "") in handles
    ]
    scan_accounts = [
        item
        for item in (scan.get("accounts") or [])
        if isinstance(item, dict) and str(item.get("handle") or "") in handles
    ]
    name = str(row.get("brandName") or "فروشگاه").strip() or "فروشگاه"
    work = str(row.get("brandWork") or "").strip()
    _dump(
        dest / "shop.json",
        {
            "brand": name,
            "slug": "",
            "port": 0,
            "domain": "",
            "jobId": "",
            "status": "idle",
            "url": "",
            "tagline": work,
        },
    )
    _dump(dest / "products.json", kept_products)
    _dump(dest / "channels.json", kept_channels)
    _dump(
        dest / "channel-scan.json",
        {
            "accounts": scan_accounts,
            "colors": [c for item in scan_accounts for c in (item.get("colors") or [])],
            "about": " ".join(str(item.get("about") or "") for item in scan_accounts)[:800],
            "productCount": sum(len(item.get("products") or []) for item in scan_accounts),
        },
    )
    _dump(dest / "shop-messages.json", [])
    _dump(dest / "shop-brief.json", {})
    _dump(dest / "studio-messages.json", [])
    _dump(dest / "inbox.json", {"threads": []})
    _dump(dest / "sales.json", [])
    _dump(dest / "campaign-ids.json", [])
    voice = _load(op / "voice.json", {})
    if handles and str(voice.get("source") or "") in {f"instagram:{h}" for h in handles}:
        _dump(dest / "voice.json", voice)
    if handles:
        remaining_products = [
            item
            for item in products
            if isinstance(item, dict) and str(item.get("sourceHandle") or "") not in handles
        ]
        remaining_channels = [
            item
            for item in channels
            if isinstance(item, dict) and str(item.get("handle") or "") not in handles
        ]
        remaining_scan = [
            item
            for item in (scan.get("accounts") or [])
            if isinstance(item, dict) and str(item.get("handle") or "") not in handles
        ]
        _dump(op / "products.json", remaining_products)
        _dump(op / "channels.json", remaining_channels)
        _dump(
            op / "channel-scan.json",
            {
                "accounts": remaining_scan,
                "colors": [c for item in remaining_scan for c in (item.get("colors") or [])],
                "about": " ".join(str(item.get("about") or "") for item in remaining_scan)[:800],
                "productCount": sum(len(item.get("products") or []) for item in remaining_scan),
            },
        )


def migrate_files() -> None:
    operator = _operator()
    dest = _tenant_path(operator)
    marker = dest / ".migrated"
    if not marker.is_file():
        for name in TENANT_JSON:
            src = _root() / name
            if src.is_file() and not (dest / name).is_file():
                shutil.copy2(src, dest / name)
        _copy_brand(settings.brand_path, dest / "brand")
        shop = _load(dest / "shop.json", {})
        if isinstance(shop, dict) and str(shop.get("brand") or "") == "زاویتا":
            _dump(
                dest / "shop.json",
                {
                    "brand": "کیف و کفش نیاوران",
                    "slug": "kif-kafsh-niavaran",
                    "port": 12404,
                    "domain": "",
                    "jobId": "",
                    "status": "ready",
                    "url": "http://127.0.0.1:12404",
                    "tagline": "چرم، کتانی و کیف دست‌دوز",
                },
            )
            _dump(dest / "shop-messages.json", [])
        _dump(dest / "studio-messages.json", [])
        marker.write_text("1\n", encoding="utf-8")
    studio = _load(_root() / "settings.json", {})
    if isinstance(studio, dict) and studio.get("storeName") == "زاویتا":
        studio["storeName"] = "کیف و کفش نیاوران"
        studio["storeTagline"] = "چرم، کتانی و کیف دست‌دوز"
        _dump(_root() / "settings.json", studio)
    profiles = _load(_root() / "profiles.json", {})
    if not isinstance(profiles, dict):
        return
    for phone, row in profiles.items():
        if phone == operator or not isinstance(row, dict) or not row.get("onboarded"):
            continue
        _seed_from_operator(phone, row, operator)
    from app.services.storefront_service import retitle_scanned_from_captions

    tenants = _root() / "tenants"
    if tenants.is_dir():
        for path in tenants.iterdir():
            if path.is_dir() and path.name != "_none":
                with tenant_scope(path.name):
                    retitle_scanned_from_captions()
    _migrate_plans()


def _migrate_plans() -> None:
    from app.services.plan_service import PLANS

    studio_path = _root() / "settings.json"
    studio = _load(studio_path, {})
    shared = str(studio.get("plan") or "").strip().lower() if isinstance(studio, dict) else ""
    if shared not in PLANS:
        shared = "free"
    targets = {_operator(), "09135409482"}
    for phone in targets:
        folder = _root() / "tenants" / phone
        dest = folder / "plan.json"
        if dest.is_file() or not folder.is_dir():
            continue
        _dump(dest, {"plan": shared})
    if isinstance(studio, dict) and "plan" in studio:
        studio.pop("plan", None)
        _dump(studio_path, studio)


async def migrate_campaign_ids() -> None:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.user import Campaign

    operator = _operator()
    path = _tenant_path(operator) / "campaign-ids.json"
    if path.is_file():
        return
    async with SessionLocal() as session:
        result = await session.execute(select(Campaign.id))
        ids = [str(item) for item in result.scalars().all()]
    with tenant_scope(operator):
        write_json("campaign-ids.json", ids)
