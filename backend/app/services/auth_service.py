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
OTP_CAPTCHA_AFTER = 2
# شماره‌های ساختگی تست ساخت سایت — در پنجرهٔ تست، پیامک واقعی برایشان نمی‌رود.
_TEST_WINDOW_SKIP_SMS = frozenset({
    "09120000991", "09120000992", "09120000993",
    "09130000001", "09130000002", "09130000003",
    "09129900001", "09129900002", "09129900003",
    "09199990001", "09199990002", "09199990003",
    "09135409482",
})


def _overlay_without_side_effects(phone: str) -> dict:
    """تنظیمات فروشنده را بدون ساختن پوشهٔ tenant بخوان؛ ارسال کد حسابی نمی‌سازد."""
    import json

    from app.config import settings as env

    path = env.state_path / "tenants" / phone / "settings.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def otp_test_window_open() -> bool:
    """پنجرهٔ موقت تست ساخت سایت: تا تاریخ مشخص، کد در پاسخ ارسال برمی‌گردد."""
    import datetime as _dt

    raw = str(settings.otp_test_until or "").strip()
    if not raw:
        return False
    try:
        until = _dt.date.fromisoformat(raw)
    except ValueError:
        return False
    return _dt.date.today() <= until


def _hash_otp(phone: str, code: str) -> str:
    key = f"{settings.jwt_secret}:{phone}".encode("utf-8")
    return "sha256:" + hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()


def fixed_otp_for(phone: str) -> str | None:
    return settings.otp_fixed_map.get(phone)


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    async def send_otp(self, phone_raw: str, *, ip: str = "", captcha_token: str = "", captcha_answer: str = "") -> dict:
        try:
            phone = normalize_phone(phone_raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        from app.lab_account import is_lab_phone

        if is_lab_phone(phone):
            return {"ok": True}
        await self._check_send_caps(phone, ip=ip)
        await self._check_captcha(phone, token=captcha_token, answer=captcha_answer)
        if str(settings.otp_provider or "").strip().lower() == "melipayamak_otp":
            return await self._send_melipayamak_otp(phone, ip=ip)
        overlay = _overlay_without_side_effects(phone)
        mock_sms = overlay.get("mockSms")
        if settings.payments_enabled:
            # در production کد آزمایشی وجود ندارد، هر تنظیمی فروشنده گذاشته باشد.
            mock_sms = False
        elif mock_sms is None:
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
        if otp_test_window_open():
            # پنجرهٔ تست ساخت سایت: کد در پاسخ می‌آید؛ پیامک واقعی هم می‌رود.
            payload["code"] = code
            from app.services.observe_client import emit_later

            emit_later(
                kind="sms",
                title="otp-test-reveal",
                surface="auth",
                status="ok",
                payload={"path": "login"},
            )
            return payload
        # پیامک ورود هزینه و کلید خود سوزان است؛ نه کیف پول فروشنده، نه درگاه شخصی او.
        async def drop_fresh_code() -> None:
            if not reused:
                await redis_client.delete(f"otp:{phone}")

        sms = sms_service.resolve_sms({})
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
            await drop_fresh_code()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except Exception as exc:
            await drop_fresh_code()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ارسال پیامک به درگاه نرسید.") from exc
        return payload

    async def _check_captcha(self, phone: str, *, token: str, answer: str) -> None:
        """بعد از دو ارسال در روز، کد ورود پاسخ کپچای ساده می‌خواهد."""
        sends = await redis_client.incr(f"otp:cs:{phone}")
        if sends == 1:
            await redis_client.expire(f"otp:cs:{phone}", 86400)
        if sends <= OTP_CAPTCHA_AFTER:
            return
        key = f"captcha:{str(token or '').strip()}"
        stored = await redis_client.get(key)
        from app.phone import normalize_digits

        given = "".join(ch for ch in normalize_digits(str(answer or "")) if ch.isdigit())
        if not stored or not given or not hmac.compare_digest(str(stored), given):
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "پاسخ پرسش امنیتی لازم است")
        await redis_client.delete(key)

    async def _check_send_caps(self, phone: str, *, ip: str = "") -> None:
        """سقف IP در ساعت و کل ارسال‌های روز، برای هر دو درگاه کد ورود."""
        hits = await redis_client.incr(f"otp:hip:{ip or 'no-ip'}")
        if hits == 1:
            await redis_client.expire(f"otp:hip:{ip or 'no-ip'}", 3600)
        if hits > OTP_MELIPAYAMAK_HOURLY:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "تعداد درخواست بیش از حد است")
        import time as _time

        day = _time.strftime("%Y-%m-%d", _time.gmtime())
        day_key = f"otp:daily:{day}"
        total = await redis_client.incr(day_key)
        if total == 1:
            await redis_client.expire(day_key, 90000)
        if total > int(settings.otp_global_daily_cap or 500):
            from app.services.observe_client import emit_later

            emit_later(
                kind="sms",
                title="otp-daily-cap",
                surface="auth",
                status="error",
                payload={"day": day},
            )
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "ظرفیت کد امروز پر است")

    async def _send_melipayamak_otp(self, phone: str, *, ip: str = "") -> dict:
        """کد ۶رقمی خود ما در قالب تأییدشده ملی‌پیامک می‌رود؛ هشِ آن دو دقیقه می‌ماند."""
        from app.services import melipayamak_otp_service

        if int(await redis_client.ttl(f"otp:cool:{phone}")) > 0:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "کد قبلی هنوز تازه است؛ کمی بعد دوباره تلاش کن")
        hits = await redis_client.incr(f"otp:hphone:{phone}")
        if hits == 1:
            await redis_client.expire(f"otp:hphone:{phone}", 3600)
        if hits > OTP_MELIPAYAMAK_HOURLY:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "تعداد درخواست کد بیش از حد است؛ بعداً تلاش کن")
        code = f"{secrets.randbelow(1_000_000):06d}"
        # پنجرهٔ تست ساخت سایت: کد در پاسخ برمی‌گردد و برای شمارهٔ ساختگیِ تست،
        # پیامک واقعی هم فرستاده نمی‌شود (شمارهٔ واقعی هم‌چنان SMS می‌گیرد).
        test_window = otp_test_window_open()
        test_phone = test_window and phone in _TEST_WINDOW_SKIP_SMS
        rec_id = ""
        if not test_phone:
            try:
                rec_id = await melipayamak_otp_service.send_otp(phone, code)
            except melipayamak_otp_service.OtpSendError:
                if not test_window:
                    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ارسال کد ناموفق بود، دوباره تلاش کنید") from None
        await redis_client.setex(f"otp:{phone}", OTP_MELIPAYAMAK_TTL, _hash_otp(phone, code))
        await redis_client.setex(f"otp:cool:{phone}", OTP_MELIPAYAMAK_COOLDOWN, "1")
        if rec_id:
            await redis_client.setex(f"otp:rec:{phone}", OTP_MELIPAYAMAK_TTL, str(rec_id))
        await redis_client.delete(f"otp:wa:{phone}")
        payload = {"ok": True}
        if test_window:
            payload["code"] = code
            from app.services.observe_client import emit_later

            emit_later(
                kind="sms",
                title="otp-test-reveal",
                surface="auth",
                status="ok",
                payload={"path": "login", "skipSms": test_phone},
            )
        return payload

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
