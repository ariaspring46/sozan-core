from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.config import settings as env
from app.services import payment_service, sms_service
from app.services.plan_service import snapshot as plan_snapshot
from app.state_store import read_json, shared_lock, write_json

OTP_TTL_MIN = 60
OTP_TTL_MAX = 900
STUDIO_KEYS = (
    "mockSms",
    "adminPhone",
    "otpTtlSeconds",
    "gatewayPublicUrl",
)
SECRET_KEYS = ("smsApiKey", "paymentApiKey")
INTEGRATION_DEFAULTS = {
    "paymentSandbox": True,
    "paymentGateway": "mock",
    "paymentMerchantId": "",
    "paymentApiKey": "",
    "paymentCurrency": "IRT",
    "paymentCallbackUrl": "",
    "smsProvider": "smsir",
    "smsApiKey": "",
    "smsTemplateId": "",
    "smsTokenName": "Code",
}
DEFAULTS = {
    "mockSms": env.otp_dev,
    "adminPhone": env.admin_phone,
    "otpTtlSeconds": env.otp_ttl_seconds,
    "gatewayPublicUrl": env.gateway_sozan_url,
    "storeName": "فروشگاه",
    "storeTagline": "",
    **INTEGRATION_DEFAULTS,
}


def _studio() -> dict:
    stored = read_json("settings.json", {}, shared=True)
    if not isinstance(stored, dict):
        stored = {}
    out = {key: DEFAULTS[key] for key in STUDIO_KEYS}
    out.update({key: stored[key] for key in STUDIO_KEYS if key in stored})
    return out


def _integrations() -> dict:
    stored = read_json("integrations.json", {})
    if not isinstance(stored, dict):
        stored = {}
    studio = read_json("settings.json", {}, shared=True)
    if not isinstance(studio, dict):
        studio = {}
    out = deepcopy(INTEGRATION_DEFAULTS)
    # Older checkouts stored payment flags in shared settings.json.
    for key in ("paymentSandbox", "paymentGateway"):
        if key in studio and key not in stored:
            out[key] = studio[key]
    out.update({key: stored[key] for key in INTEGRATION_DEFAULTS if key in stored})
    gateway = str(out.get("paymentGateway") or "mock").strip().lower()
    out["paymentGateway"] = gateway if gateway in {item["id"] for item in payment_service.GATEWAYS} else "mock"
    provider = str(out.get("smsProvider") or "smsir").strip().lower()
    out["smsProvider"] = provider if provider in {item["id"] for item in sms_service.PROVIDERS} else "smsir"
    currency = str(out.get("paymentCurrency") or "IRT").strip().upper()
    out["paymentCurrency"] = currency if currency in {"IRT", "IRR"} else "IRT"
    return out


def get_settings() -> dict:
    out = deepcopy(DEFAULTS)
    out.update(_studio())
    out.update(_integrations())
    shop = read_json("shop.json", {})
    if isinstance(shop, dict):
        if str(shop.get("brand") or "").strip():
            out["storeName"] = str(shop["brand"]).strip()
        if str(shop.get("tagline") or "").strip():
            out["storeTagline"] = str(shop["tagline"]).strip()
    return out


def public_settings() -> dict:
    from app.services.voice_service import get_voice

    raw = get_settings()
    out = {key: raw[key] for key in raw if key not in SECRET_KEYS}
    hub_sms = sms_service.resolve_sms({})
    tenant_sms = bool(str(raw.get("smsApiKey") or "").strip())
    hub_sms_ready = bool(hub_sms.get("api_key") and hub_sms.get("template_id"))
    out["smsFromHub"] = hub_sms_ready and not tenant_sms
    out["smsApiKeySet"] = tenant_sms or hub_sms_ready
    out["paymentApiKeySet"] = bool(str(raw.get("paymentApiKey") or "").strip())
    out["payment"] = payment_service.public_status({**raw, "paymentApiKeySet": out["paymentApiKeySet"]})
    out["smsProviders"] = sms_service.public_catalog()
    out["paymentGateways"] = payment_service.public_catalog()
    out["subscription"] = plan_snapshot()
    out["plan"] = out["subscription"]["plan"]
    hub_merchant = bool(str(env.zarinpal_merchant_id or "").strip())
    tenant_merchant = bool(str(raw.get("paymentMerchantId") or "").strip())
    out["paymentMerchantFromHub"] = hub_merchant and not tenant_merchant
    out["billing"] = {
        "ready": payment_service.hub_payments_open(),
        "gateway": "zarinpal",
    }
    from app.services import wallet_service

    try:
        out["walletAvailable"] = int(wallet_service.get().get("available") or 0)
    except (TypeError, ValueError):
        out["walletAvailable"] = 0
    if out["smsFromHub"]:
        out["smsProvider"] = hub_sms["provider"] or out.get("smsProvider") or "smsir"
        if hub_sms.get("template_id"):
            out["smsTemplateId"] = hub_sms["template_id"]
        if hub_sms.get("token_name"):
            out["smsTokenName"] = hub_sms["token_name"]
    out["helpImprove"] = allows_training()
    voice = get_voice()
    out["voice"] = {
        "summary": voice.get("summary") or "",
        "tone": voice.get("tone") or "",
        "sampleReply": voice.get("sampleReply") or "",
        "at": voice.get("at") or 0,
    }
    return out


def save_settings(patch: dict, *, hub_admin: bool = False) -> dict:
    from app.services import plan_service

    with shared_lock():
        studio = _studio()
        studio_touch = [key for key in STUDIO_KEYS if key in patch and patch[key] is not None]
        if studio_touch and not hub_admin:
            raise PermissionError("این تنظیمات فقط برای مدیر هاب است")
        for key in STUDIO_KEYS:
            if key not in patch or patch[key] is None:
                continue
            if key == "otpTtlSeconds":
                ttl = int(patch[key])
                if ttl < OTP_TTL_MIN or ttl > OTP_TTL_MAX:
                    raise ValueError("عمر کد باید بین ۶۰ تا ۹۰۰ ثانیه باشد")
                studio[key] = ttl
                continue
            studio[key] = patch[key]
        studio.pop("plan", None)

        integrations = _integrations()
        for key in INTEGRATION_DEFAULTS:
            if key not in patch or patch[key] is None:
                continue
            if key in SECRET_KEYS and not str(patch[key]).strip():
                continue
            integrations[key] = patch[key]
            if isinstance(integrations[key], str):
                integrations[key] = integrations[key].strip()
        payment_service.validate_patch(patch, integrations)
        provider = str(integrations.get("smsProvider") or "smsir").strip().lower()
        if provider not in {item["id"] for item in sms_service.PROVIDERS}:
            raise ValueError("این درگاه پیامک پشتیبانی نمی‌شود")
        integrations["smsProvider"] = provider
        if "plan" in patch and patch["plan"] is not None:
            wanted = str(patch["plan"]).strip().lower()
            current = plan_service.current_plan_id()
            if wanted != current and wanted != "free":
                raise ValueError("برای اشتراک پرو از پرداخت زرین‌پال استفاده کن")
            plan_service.set_plan(wanted)
        write_json("settings.json", studio, shared=True)
    write_json("integrations.json", integrations)
    if "storeName" in patch or "storeTagline" in patch:
        from app.state_store import update_json

        def _brand(shop: dict) -> None:
            if "storeName" in patch and patch["storeName"] is not None:
                shop["brand"] = str(patch["storeName"]).strip()
            if "storeTagline" in patch and patch["storeTagline"] is not None:
                shop["tagline"] = str(patch["storeTagline"]).strip()

        # shop.json is also written by the build (X4) and the pay secret (C): locked update.
        update_json("shop.json", _brand, {}, lock="shop")
    if "helpImprove" in patch and patch["helpImprove"] is not None:
        save_training_choice(bool(patch["helpImprove"]))
    return public_settings()


TRAINING_FILE = "training.json"


def allows_training() -> bool:
    """True unless this seller turned «کمک به بهتر شدن سوزان» off.

    training_log.log_example must call this before it writes a sample.
    """
    raw = read_json(TRAINING_FILE, {})
    if not isinstance(raw, dict) or "helpImprove" not in raw:
        return True
    return bool(raw.get("helpImprove"))


def save_training_choice(value: bool) -> bool:
    choice = bool(value)
    write_json(TRAINING_FILE, {"helpImprove": choice})
    return choice


def note_training_example(example: dict, dest: Path) -> bool:
    if not allows_training():
        return False
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(example, ensure_ascii=False) + "\n")
    return True
