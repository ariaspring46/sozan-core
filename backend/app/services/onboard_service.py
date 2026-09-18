from __future__ import annotations

import json

from app.config import settings
from app.repositories.brand_repository import BrandRepository
from app.services import brand_service, channel_scan_service, channel_service, profile_service, settings_service, shop_service, storefront_service, voice_service
from app.state_store import brand_dir, write_json

SHOP_BRIEF = "shop-brief.json"
CATALOG_PLATFORMS = frozenset({"instagram", "telegram"})


def _brand_svc():
    return brand_service.BrandService(BrandRepository(brand_dir(), settings.fonts_path))


def get_brief() -> dict:
    from app.state_store import read_json

    data = read_json(SHOP_BRIEF, {})
    return data if isinstance(data, dict) else {}


def save_brief(patch: dict) -> dict:
    brief = get_brief()
    for key, value in patch.items():
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                brief[key] = text[:400]
        elif isinstance(value, list):
            brief[key] = [str(item).strip() for item in value if str(item).strip()][:12]
        elif isinstance(value, bool):
            brief[key] = value
    write_json(SHOP_BRIEF, brief)
    return brief


def brief_ready(brief: dict | None = None) -> bool:
    data = brief or get_brief()
    return bool(str(data.get("style") or "").strip() and str(data.get("colors") or "").strip())


def brief_block() -> str:
    brief = get_brief()
    if not brief:
        return "مصاحبه فروشگاه هنوز تمام نشده."
    return (
        f"سبک سایت: {brief.get('style') or '—'}\n"
        f"رنگ‌ها: {brief.get('colors') or '—'}\n"
        f"ویژگی‌ها: {brief.get('features') or '—'}\n"
        f"نکته کاربر: {brief.get('notes') or '—'}"
    )


def _channels_from_payload(channels: list | None) -> list[dict]:
    out = []
    for item in channels or []:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "").strip().lower()
        handle = str(item.get("handle") or "").strip()
        if platform and handle:
            out.append({"platform": platform, "handle": handle})
    return out


def parse_channels(raw: str | list | None) -> list[dict]:
    if isinstance(raw, list):
        return _channels_from_payload(raw)
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _channels_from_payload(parsed if isinstance(parsed, list) else [])


def catalog_channel(channels: list | None) -> dict | None:
    for item in _channels_from_payload(channels):
        if item["platform"] in CATALOG_PLATFORMS:
            return item
    return None


def _catalog_scan_row(channels: list | None) -> dict | None:
    picked = catalog_channel(channels)
    if not picked:
        return None
    sendbox_id = ""
    if picked["platform"] == "instagram":
        ig = channel_service.account_for_platform("instagram")
        if ig:
            connected = str(ig.get("handle") or "").strip().lstrip("@").lower()
            typed = picked["handle"].strip().lstrip("@").lower()
            if connected and typed == connected:
                sendbox_id = channel_service.sendbox_account_id(ig)
    return {
        "platform": picked["platform"],
        "handle": picked["handle"],
        "sendboxAccountId": sendbox_id,
    }


def snapshot(phone: str) -> dict:
    listed = channel_service.list_accounts()
    return {
        "profile": profile_service.get_profile(phone),
        "platforms": listed.get("platforms") or [],
        "accounts": listed.get("accounts") or [],
    }


def save_draft(
    phone: str,
    *,
    first_name: str = "",
    last_name: str = "",
    brand_name: str = "",
    brand_work: str = "",
    tone_id: str = "",
) -> dict:
    patch = {}
    if first_name.strip():
        patch["firstName"] = first_name
    if last_name.strip():
        patch["lastName"] = last_name
    if brand_name.strip():
        patch["brandName"] = brand_name
    if brand_work.strip():
        patch["brandWork"] = brand_work
    if tone_id.strip():
        patch["toneId"] = tone_id
    if patch:
        profile_service.patch_profile(phone, patch)
    return snapshot(phone)


async def complete(
    *,
    phone: str,
    first_name: str,
    last_name: str,
    brand_name: str,
    brand_work: str,
    tone_id: str,
    channels: list | None,
    logo: bytes | None,
    logo_name: str,
) -> dict:
    name = brand_name.strip()
    work = brand_work.strip()
    if not name or not work:
        raise ValueError("نام برند و کاری که انجام می‌دهید لازم است")
    profile = profile_service.complete(
        phone,
        firstName=first_name,
        lastName=last_name,
        brandName=name,
        brandWork=work,
        toneId=tone_id,
        hasLogo=bool(logo),
    )
    settings_service.save_settings({"storeName": name, "storeTagline": work})
    _brand_svc().update(name=name, description=work)
    if logo:
        _brand_svc().save_logo(logo_name or "logo.png", logo)
    if tone_id.strip():
        voice_service.apply_tone(tone_id)
    picked = catalog_channel(channels)
    scan_row = _catalog_scan_row(channels)
    if scan_row:
        storefront_service.clear_scanned_catalog()
        write_json("channel-scan.json", {})
        channel_scan_service.start_scan([scan_row])
    shop_service.reset_for_brand(name=name, tagline=work)
    write_json(SHOP_BRIEF, {})
    return {
        "ok": True,
        "profile": profile,
        "channels": [picked] if picked else [],
        "scan": channel_scan_service.scan_status(),
    }
