from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import billing_service, payment_service, plan_service
from app.state_store import tenant_scope


class BillingServiceTests(unittest.TestCase):
    def test_start_subscription_returns_zarinpal_url(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with (
                    patch.object(payment_service, "merchant_id", return_value="11111111-1111-1111-1111-111111111111"),
                    patch.object(
                        payment_service,
                        "zarinpal_request",
                        new=AsyncMock(
                            return_value={
                                "authority": "A" * 36,
                                "startPayUrl": "https://payment.zarinpal.com/pg/StartPay/" + "A" * 36,
                            }
                        ),
                    ),
                ):
                    out = asyncio.run(billing_service.start_subscription("pro", phone="09135409482"))
        self.assertFalse(out["activated"])
        self.assertEqual(out["plan"], "pro")
        self.assertTrue(out["startPayUrl"].startswith("https://payment.zarinpal.com/pg/StartPay/"))

    def test_finish_subscription_sets_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with (
                    patch.object(payment_service, "merchant_id", return_value="11111111-1111-1111-1111-111111111111"),
                    patch.object(
                        payment_service,
                        "zarinpal_request",
                        new=AsyncMock(
                            return_value={
                                "authority": "AUTH123",
                                "startPayUrl": "https://payment.zarinpal.com/pg/StartPay/AUTH123",
                            }
                        ),
                    ),
                    patch.object(
                        payment_service,
                        "zarinpal_verify",
                        new=AsyncMock(return_value={"ok": True, "refId": "99", "code": 100}),
                    ),
                ):
                    asyncio.run(billing_service.start_subscription("pro", phone="09135409482"))
                    url = asyncio.run(billing_service.finish_subscription(authority="AUTH123", ok=True))
                    self.assertEqual(plan_service.current_plan_id(), "pro")
        self.assertIn("pay=ok", url)

    def test_to_gateway_amount_rial(self) -> None:
        with patch.object(payment_service.env, "zarinpal_amount_unit", "rial"):
            self.assertEqual(payment_service.to_gateway_amount(490000), 4_900_000)

    def test_idpay_verify_sends_amount_and_rejects_mismatch(self) -> None:
        sent: dict = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"status": 100, "amount": 1, "track_id": "t1"}

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                sent.update(json or {})
                return _Resp()

        with patch.object(payment_service.env, "zarinpal_amount_unit", "rial"), patch(
            "app.services.payment_service.httpx.AsyncClient", _Client
        ):
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(
                    payment_service.idpay_verify(
                        order_id="o1",
                        authority="id-1",
                        api_key="k",
                        amount_toman=490000,
                    )
                )
        self.assertEqual(sent.get("amount"), 4_900_000)
        self.assertIn("مبلغ", str(ctx.exception))

    def test_idpay_verify_accepts_matching_amount(self) -> None:
        class _Resp:
            status_code = 200

            def json(self):
                return {"status": 100, "amount": 4_900_000, "track_id": "t9", "payment": {"track_id": "t9"}}

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                return _Resp()

        with patch.object(payment_service.env, "zarinpal_amount_unit", "rial"), patch(
            "app.services.payment_service.httpx.AsyncClient", _Client
        ):
            out = asyncio.run(
                payment_service.idpay_verify(
                    order_id="o1",
                    authority="id-1",
                    api_key="k",
                    amount_toman=490000,
                )
            )
        self.assertTrue(out["ok"])
        self.assertEqual(out["refId"], "t9")
