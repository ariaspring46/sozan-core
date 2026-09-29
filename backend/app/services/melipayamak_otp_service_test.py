from __future__ import annotations

import asyncio
import logging
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.config import settings
from app.services import auth_service, melipayamak_otp_service
from app.services.auth_service import AuthService
from app.services.auth_service_test import _FakeRedis, _Users


class MelipayamakAdapterTests(unittest.TestCase):
    """قرارداد تازه: SendByBaseNumber2؛ کد خود ما در {0} قالب تأییدشده."""

    def setUp(self) -> None:
        emit_patcher = patch.object(melipayamak_otp_service, "emit_later")
        self.emit = emit_patcher.start()
        self.addCleanup(emit_patcher.stop)
        for key, value in (
            ("melipayamak_username", "panel-user"),
            ("melipayamak_otp_apikey", "SECRET-KEY-123"),
            ("melipayamak_body_id", "547036"),
            ("melipayamak_pattern_base", "https://api.payamak-panel.com/post/send.asmx"),
        ):
            patcher = patch.object(settings, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _client(self, text: str, http_status: int = 200):
        class Resp:
            status_code = http_status

            def __str__(self):
                return text

            @property
            def text(self):
                return text

        class Client:
            seen_url = ""
            seen_body = {}

            def __init__(self, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                Client.seen_url = url
                Client.seen_body = json
                return Resp()

        return Client

    def test_success_sends_own_code_and_credentials(self) -> None:
        client = self._client('"179070000000000001"')
        with patch.object(melipayamak_otp_service.httpx, "AsyncClient", client):
            out = asyncio.run(melipayamak_otp_service.send_otp("09111111111", "456789"))
        self.assertEqual(out, "179070000000000001")
        self.assertTrue(client.seen_url.endswith("/SendByBaseNumber2"))
        self.assertEqual(client.seen_body.get("username"), "panel-user")
        self.assertEqual(client.seen_body.get("password"), "SECRET-KEY-123")
        self.assertEqual(client.seen_body.get("bodyId"), "547036")
        self.assertEqual(client.seen_body.get("text"), "456789")
        self.assertEqual(client.seen_body.get("to"), "09111111111")

    def test_error_code_maps_and_emits_without_phone(self) -> None:
        client = self._client("18")
        with patch.object(melipayamak_otp_service.httpx, "AsyncClient", client):
            with self.assertRaises(melipayamak_otp_service.OtpSendError) as ctx:
                asyncio.run(melipayamak_otp_service.send_otp("09111111111", "456789"))
        self.assertEqual(ctx.exception.error_class, "bad-number")
        self.assertEqual(ctx.exception.return_code, "18")
        self.emit.assert_called_once()
        payload = self.emit.call_args.kwargs.get("payload") or {}
        self.assertEqual(payload.get("returnCode"), "18")
        self.assertNotIn("09111111111", str(self.emit.call_args))

    def test_credit_code_maps(self) -> None:
        client = self._client("2")
        with patch.object(melipayamak_otp_service.httpx, "AsyncClient", client):
            with self.assertRaises(melipayamak_otp_service.OtpSendError) as ctx:
                asyncio.run(melipayamak_otp_service.send_otp("09111111111", "456789"))
        self.assertEqual(ctx.exception.error_class, "credit")

    def test_missing_credentials_raise_config(self) -> None:
        with patch.object(settings, "melipayamak_username", ""):
            with self.assertRaises(melipayamak_otp_service.OtpSendError):
                asyncio.run(melipayamak_otp_service.send_otp("09111111111", "456789"))

    def test_url_never_appears_in_logs(self) -> None:
        records: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logger = logging.getLogger("sozan.sms")
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        class Boom:
            def __init__(self, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                raise RuntimeError("boom")

        with patch.object(melipayamak_otp_service.httpx, "AsyncClient", Boom):
            with self.assertRaises(melipayamak_otp_service.OtpSendError):
                asyncio.run(melipayamak_otp_service.send_otp("09111111111", "456789"))
        for line in records:
            self.assertNotIn("SECRET-KEY-123", line)
            self.assertNotIn("panel-user", line)


class MelipayamakFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.svc = AuthService(_Users())
        self.patches = [
            patch.object(auth_service, "redis_client", self.redis),
            patch.object(settings, "otp_provider", "melipayamak_otp"),
            patch.object(settings, "melipayamak_otp_apikey", "SECRET-KEY-123"),
            patch.object(settings, "otp_dev", False),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _mock_provider_code(self, code: str):
        async def fake(phone: str, otp_code: str) -> str:
            return code

        return patch.object(melipayamak_otp_service, "send_otp", new=fake)

    def _mock_provider_echo(self):
        async def echo(phone: str, otp_code: str) -> str:
            return otp_code

        return patch.object(melipayamak_otp_service, "send_otp", new=echo)

    def test_send_stores_hash_not_plaintext(self) -> None:
        with self._mock_provider_code("443322"):
            out = asyncio.run(self.svc.send_otp("09111234567", ip="10.1.1.5"))
        self.assertEqual(out, {"ok": True})
        stored = self.redis.store["otp:09111234567"]
        self.assertTrue(stored.startswith("sha256:"))
        self.assertNotIn("443322", stored)
        self.assertGreater(self.redis.ttls["otp:09111234567"], 0)
        self.assertLessEqual(self.redis.ttls["otp:09111234567"], auth_service.OTP_MELIPAYAMAK_TTL)
        self.assertEqual(self.redis.ttls["otp:cool:09111234567"], 60)

    def test_resend_within_cooldown_is_throttled(self) -> None:
        with self._mock_provider_code("111111"):
            asyncio.run(self.svc.send_otp("09111234567", ip="10.1.1.5"))
        with self._mock_provider_code("111111"):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.svc.send_otp("09111234567", ip="10.1.1.5"))
        self.assertEqual(ctx.exception.status_code, 429)

    def test_hourly_cap_per_phone_and_ip(self) -> None:
        for i in range(auth_service.OTP_MELIPAYAMAK_HOURLY):
            asyncio.run(self.redis.delete(f"otp:cool:0911123456{i}"))
            with self._mock_provider_code("111111"):
                asyncio.run(self.svc.send_otp(f"0911123456{i}", ip="10.1.1.9"))
        with self._mock_provider_code("111111"):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.svc.send_otp("09119999999", ip="10.1.1.9"))
        self.assertEqual(ctx.exception.status_code, 429)
        # شمارهٔ تازه از همان IP هم سقف IP را می‌خورد؛ IP دیگر نه
        with self._mock_provider_code("111111"):
            asyncio.run(self.svc.send_otp("09118888888", ip="10.2.2.8"))

    def test_verify_accepts_right_code_and_rejects_five_wrong(self) -> None:
        # echo یعنی کدِ دریافتی provider همان کدِ ساختهٔ ما است (رفتار واقعی).
        code_holder: dict = {}

        async def capture(phone: str, otp_code: str) -> str:
            code_holder["code"] = otp_code
            return "179070000000000001"

        with patch.object(melipayamak_otp_service, "send_otp", new=capture):
            asyncio.run(self.svc.send_otp("09111234567", ip="10.1.1.5"))
        out = asyncio.run(self.svc.verify_otp("09111234567", code_holder["code"]))
        self.assertIn("otp:rec:09111234567", self.redis.store)  # recId ذخیره شد
        self.assertIn("access_token", out)
        self.assertNotIn("otp:09111234567", self.redis.store)

        asyncio.run(self.redis.delete("otp:cool:09111234567"))
        asyncio.run(self.redis.setex("captcha:tok9", 300, "7"))
        with self._mock_provider_code("654321"):
            asyncio.run(self.svc.send_otp("09111234567", ip="10.1.1.5", captcha_token="tok9", captcha_answer="7"))
        for _ in range(auth_service.OTP_WRONG_ATTEMPTS):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.svc.verify_otp("09111234567", "000000"))
            self.assertEqual(ctx.exception.status_code, 400)
        self.assertNotIn("otp:09111234567", self.redis.store)
        asyncio.run(self.redis.delete("otp:cool:09111234567"))
        asyncio.run(self.redis.setex("captcha:tok10", 300, "3"))
        with self._mock_provider_code("654321"):
            asyncio.run(
                self.svc.send_otp("09111234567", ip="10.1.1.5", captcha_token="tok10", captcha_answer="3")
            )
        with self.assertRaises(HTTPException):
            asyncio.run(self.svc.verify_otp("09111234567", "654321"))

    def test_provider_failure_maps_to_friendly_error(self) -> None:
        async def boom(phone: str, otp_code: str) -> str:
            raise melipayamak_otp_service.OtpSendError("credit-or-key")

        with patch.object(melipayamak_otp_service, "send_otp", new=boom):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(self.svc.send_otp("09111234567", ip="10.1.1.5"))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("ارسال کد ناموفق بود", str(ctx.exception.detail))

    def test_lab_phone_still_skips_provider(self) -> None:
        called = {"n": 0}

        async def spy(phone: str) -> str:
            called["n"] += 1
            return "123456"

        with patch.object(melipayamak_otp_service, "send_otp", new=spy):
            out = asyncio.run(self.svc.send_otp("09120000991", ip="10.1.1.5"))
        self.assertEqual(out, {"ok": True})
        self.assertEqual(called["n"], 0)


if __name__ == "__main__":
    unittest.main()
