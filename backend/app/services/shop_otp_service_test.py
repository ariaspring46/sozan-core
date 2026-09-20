from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import shop_otp_service
from app.services.auth_service import OTP_SEND_LIMIT, OTP_VERIFY_LIMIT
from app.state_store import tenant_scope


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.ttls[key] = ttl

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        self.counters.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl


class ShopOtpHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.patches = [
            patch.object(shop_otp_service, "redis_client", self.redis),
            patch.object(shop_otp_service, "find_tenant_by_slug", return_value="09135409482"),
            patch.object(shop_otp_service, "get_settings", return_value={"mockSms": True, "otpTtlSeconds": 300}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()

    def test_send_rate_limit_blocks_sixth(self) -> None:
        for _ in range(OTP_SEND_LIMIT):
            out = asyncio.run(shop_otp_service.send(slug="demo", phone="09111234567"))
            self.assertTrue(out["ok"])
        with self.assertRaises(shop_otp_service.OtpLimitError):
            asyncio.run(shop_otp_service.send(slug="demo", phone="09111234567"))

    def test_verify_blocks_after_five_failures(self) -> None:
        self.redis.store["shop-otp:demo:09111234567"] = "123456"
        for _ in range(OTP_VERIFY_LIMIT):
            with self.assertRaises(ValueError):
                asyncio.run(shop_otp_service.verify(slug="demo", phone="09111234567", code="000000"))
        with self.assertRaises(shop_otp_service.OtpLimitError):
            asyncio.run(shop_otp_service.verify(slug="demo", phone="09111234567", code="123456"))
        self.assertEqual(self.redis.store.get("shop-otp:demo:09111234567"), "123456")

    def test_verify_success_clears_attempts(self) -> None:
        self.redis.store["shop-otp:demo:09111234567"] = "123456"
        with self.assertRaises(ValueError):
            asyncio.run(shop_otp_service.verify(slug="demo", phone="09111234567", code="000000"))
        out = asyncio.run(shop_otp_service.verify(slug="demo", phone="09111234567", code="123456"))
        self.assertTrue(out["ok"])
        self.assertNotIn("shop-otp:vl:demo:09111234567", self.redis.counters)

    def test_failed_send_refunds_sms_charge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with patch.object(shop_otp_service, "get_settings", return_value={"mockSms": False}), patch(
                    "app.services.wallet_service.consume_sms", return_value={"charged": 200, "count": 3, "quota": 2}
                ) as consume, patch("app.services.wallet_service.refund_sms") as refund, patch.object(
                    shop_otp_service.sms_service,
                    "resolve_sms",
                    return_value={"provider": "smsir", "api_key": "k", "template_id": "1", "token_name": "code"},
                ), patch.object(
                    shop_otp_service.sms_service, "send_otp", new=AsyncMock(side_effect=RuntimeError("gateway"))
                ):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(shop_otp_service.send(slug="demo", phone="09111234567"))
        consume.assert_called_once()
        refund.assert_called_once_with(200)
        self.assertNotIn("shop-otp:demo:09111234567", self.redis.store)


if __name__ == "__main__":
    unittest.main()
