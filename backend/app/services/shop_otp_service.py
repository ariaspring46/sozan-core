from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from app.config import settings
from app.phone import normalize_phone
from app.redis_client import redis_client
from app.services import sms_service, wallet_service
from app.services.auth_service import OTP_SEND_LIMIT, OTP_SEND_WINDOW, OTP_VERIFY_LIMIT, OTP_VERIFY_WINDOW
from app.services.pay_service import find_tenant_by_slug
from app.services.settings_service import get_settings
from app.state_store import tenant_scope


class OtpLimitError(ValueError):
    pass


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
    rl_key = f"shop-otp:rl:{slug}:{receptor}"
    hits = await redis_client.incr(rl_key)
    if hits == 1:
        await redis_client.expire(rl_key, OTP_SEND_WINDOW)
    if hits > OTP_SEND_LIMIT:
        raise OtpLimitError("تعداد درخواست بیش از حد است")
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
        consumed = wallet_service.consume_sms()
        charged = int(consumed.get("charged") or 0)
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
            wallet_service.refund_sms(charged)
            await redis_client.delete(f"shop-otp:{slug}:{receptor}")
            raise
        payload["loginMode"] = "sms"
        return payload


async def verify(*, slug: str, phone: str, code: str) -> dict:
    if not find_tenant_by_slug(slug):
        raise ValueError("فروشگاه پیدا نشد")
    receptor = normalize_phone(phone)
    vl_key = f"shop-otp:vl:{slug}:{receptor}"
    hits = await redis_client.incr(vl_key)
    if hits == 1:
        await redis_client.expire(vl_key, OTP_VERIFY_WINDOW)
    if hits > OTP_VERIFY_LIMIT:
        raise OtpLimitError("تعداد تلاش بیش از حد است")
    stored = await redis_client.get(f"shop-otp:{slug}:{receptor}")
    if stored is None or stored != code.strip():
        raise ValueError("کد یک‌بارمصرف نادرست است")
    await redis_client.delete(f"shop-otp:{slug}:{receptor}")
    await redis_client.delete(vl_key)
    return {"ok": True, "token": mint_token(slug=slug, phone=receptor), "role": "shopper"}
