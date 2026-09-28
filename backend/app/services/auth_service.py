from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, status

from app.config import settings
from app.phone import normalize_digits, normalize_phone
from app.redis_client import redis_client
from app.repositories.user_repository import UserRepository
from app.security import encode_token
from app.services import sms_service
from app.services.settings_service import get_settings
from app.state_store import tenant_scope

# Resend keeps the same code while at least this many seconds remain on it.
OTP_REUSE_MIN_TTL = 60
OTP_SEND_LIMIT = 5
OTP_SEND_WINDOW = 900
OTP_VERIFY_LIMIT = 5
OTP_VERIFY_WINDOW = 300
# Melipayamak console OTP: the provider's own code lives hashed, 2 minutes only.
OTP_MELIPAYAMAK_TTL = 120
OTP_MELIPAYAMAK_COOLDOWN = 60
OTP_MELIPAYAMAK_HOURLY = 5
OTP_WRONG_ATTEMPTS = 5


def _hash_otp(phone: str, code: str) -> str:
    key = f"{settings.jwt_secret}:{phone}".encode("utf-8")
    return "sha256:" + hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()


def fixed_otp_for(phone: str) -> str | None:
    return settings.otp_fixed_map.get(phone)


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    async def send_otp(self, phone_raw: str, *, ip: str = "") -> dict:
        try:
            phone = normalize_phone(phone_raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        from app.lab_account import is_lab_phone

        if is_lab_phone(phone):
            return {"ok": True}
        if str(settings.otp_provider or "").strip().lower() == "melipayamak_otp":
            return await self._send_melipayamak_otp(phone, ip=ip)
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
            await redis_client.expire(rl_key, OTP_SEND_WINDOW)
        if hits > OTP_SEND_LIMIT:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "تعداد درخواست بیش از حد است")
        ttl = int(overlay.get("otpTtlSeconds") or settings.otp_ttl_seconds)
        fixed = fixed_otp_for(phone)
        if fixed:
            await redis_client.setex(f"otp:{phone}", ttl, fixed)
            payload = {"ok": True}
            if mock_sms:
                payload["dev_code"] = fixed
            return payload
        code, reused = await self._current_or_new_code(phone, ttl)
        if not reused:
            await redis_client.setex(f"otp:{phone}", ttl, code)
        payload = {"ok": True}
        if mock_sms:
            payload["dev_code"] = code
            return payload
        from app.services import wallet_service

        async def drop_fresh_code() -> None:
            # A reused code may already be in an SMS on its way; only a brand-new one is dropped.
            if not reused:
                await redis_client.delete(f"otp:{phone}")

        charged = 0
        try:
            with tenant_scope(phone):
                consumed = wallet_service.consume_sms()
                charged = int(consumed.get("charged") or 0)
        except ValueError as exc:
            await drop_fresh_code()
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
            with tenant_scope(phone):
                wallet_service.refund_sms(charged)
            await drop_fresh_code()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except Exception as exc:
            with tenant_scope(phone):
                wallet_service.refund_sms(charged)
            await drop_fresh_code()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ارسال پیامک به درگاه نرسید.") from exc
        return payload

    async def _send_melipayamak_otp(self, phone: str, *, ip: str = "") -> dict:
        """کد را خود ملی‌پیک می‌سازد؛ ما فقط هش آن را دو دقیقه نگه می‌داریم."""
        from app.services import melipayamak_otp_service

        if int(await redis_client.ttl(f"otp:cool:{phone}")) > 0:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "کد قبلی هنوز تازه است؛ کمی بعد دوباره تلاش کن")
        for key in (f"otp:hphone:{phone}", f"otp:hip:{ip or 'no-ip'}"):
            hits = await redis_client.incr(key)
            if hits == 1:
                await redis_client.expire(key, 3600)
            if hits > OTP_MELIPAYAMAK_HOURLY:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "تعداد درخواست کد بیش از حد است؛ بعداً تلاش کن")
        try:
            code = await melipayamak_otp_service.send_otp(phone)
        except melipayamak_otp_service.OtpSendError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ارسال کد ناموفق بود، دوباره تلاش کنید") from None
        await redis_client.setex(f"otp:{phone}", OTP_MELIPAYAMAK_TTL, _hash_otp(phone, code))
        await redis_client.setex(f"otp:cool:{phone}", OTP_MELIPAYAMAK_COOLDOWN, "1")
        await redis_client.delete(f"otp:wa:{phone}")
        return {"ok": True}

    async def _current_or_new_code(self, phone: str, ttl: int) -> tuple[str, bool]:
        """Reuse the live code on resend so a late-arriving SMS still verifies.

        A fresh code is issued only when none exists or the old one is about to
        expire (less than OTP_REUSE_MIN_TTL seconds left)."""
        key = f"otp:{phone}"
        try:
            stored = await redis_client.get(key)
            left = int(await redis_client.ttl(key)) if stored else -1
        except Exception:
            stored, left = None, -1
        if stored and left >= OTP_REUSE_MIN_TTL:
            return str(stored), True
        return f"{secrets.randbelow(1_000_000):06d}", False

    async def verify_otp(self, phone_raw: str, code: str) -> dict:
        try:
            phone = normalize_phone(phone_raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        vl_key = f"otp:vl:{phone}"
        hits = await redis_client.incr(vl_key)
        if hits == 1:
            await redis_client.expire(vl_key, OTP_VERIFY_WINDOW)
        if hits > OTP_VERIFY_LIMIT:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "تعداد تلاش بیش از حد است")
        stored = await redis_client.get(f"otp:{phone}")
        given = re.sub(r"\D", "", normalize_digits(code))
        fixed = fixed_otp_for(phone)
        hashed = str(stored or "").startswith("sha256:")
        matched = bool(given) and (
            (fixed is not None and hmac.compare_digest(fixed, given))
            or (
                stored is not None
                and (
                    hmac.compare_digest(str(stored), _hash_otp(phone, given))
                    if hashed
                    else hmac.compare_digest(str(stored), given)
                )
            )
        )
        if not matched:
            if hashed:
                wrong = await redis_client.incr(f"otp:wa:{phone}")
                if wrong == 1:
                    await redis_client.expire(f"otp:wa:{phone}", OTP_MELIPAYAMAK_TTL)
                if wrong >= OTP_WRONG_ATTEMPTS:
                    await redis_client.delete(f"otp:{phone}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "کد یک‌بارمصرف نادرست است")
        await redis_client.delete(f"otp:{phone}")
        await redis_client.delete(vl_key)
        await redis_client.delete(f"otp:wa:{phone}")
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
