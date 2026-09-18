from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from app.config import settings
from app.phone import normalize_phone
from app.redis_client import redis_client
from app.services import sms_service, wallet_service
from app.services.pay_service import find_tenant_by_slug
from app.services.settings_service import get_settings
from app.state_store import tenant_scope


def _sign(body: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:24]


def mint_token(*, slug: str, phone: str) -> str:
    exp = int(time.time()) + 60 * 60 * 24 * 30
    body = f"{slug}|{phone}|{exp}"
    return f"{body}|{_sign(body)}"


async def send(*, slug: str, phone: str) -> dict:
    tenant = find_tenant_by_slug(slug)
    if not tenant:
        raise ValueError("فروشگاه پیدا نشد")
    receptor = normalize_phone(phone)
    with tenant_scope(tenant):
        overlay = get_settings()
        mock = overlay.get("mockSms")
        if mock is None:
            mock = settings.otp_dev is True
        else:
            mock = mock is True
        code = f"{secrets.randbelow(1_000_000):06d}"
        ttl = int(overlay.get("otpTtlSeconds") or settings.otp_ttl_seconds)
        payload = {"ok": True, "expiresIn": ttl}
        if mock:
            await redis_client.setex(f"shop-otp:{slug}:{receptor}", ttl, code)
            payload["dev_code"] = code
            payload["loginMode"] = "mock"
            return payload
        wallet_service.consume_sms()
        await redis_client.setex(f"shop-otp:{slug}:{receptor}", ttl, code)
        sms = sms_service.resolve_sms(overlay)
        try:
            await sms_service.send_otp(
                provider=sms["provider"],
                api_key=sms["api_key"],
                template_id=sms["template_id"],
                token_name=sms["token_name"],
                phone=receptor,
                code=code,
            )
        except Exception:
            await redis_client.delete(f"shop-otp:{slug}:{receptor}")
            raise
        payload["loginMode"] = "sms"
        return payload


async def verify(*, slug: str, phone: str, code: str) -> dict:
    if not find_tenant_by_slug(slug):
        raise ValueError("فروشگاه پیدا نشد")
    receptor = normalize_phone(phone)
    stored = await redis_client.get(f"shop-otp:{slug}:{receptor}")
    if stored is None or stored != code.strip():
        raise ValueError("کد یک‌بارمصرف نادرست است")
    await redis_client.delete(f"shop-otp:{slug}:{receptor}")
    return {"ok": True, "token": mint_token(slug=slug, phone=receptor), "role": "shopper"}
