from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import billing_service, payment_service, plan_service
from app.state_store import read_json, tenant_scope, write_json


def _during_discount():
    now = datetime(2026, 9, 27, tzinfo=timezone.utc)
    until = (now + timedelta(days=7)).isoformat()
    return (
        patch.object(settings, "plan_price_pro", 1_414_000),
        patch.object(settings, "plan_price_promax", 2_414_000),
        patch.object(settings, "plan_price_ultra", 3_843_000),
        patch.object(settings, "plan_discount_percents", '{"pro":0,"promax":20,"ultra":30}'),
        patch.object(settings, "plan_discount_until", until),
    )


class PlanPriceTests(unittest.TestCase):
    def test_effective_price_before_and_after_discount(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        later = now + timedelta(days=8)
        with _during_discount()[0], _during_discount()[1], _during_discount()[2], _during_discount()[3], _during_discount()[4]:
            self.assertEqual(plan_service.effective_price("pro", now), 1_414_000)
            self.assertEqual(plan_service.effective_price("promax", now), 1_931_000)
            self.assertEqual(plan_service.effective_price("ultra", now), 2_690_000)
            self.assertEqual(plan_service.effective_price("pro", later), 1_414_000)
            self.assertEqual(plan_service.effective_price("promax", later), 2_414_000)
            self.assertEqual(plan_service.effective_price("free", now), 0)

    def test_checkout_amount_matches_public_catalog(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        patches = _during_discount()
        with tempfile.TemporaryDirectory() as raw:
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                catalog = plan_service.public_catalog(now)
                pro = next(item for item in catalog["plans"] if item["id"] == "pro")
                self.assertEqual(pro["price"], plan_service.effective_price("pro", now))
                self.assertEqual(pro["listPrice"], 1_414_000)
                self.assertEqual(pro["discountPercent"], 0)
                promax = next(item for item in catalog["plans"] if item["id"] == "promax")
                ultra = next(item for item in catalog["plans"] if item["id"] == "ultra")
                self.assertEqual(promax["price"], 1_931_000)
                self.assertEqual(promax["discountPercent"], 20)
                self.assertEqual(ultra["price"], 2_690_000)
                self.assertEqual(ultra["discountPercent"], 30)
                self.assertIn("مهر", catalog["discountUntilLabel"])
                self.assertIn("paymentReady", catalog)
                later = now + timedelta(days=8)
                after = plan_service.public_catalog(later)
                self.assertEqual(next(item for item in after["plans"] if item["id"] == "promax")["price"], 2_414_000)
                self.assertEqual(after["discountUntilLabel"], "")
                with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                    with (
                        patch.object(payment_service.env, "payments_enabled", True),
                        patch.object(plan_service, "effective_price", return_value=pro["price"]),
                        patch.object(payment_service, "merchant_id", return_value="11111111-1111-1111-1111-111111111111"),
                        patch.object(
                            payment_service,
                            "zarinpal_request",
                            new=AsyncMock(return_value={"authority": "A" * 36, "startPayUrl": "https://pay.example/a"}),
                        ),
                    ):
                        out = asyncio.run(billing_service.start_subscription("pro", phone="09135409482"))
                self.assertEqual(out["amount"], pro["price"])

    def test_phone_coupon_stacks_on_effective_price(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        patches = _during_discount()
        with tempfile.TemporaryDirectory() as raw:
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patch.object(settings, "phone_coupon_code", "SOZAN30"),
                patch.object(settings, "phone_coupon_percent", 30),
                patch.object(settings, "phone_coupon_until", ""),
                patch.object(settings, "state_dir", raw),
                tenant_scope("09129900007"),
                patch.object(plan_service, "discount_until", return_value=now + timedelta(days=7)),
                patch.object(payment_service.env, "payments_enabled", True),
                patch.object(payment_service, "merchant_id", return_value="11111111-1111-1111-1111-111111111111"),
            ):
                self.assertEqual(billing_service.apply_phone_coupon("pro", 1_414_000, "SOZAN30")[0], 989_800)
                self.assertEqual(billing_service.apply_phone_coupon("promax", 1_931_000, "سوزان30")[0], 1_351_700)
                self.assertEqual(billing_service.apply_phone_coupon("ultra", 2_690_000, "سوزانسی")[0], 1_883_000)
                quoted = billing_service.preview_coupon("pro", "SOZAN30")
                self.assertEqual(quoted["amount"], 989_800)
                with (
                    patch.object(payment_service, "merchant_id", return_value="11111111-1111-1111-1111-111111111111"),
                    patch.object(
                        payment_service,
                        "zarinpal_request",
                        new=AsyncMock(return_value={"authority": "B" * 36, "startPayUrl": "https://pay.example/b"}),
                    ),
                ):
                    out = asyncio.run(
                        billing_service.start_subscription("pro", phone="09129900007", code="SOZAN30")
                    )
                self.assertEqual(out["amount"], 989_800)
                write_json("billing.json", [{"coupon": "SOZAN30", "status": "paid", "plan": "pro"}])
                with self.assertRaises(ValueError):
                    billing_service.preview_coupon("promax", "SOZAN30")

    def test_ultra_checkout_stays_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with self.assertRaises(ValueError) as caught:
                    asyncio.run(billing_service.start_subscription("ultra", phone="09135409482"))
        self.assertIn("به‌زودی", str(caught.exception))

    def test_one_shop_cap_and_legacy_pro_stays(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json("plan.json", {"plan": "pro"})
                write_json("sites.json", ["one"])
                self.assertIsNotNone(plan_service.allow_new_site())
                write_json("sites.json", ["yek", "do", "se"])
                snap = plan_service.snapshot()
                self.assertEqual(snap["sitesUsed"], 3)
                self.assertEqual(read_json("sites.json", []), ["yek", "do", "se"])
                self.assertIsNotNone(plan_service.allow_new_site())

    def test_nowruz_label(self) -> None:
        self.assertEqual(plan_service.gregorian_to_jalali(2026, 3, 21), (1405, 1, 1))

    def test_coupon_waits_until_hub_merchant(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "phone_coupon_code", "SOZAN30"),
                patch.object(settings, "phone_coupon_percent", 30),
                patch.object(settings, "state_dir", raw),
                patch.object(plan_service, "discount_until", return_value=now + timedelta(days=7)),
                patch.object(payment_service, "merchant_id", return_value=""),
                tenant_scope("09129900007"),
            ):
                catalog = plan_service.public_catalog(now)
                self.assertIs(catalog["paymentReady"], False)
                with self.assertRaises(ValueError) as caught:
                    billing_service.preview_coupon("pro", "SOZAN30")
                self.assertEqual(str(caught.exception), payment_service.PAYMENT_LATER)
                with self.assertRaises(ValueError) as blocked:
                    asyncio.run(billing_service.start_subscription("pro", phone="09129900007"))
                self.assertEqual(str(blocked.exception), payment_service.PAYMENT_LATER)

    def test_payments_switch_closes_checkout_while_merchant_stays(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "phone_coupon_code", "SOZAN30"),
                patch.object(settings, "phone_coupon_percent", 30),
                patch.object(settings, "state_dir", raw),
                patch.object(plan_service, "discount_until", return_value=now + timedelta(days=7)),
                patch.object(payment_service.env, "payments_enabled", False),
                patch.object(payment_service.env, "zarinpal_merchant_id", "11111111-1111-1111-1111-111111111111"),
                patch.object(payment_service, "merchant_id", return_value="11111111-1111-1111-1111-111111111111"),
                tenant_scope("09129900007"),
            ):
                self.assertIs(plan_service.public_catalog(now)["paymentReady"], False)
                with self.assertRaises(ValueError) as caught:
                    billing_service.preview_coupon("pro", "SOZAN30")
                self.assertEqual(str(caught.exception), payment_service.PAYMENT_LATER)
                with self.assertRaises(ValueError) as blocked:
                    asyncio.run(billing_service.start_subscription("pro", phone="09129900007"))
                self.assertEqual(str(blocked.exception), payment_service.PAYMENT_LATER)
                with self.assertRaises(ValueError):
                    payment_service.resolve_sale_gateway({"paymentGateway": "mock"})
