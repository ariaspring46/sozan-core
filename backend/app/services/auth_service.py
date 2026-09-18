from __future__ import annotations

import secrets

from fastapi import HTTPException, status

from app.config import settings
from app.phone import normalize_phone
from app.redis_client import redis_client
from app.repositories.user_repository import UserRepository
from app.security import encode_token
from app.services import sms_service
from app.services.settings_service import get_settings
from app.state_store import tenant_scope


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    async def send_otp(self, phone_raw: str) -> dict:
        try:
            phone = normalize_phone(phone_raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        with tenant_scope(phone):
            overlay = get_settings()
        mock_sms = overlay.get("mockSms")
        if mock_sms is None:
            mock_sms = settings.otp_dev is True
        else:
            mock_sms = mock_sms is True
        rl_key = f"otp:rl:{phone}"
        hits = await redis_client.incr(rl_key)
        if hits == 1:
            await redis_client.expire(rl_key, 900)
        if hits > 5:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "تعداد درخواست بیش از حد است")
        code = f"{secrets.randbelow(1_000_000):06d}"
        ttl = int(overlay.get("otpTtlSeconds") or settings.otp_ttl_seconds)
        await redis_client.setex(f"otp:{phone}", ttl, code)
        payload = {"ok": True}
        if mock_sms:
            payload["dev_code"] = code
            return payload
        from app.services import wallet_service

        try:
            with tenant_scope(phone):
                wallet_service.consume_sms()
        except ValueError as exc:
            await redis_client.delete(f"otp:{phone}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        sms = sms_service.resolve_sms(overlay)
        try:
            await sms_service.send_otp(
                provider=sms["provider"],
                api_key=sms["api_key"],
                template_id=sms["template_id"],
                token_name=sms["token_name"],
                phone=phone,
                code=code,
            )
        except ValueError as exc:
            await redis_client.delete(f"otp:{phone}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except Exception as exc:
            await redis_client.delete(f"otp:{phone}")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ارسال پیامک به درگاه نرسید.") from exc
        return payload

    async def verify_otp(self, phone_raw: str, code: str) -> dict:
        try:
            phone = normalize_phone(phone_raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        stored = await redis_client.get(f"otp:{phone}")
        if stored is None or stored != code.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "کد یک‌بارمصرف نادرست است")
        await redis_client.delete(f"otp:{phone}")
        user = await self.users.get_by_phone(phone)
        existed = user is not None
        if user is None:
            user = await self.users.create(phone=phone, role="admin")
        from app.services import profile_service

        profile = profile_service.touch(phone, existed=existed)
        token = encode_token(user.id, user.role)
        return {
            "access_token": token,
            "token_type": "bearer",
            "onboarded": bool(profile.get("onboarded")),
        }
