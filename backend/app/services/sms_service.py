from __future__ import annotations

import httpx

from app.phone import normalize_phone

PROVIDERS = (
    {
        "id": "kavenegar",
        "label": "کاوه نگار",
        "docs": "https://kavenegar.com/rest.html",
        "help": "از پنل کاوه نگار کلید API و نام الگوی Verify Lookup را بردار. الگو باید قبل از ارسال در پنل تأیید شده باشد.",
    },
    {
        "id": "smsir",
        "label": "SMS.ir",
        "docs": "https://sms.ir/rest-api/",
        "help": "از پنل SMS.ir کلید API و شناسه عددی قالب ارسال سریع (verify) را بردار.",
    },
)


def public_catalog() -> list[dict]:
    return [dict(item) for item in PROVIDERS]


async def send_otp(*, provider: str, api_key: str, template_id: str, token_name: str, phone: str, code: str) -> None:
    key = api_key.strip()
    template = template_id.strip()
    if not key or not template:
        raise ValueError("کلید API و شناسه قالب پیامک را در تنظیمات بیشتر بگذار.")
    receptor = normalize_phone(phone)
    kind = (provider or "kavenegar").strip().lower()
    if kind == "smsir":
        await _smsir(key=key, template=template, token_name=token_name, mobile=receptor, code=code)
        return
    if kind != "kavenegar":
        raise ValueError("این درگاه پیامک پشتیبانی نمی‌شود")
    await _kavenegar(key=key, template=template, receptor=receptor, code=code)


async def _kavenegar(*, key: str, template: str, receptor: str, code: str) -> None:
    # Official Verify Lookup: https://kavenegar.com/rest.html
    url = f"https://api.kavenegar.com/v1/{key}/verify/lookup.json"
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.post(
            url,
            data={"receptor": receptor, "token": code, "template": template},
        )
    payload = _json(response)
    status = ((payload.get("return") or {}) if isinstance(payload.get("return"), dict) else {}).get("status")
    if response.status_code >= 400 or (status not in (None, 200)):
        raise ValueError("کاوه نگار پیامک را نفرستاد. کلید API و نام قالب را در پنل بررسی کن.")


def smsir_mobile(phone: str) -> str:
    receptor = normalize_phone(phone)
    return receptor[1:] if receptor.startswith("0") else receptor


def resolve_sms(overlay: dict | None = None) -> dict[str, str]:
    from app.config import settings as env

    row = overlay if isinstance(overlay, dict) else {}
    tenant_key = str(row.get("smsApiKey") or "").strip()
    tenant_template = str(row.get("smsTemplateId") or "").strip()
    if tenant_key and tenant_template:
        provider = str(row.get("smsProvider") or "smsir").strip().lower() or "smsir"
        token_name = str(row.get("smsTokenName") or "").strip()
        if provider == "smsir" and not token_name:
            token_name = str(env.sms_ir_token_name or "Code")
        if provider != "smsir" and not token_name:
            token_name = "CODE"
        return {
            "provider": provider,
            "api_key": tenant_key,
            "template_id": tenant_template,
            "token_name": token_name,
        }
    return {
        "provider": str(env.sms_provider or "smsir").strip().lower() or "smsir",
        "api_key": str(env.sms_ir_api_key or "").strip(),
        "template_id": str(env.sms_ir_template_id or "").strip(),
        "token_name": str(env.sms_ir_token_name or "Code").strip() or "Code",
    }


async def _smsir(*, key: str, template: str, token_name: str, mobile: str, code: str) -> None:
    # Official verify: POST https://api.sms.ir/v1/send/verify with x-api-key
    name = (token_name or "Code").strip() or "Code"
    try:
        template_id = int(template)
    except ValueError as exc:
        raise ValueError("شناسه قالب SMS.ir باید عدد باشد.") from exc
    payload_mobile = smsir_mobile(mobile)
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.post(
            "https://api.sms.ir/v1/send/verify",
            headers={"x-api-key": key, "Accept": "application/json"},
            json={
                "mobile": payload_mobile,
                "templateId": template_id,
                "parameters": [{"name": name, "value": code}],
            },
        )
    payload = _json(response)
    status = payload.get("status")
    if response.status_code >= 400 or (status not in (None, 1, True)):
        detail = str(payload.get("message") or "").strip()
        if detail and len(detail) < 80:
            raise ValueError(detail)
        raise ValueError("SMS.ir پیامک را نفرستاد. کلید API و شناسه قالب را در پنل بررسی کن.")


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
