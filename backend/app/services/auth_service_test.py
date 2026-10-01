from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.services import auth_service
from app.services.auth_service import AuthService


class _FakeRedis:
    """Minimal async Redis: get/setex/ttl/delete/incr/expire with fixed TTL bookkeeping."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.ttls[key] = ttl

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        self.counters.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl


class _Users:
    def __init__(self) -> None:
        self.user = None

    async def get_by_phone(self, phone: str):
        return self.user

    async def create(self, *, phone: str, role: str):
        self.user = type("U", (), {"id": 7, "role": role, "phone": phone})()
        return self.user


class OtpResendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.svc = AuthService(_Users())
        self.patches = [
            patch.object(auth_service, "redis_client", self.redis),
            patch.object(auth_service, "_overlay_without_side_effects", return_value={"mockSms": True}),
            # این کلاس درگاه همیشگی را می‌سنجد؛ محیط ممکن است ملی‌پیامک را روشن کرده باشد.
            patch.object(auth_service.settings, "otp_provider", ""),
            patch.object(auth_service.settings, "payments_enabled", False),
            # env هاب پنجرهٔ تست و کلید پیامک واقعی دارد؛ این کلاس مسیر شکست را می‌سنجد.
            patch.object(auth_service.settings, "otp_test_until", ""),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def test_resend_within_ttl_reuses_same_code(self) -> None:
        first = asyncio.run(self.svc.send_otp("09111234567"))["dev_code"]
        self.redis.ttls["otp:09111234567"] = 200
        second = asyncio.run(self.svc.send_otp("09111234567"))["dev_code"]
        self.assertEqual(first, second)

    def test_resend_near_expiry_issues_fresh_code(self) -> None:
        first = asyncio.run(self.svc.send_otp("09111234567"))["dev_code"]
        self.redis.ttls["otp:09111234567"] = auth_service.OTP_REUSE_MIN_TTL - 1
        with patch.object(auth_service.secrets, "randbelow", return_value=int(first) + 1 if first != "999999" else 0):
            second = asyncio.run(self.svc.send_otp("09111234567"))["dev_code"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.redis.store["otp:09111234567"], second)

    def test_verify_accepts_persian_digits_and_spaces(self) -> None:
        self.redis.store["otp:09111234567"] = "123456"
        self.redis.ttls["otp:09111234567"] = 100
        with patch("app.services.profile_service.touch", return_value={}), patch.object(
            auth_service, "encode_token", return_value="jwt"
        ):
            out = asyncio.run(self.svc.verify_otp("09111234567", " ۱۲۳ ۴۵۶ "))
        self.assertEqual(out.get("token") or out.get("access_token") or "jwt", "jwt")
        self.assertNotIn("otp:09111234567", self.redis.store)

    def test_verify_rejects_wrong_or_empty_code(self) -> None:
        self.redis.store["otp:09111234567"] = "123456"
        with self.assertRaises(HTTPException):
            asyncio.run(self.svc.verify_otp("09111234567", "654321"))
        with self.assertRaises(HTTPException):
            asyncio.run(self.svc.verify_otp("09111234567", ""))

    def test_failed_resend_keeps_reused_code(self) -> None:
        first = asyncio.run(self.svc.send_otp("09111234567"))["dev_code"]
        self.redis.ttls["otp:09111234567"] = 200
        with patch.object(auth_service, "_overlay_without_side_effects", return_value={"mockSms": False}), patch(
            "app.services.wallet_service.consume_sms"
        ), patch.object(auth_service.sms_service, "resolve_sms", return_value={"provider": "smsir", "api_key": "k", "template_id": "1", "token_name": "code"}), patch.object(
            auth_service.sms_service, "send_otp", new=AsyncMock(side_effect=RuntimeError("gateway"))
        ):
            with self.assertRaises(HTTPException):
                asyncio.run(self.svc.send_otp("09111234567"))
        self.assertEqual(self.redis.store.get("otp:09111234567"), first)

    def test_verify_blocks_after_five_failures(self) -> None:
        self.redis.store["otp:09111234567"] = "123456"
        for _ in range(5):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.svc.verify_otp("09111234567", "000000"))
            self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.svc.verify_otp("09111234567", "123456"))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(self.redis.store.get("otp:09111234567"), "123456")

    def test_verify_success_clears_attempt_counter(self) -> None:
        self.redis.store["otp:09111234567"] = "123456"
        with self.assertRaises(HTTPException):
            asyncio.run(self.svc.verify_otp("09111234567", "000000"))
        with patch("app.services.profile_service.touch", return_value={}), patch.object(
            auth_service, "encode_token", return_value="jwt"
        ):
            asyncio.run(self.svc.verify_otp("09111234567", "123456"))
        self.assertNotIn("otp:vl:09111234567", self.redis.counters)

    def test_failed_send_touches_neither_wallet_nor_seller_gateway(self) -> None:
        with patch.object(
            auth_service, "_overlay_without_side_effects", return_value={"mockSms": False}
        ), patch("app.services.wallet_service.consume_sms") as consume, patch(
            "app.services.wallet_service.refund_sms"
        ) as refund, patch.object(
            auth_service.sms_service, "resolve_sms", return_value={"provider": "smsir", "api_key": "k", "template_id": "1", "token_name": "code"}
        ) as resolve, patch.object(
            auth_service.sms_service, "send_otp", new=AsyncMock(side_effect=RuntimeError("gateway"))
        ):
            with self.assertRaises(HTTPException):
                asyncio.run(self.svc.send_otp("09111234567"))
        consume.assert_not_called()
        refund.assert_not_called()
        # درگاه پیامک ورود، تنظیمات فروشنده نیست؛ همیشه درگاه خود سوزان.
        self.assertEqual(resolve.call_args.args[0], {})
        self.assertNotIn("otp:09111234567", self.redis.store)




class OtpTestWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.svc = AuthService(_Users())
        self.patches = [
            patch.object(auth_service, "redis_client", self.redis),
            patch.object(auth_service, "_overlay_without_side_effects", return_value={"mockSms": False}),
            patch.object(auth_service.settings, "otp_provider", ""),
            patch.object(auth_service.settings, "payments_enabled", False),
            # env هاب پنجرهٔ تست و کلید پیامک واقعی دارد؛ این کلاس مسیر شکست را می‌سنجد.
            patch.object(auth_service.settings, "otp_test_until", ""),
            patch.object(auth_service.sms_service, "send_otp", new=AsyncMock()),
            patch.object(auth_service.sms_service, "resolve_sms", return_value={"provider": "smsir", "api_key": "k", "template_id": "1", "token_name": "code"}),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_window_open_returns_code_for_test_phone_only(self) -> None:
        with patch.object(auth_service.settings, "otp_test_until", "2030-12-31"):
            out = asyncio.run(self.svc.send_otp("09130000001"))
        self.assertTrue(out.get("code"), "a fake test phone gets the code")

    def test_window_never_reveals_code_for_real_phone(self) -> None:
        with patch.object(auth_service.settings, "otp_test_until", "2030-12-31"):
            out = asyncio.run(self.svc.send_otp("09111234567"))
        self.assertNotIn("code", out)

    def test_window_never_reveals_code_for_hub_admin(self) -> None:
        with patch.object(auth_service.settings, "otp_test_until", "2030-12-31"), patch.object(
            auth_service.settings, "admin_phone", "09130000002"
        ):
            out = asyncio.run(self.svc.send_otp("09130000002"))
        self.assertNotIn("code", out)

    def test_extra_test_phone_from_env(self) -> None:
        with patch.object(auth_service.settings, "otp_test_until", "2030-12-31"), patch.object(
            auth_service.settings, "otp_test_phones", "09191112222"
        ):
            out = asyncio.run(self.svc.send_otp("09191112222"))
        self.assertTrue(out.get("code"))

    def test_window_closed_hides_code(self) -> None:
        with patch.object(auth_service.settings, "otp_test_until", ""):
            out = asyncio.run(self.svc.send_otp("09111234567"))
        self.assertNotIn("code", out)


class OtpCaptchaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.svc = AuthService(_Users())
        self.patches = [
            patch.object(auth_service, "redis_client", self.redis),
            patch.object(auth_service, "_overlay_without_side_effects", return_value={"mockSms": True}),
            patch.object(auth_service.settings, "otp_provider", ""),
            patch.object(auth_service.settings, "payments_enabled", False),
            # env هاب پنجرهٔ تست و کلید پیامک واقعی دارد؛ این کلاس مسیر شکست را می‌سنجد.
            patch.object(auth_service.settings, "otp_test_until", ""),
            patch.object(auth_service.settings, "otp_dev", True),
            patch.object(auth_service.settings, "payments_enabled", False),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_third_send_requires_captcha(self) -> None:
        asyncio.run(self.redis.setex("captcha:tok1", 300, "9"))
        asyncio.run(self.svc.send_otp("09111234567"))  # ۱
        asyncio.run(self.svc.send_otp("09111234567"))  # ۲
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.svc.send_otp("09111234567", captcha_token="tok1", captcha_answer="8"))
        self.assertEqual(ctx.exception.status_code, 428)
        asyncio.run(self.svc.send_otp("09111234567", captcha_token="tok1", captcha_answer="9"))
        self.assertNotIn("captcha:tok1", self.redis.store)


class FactoryEnvTests(unittest.TestCase):
    def test_factory_env_whitelist_hides_secrets(self) -> None:
        from app.services import shop_service

        with patch.dict(
            "os.environ",
            {"JWT_SECRET": "x" * 40, "PATH": "/usr/bin", "SOZAN_KEEP": "1", "OPEN_ROUT_API_TOKEN": "leak"},
        ):
            env = shop_service._factory_env()
        self.assertNotIn("JWT_SECRET", env)
        self.assertNotIn("OPEN_ROUT_API_TOKEN", env)
        self.assertEqual(env["SOZAN_KEEP"], "1")
        self.assertEqual(env["PATH"], "/usr/bin")


class SecurityGuardTests(unittest.TestCase):
    def test_default_secret_rejected(self) -> None:
        from app import main as app_main

        with patch.object(app_main.settings, "jwt_secret", "change-me-to-a-long-random-secret"):
            with self.assertRaises(RuntimeError):
                app_main._security_guard()

    def test_short_secret_rejected(self) -> None:
        from app import main as app_main

        with patch.object(app_main.settings, "jwt_secret", "short"), patch.object(
            app_main.settings, "otp_dev", False
        ):
            with self.assertRaises(RuntimeError):
                app_main._security_guard()

    def test_otp_dev_with_payments_rejected(self) -> None:
        from app import main as app_main

        with patch.object(app_main.settings, "jwt_secret", "k" * 40), patch.object(
            app_main.settings, "otp_dev", True
        ), patch.object(app_main.settings, "payments_enabled", True):
            with self.assertRaises(RuntimeError):
                app_main._security_guard()


class SendCapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.svc = AuthService(_Users())
        self.patches = [
            patch.object(auth_service, "redis_client", self.redis),
            patch.object(auth_service, "_overlay_without_side_effects", return_value={"mockSms": True}),
            patch.object(auth_service.settings, "otp_provider", ""),
            patch.object(auth_service.settings, "payments_enabled", False),
            # env هاب پنجرهٔ تست و کلید پیامک واقعی دارد؛ این کلاس مسیر شکست را می‌سنجد.
            patch.object(auth_service.settings, "otp_test_until", ""),
            patch.object(auth_service.settings, "otp_dev", True),
            patch.object(auth_service.settings, "payments_enabled", False),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_ip_hourly_cap(self) -> None:
        for i in range(auth_service.OTP_MELIPAYAMAK_HOURLY):
            asyncio.run(self.svc.send_otp(f"0911123456{i}", ip="10.9.9.9"))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.svc.send_otp("09119999999", ip="10.9.9.9"))
        self.assertEqual(ctx.exception.status_code, 429)
        asyncio.run(self.svc.send_otp("09118888888", ip="10.8.8.8"))

    def test_global_daily_cap(self) -> None:
        with patch.object(auth_service.settings, "otp_global_daily_cap", 2):
            asyncio.run(self.svc.send_otp("09111111111", ip="1.1.1.1"))
            asyncio.run(self.svc.send_otp("09112222222", ip="2.2.2.2"))
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.svc.send_otp("09113333333", ip="3.3.3.3"))
        self.assertEqual(ctx.exception.status_code, 429)

    def test_send_does_not_create_tenant_folder(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw, patch.object(auth_service.settings, "state_dir", raw):
            asyncio.run(self.svc.send_otp("09111234599"))
            self.assertFalse((Path(raw) / "tenants" / "09111234599").exists())


class FixedOtpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.svc = AuthService(_Users())
        self.patches = [
            patch.object(auth_service, "redis_client", self.redis),
            patch.object(auth_service, "_overlay_without_side_effects", return_value={"mockSms": False, "otpTtlSeconds": 300}),
            patch.object(auth_service, "fixed_otp_for", side_effect=lambda phone: "100001" if phone == "09129900001" else None),
            patch.object(auth_service.settings, "otp_provider", ""),
            patch.object(auth_service.settings, "payments_enabled", False),
            # env هاب پنجرهٔ تست و کلید پیامک واقعی دارد؛ این کلاس مسیر شکست را می‌سنجد.
            patch.object(auth_service.settings, "otp_test_until", ""),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def test_lab_phone_does_not_send_sms(self) -> None:
        with patch.object(auth_service.sms_service, "send_otp", new=AsyncMock()) as send:
            out = asyncio.run(self.svc.send_otp("09120000991"))
        send.assert_not_called()
        self.assertEqual(out, {"ok": True})
        self.assertNotIn("otp:09120000991", self.redis.store)

    def test_send_uses_fixed_code_and_skips_sms(self) -> None:
        with patch.object(auth_service.sms_service, "send_otp", new=AsyncMock()) as send:
            out = asyncio.run(self.svc.send_otp("09129900001"))
        send.assert_not_called()
        self.assertEqual(out, {"ok": True})
        self.assertEqual(self.redis.store["otp:09129900001"], "100001")

    def test_send_then_verify_uses_redis_like_normal(self) -> None:
        asyncio.run(self.svc.send_otp("09129900001"))
        self.assertEqual(self.redis.store["otp:09129900001"], "100001")
        with patch("app.services.profile_service.touch", return_value={}), patch.object(
            auth_service, "encode_token", return_value="jwt"
        ):
            out = asyncio.run(self.svc.verify_otp("09129900001", "100001"))
        self.assertEqual(out["access_token"], "jwt")
        self.assertNotIn("otp:09129900001", self.redis.store)

    def test_send_does_not_charge_wallet(self) -> None:
        with patch("app.services.wallet_service.consume_sms") as consume:
            asyncio.run(self.svc.send_otp("09129900001"))
        consume.assert_not_called()

    def test_verify_accepts_fixed_code_without_send(self) -> None:
        with patch("app.services.profile_service.touch", return_value={}), patch.object(
            auth_service, "encode_token", return_value="jwt"
        ):
            out = asyncio.run(self.svc.verify_otp("09129900001", "100001"))
        self.assertEqual(out["access_token"], "jwt")

    def test_verify_rejects_wrong_fixed_code(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.svc.verify_otp("09129900001", "000000"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_other_numbers_are_not_fixed(self) -> None:
        with patch.object(auth_service.sms_service, "send_otp", new=AsyncMock()), patch(
            "app.services.wallet_service.consume_sms", return_value={"charged": 0}
        ), patch.object(
            auth_service.sms_service,
            "resolve_sms",
            return_value={"provider": "smsir", "api_key": "k", "template_id": "1", "token_name": "code"},
        ):
            out = asyncio.run(self.svc.send_otp("09111234567"))
        self.assertTrue(out.get("ok"))
        self.assertNotEqual(self.redis.store.get("otp:09111234567"), "100001")


if __name__ == "__main__":
    unittest.main()
