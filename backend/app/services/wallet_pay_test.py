from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import billing_service, pay_service, payment_service, plan_service, storefront_service, wallet_service
from app.services.shop_service import _public_shop
from app.state_store import read_json, tenant_scope, write_json

HUB = "11111111-1111-1111-1111-111111111111"
OWN = "22222222-2222-2222-2222-222222222222"


class WalletPayTests(unittest.TestCase):
    def test_commission_floor(self) -> None:
        self.assertEqual(payment_service.commission_toman(1000, 200), 20)
        self.assertEqual(payment_service.commission_toman(99, 200), 1)
        self.assertEqual(payment_service.commission_toman(1, 200), 0)
        self.assertEqual(payment_service.commission_toman(50000, 0), 0)

    def test_resolve_own_zarinpal_has_no_commission(self) -> None:
        with patch.object(payment_service.env, "zarinpal_merchant_id", HUB):
            route = payment_service.resolve_sale_gateway(
                {"paymentGateway": "zarinpal", "paymentMerchantId": OWN}
            )
        self.assertEqual(route["owner"], "own")
        self.assertEqual(route["commissionBps"], 0)
        self.assertEqual(route["merchant"], OWN)

    def test_resolve_hub_when_no_own_merchant(self) -> None:
        with patch.object(payment_service.env, "payments_enabled", True), patch.object(
            payment_service.env, "zarinpal_merchant_id", HUB
        ), patch.object(payment_service.env, "commission_bps", 200):
            route = payment_service.resolve_sale_gateway({"paymentGateway": "mock"})
        self.assertEqual(route["owner"], "hub")
        self.assertEqual(route["id"], "zarinpal")
        self.assertEqual(route["commissionBps"], 200)
        self.assertEqual(route["merchant"], HUB)

    def test_resolve_own_idpay(self) -> None:
        with patch.object(payment_service.env, "zarinpal_merchant_id", HUB):
            route = payment_service.resolve_sale_gateway(
                {"paymentGateway": "idpay", "paymentApiKey": "idpay-secret"}
            )
        self.assertEqual(route["owner"], "own")
        self.assertEqual(route["id"], "idpay")
        self.assertEqual(route["commissionBps"], 0)

    def test_credit_sale_idempotent_on_order_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                first = wallet_service.credit_sale(
                    amount=1000, commission=20, order_id="o1", note="کیف", owner="hub"
                )
                second = wallet_service.credit_sale(
                    amount=1000, commission=20, order_id="o1", note="کیف", owner="hub"
                )
                kinds = [row["kind"] for row in wallet_service.ledger() if row.get("orderId") == "o1"]
                self.assertEqual(first["available"], 980)
                self.assertEqual(second["available"], 980)
                self.assertEqual(wallet_service.get()["available"], 980)
                self.assertEqual(kinds.count("sale_sozan"), 1)
                self.assertEqual(kinds.count("commission"), 1)

    def test_withdraw_ledger_matches_available(self) -> None:
        def balance() -> int:
            rows = read_json("wallet-ledger.json", [])
            return sum(int(row.get("amount") or 0) for row in rows if isinstance(row, dict))

        iban = "IR120170000000111111111111"
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                wallet_service.credit_sale(amount=1000, commission=0, order_id="seed", note="", owner="hub")
                hold = wallet_service.request_withdraw(amount=400, iban=iban, name="علی")
                after_hold = wallet_service.get()
                self.assertEqual(balance(), after_hold["available"])
                self.assertEqual(after_hold["pendingWithdraw"], 400)
                wallet_service.decide_withdraw(hold["withdraw"]["id"], ok=True, phone="09135409482")
                after_paid = wallet_service.get()
                self.assertEqual(balance(), after_paid["available"])
                self.assertEqual(after_paid["pendingWithdraw"], 0)
                wallet_service.credit_sale(amount=500, commission=0, order_id="seed2", note="", owner="hub")
                hold2 = wallet_service.request_withdraw(amount=200, iban=iban, name="علی")
                wallet_service.decide_withdraw(hold2["withdraw"]["id"], ok=False, phone="09135409482")
                after_reject = wallet_service.get()
                self.assertEqual(balance(), after_reject["available"])
                self.assertEqual(after_reject["pendingWithdraw"], 0)
                kinds = [row["kind"] for row in wallet_service.ledger()]
                self.assertIn("withdraw_paid", kinds)
                self.assertIn("withdraw_reject", kinds)
                self.assertEqual(after_paid["available"], 600)
                self.assertEqual(after_reject["available"], 1100)

    def test_credit_hub_sale_nets_commission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                wallet_service.credit_sale(
                    amount=1000, commission=20, order_id="o1", note="کیف", owner="hub"
                )
                snap = wallet_service.get()
                kinds = [row["kind"] for row in wallet_service.ledger()]
        self.assertEqual(snap["available"], 980)
        self.assertEqual(snap["lifetimeSales"], 1000)
        self.assertEqual(snap["lifetimeCommission"], 20)
        self.assertIn("sale_sozan", kinds)
        self.assertIn("commission", kinds)

    def test_credit_external_sale_not_withdrawable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                wallet_service.credit_sale(
                    amount=1000, commission=0, order_id="o2", note="شخصی", owner="own"
                )
                snap = wallet_service.get()
                kinds = [row["kind"] for row in wallet_service.ledger()]
        self.assertEqual(snap["available"], 0)
        self.assertEqual(snap["lifetimeSales"], 1000)
        self.assertEqual(kinds, ["sale_external"])

    def test_sms_quota_then_wallet_overage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with (
                    patch.object(plan_service, "current", return_value={"smsQuota": 2}),
                    patch.object(wallet_service.env, "sms_overage_toman", 200),
                ):
                    wallet_service.credit_sale(
                        amount=1000, commission=0, order_id="seed", note="", owner="hub"
                    )
                    first = wallet_service.consume_sms()
                    second = wallet_service.consume_sms()
                    third = wallet_service.consume_sms()
                    self.assertEqual(first["charged"], 0)
                    self.assertEqual(second["charged"], 0)
                    self.assertEqual(third["charged"], 200)
                    self.assertEqual(wallet_service.get()["available"], 800)
                    wallet_service.debit("sms", 800, note="خالی")
                    with self.assertRaises(ValueError) as ctx:
                        wallet_service.consume_sms()
        self.assertIn("سقف پیامک", str(ctx.exception))

    def test_refund_sms_restores_overage_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with (
                    patch.object(plan_service, "current", return_value={"smsQuota": 0}),
                    patch.object(wallet_service.env, "sms_overage_toman", 200),
                ):
                    wallet_service.credit_sale(
                        amount=1000, commission=0, order_id="seed", note="", owner="hub"
                    )
                    charged = wallet_service.consume_sms()
                    self.assertEqual(charged["charged"], 200)
                    self.assertEqual(wallet_service.get()["available"], 800)
                    self.assertEqual(wallet_service.sms_usage()["count"], 1)
                    wallet_service.refund_sms(charged["charged"])
                    self.assertEqual(wallet_service.get()["available"], 1000)
                    self.assertEqual(wallet_service.sms_usage()["count"], 0)
                    kinds = [row["kind"] for row in wallet_service.ledger()]
        self.assertEqual(kinds.count("sms"), 2)

    def test_attach_pay_link_appends_url(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                created = storefront_service.add_product(
                    title="کیف چرم", price=250000, stock=3, sku="bag-1"
                )
                product = created["product"]
                with (
                    patch.object(payment_service.env, "payments_enabled", True),
                    patch.object(payment_service.env, "zarinpal_merchant_id", HUB),
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
                    text = asyncio.run(
                        pay_service.attach_pay_link(
                            "این کیف موجود است.",
                            {"productId": product["id"], "amount": 250000, "title": "کیف چرم"},
                            channel="اینستاگرام",
                        )
                    )
                    skipped = asyncio.run(pay_service.attach_pay_link("سلام", None))
        self.assertIn("https://api.sozan-core.ir/p/", text)
        self.assertTrue(text.startswith("این کیف موجود است."))
        self.assertEqual(skipped, "سلام")

    def test_attach_pay_link_skips_unpriced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                created = storefront_service.add_product(
                    title="بدون قیمت", price=0, stock=1, sku="ask", priceNote="تماس بگیرید"
                )
                product = created["product"]
                out = asyncio.run(
                    pay_service.attach_pay_link("سلام", {"productId": product["id"], "amount": 0})
                )
        self.assertEqual(out, "سلام")

    def test_attach_pay_link_says_payment_later_without_merchant(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                patch.object(payment_service.env, "zarinpal_merchant_id", ""),
                tenant_scope("09135409482"),
            ):
                created = storefront_service.add_product(title="کیف چرم", price=250000, stock=1, sku="kif")
                product = created["product"]
                text = asyncio.run(
                    pay_service.attach_pay_link(
                        "این کیف موجود است.",
                        {"productId": product["id"], "amount": 250000, "title": "کیف چرم"},
                    )
                )
        self.assertIn(payment_service.PAYMENT_LATER, text)
        self.assertNotIn("http", text)

    def test_zarinpal_callback_credits_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json(
                    "pay-orders.json",
                    [
                        {
                            "id": "ord1",
                            "title": "کیف",
                            "amount": 1000,
                            "productId": "",
                            "qty": 1,
                            "customer": "علی",
                            "channel": "دایرکت",
                            "gateway": "zarinpal",
                            "owner": "hub",
                            "merchant": HUB,
                            "commissionBps": 200,
                            "status": "pending",
                            "authority": "AUTH99",
                        }
                    ],
                )
                write_json(
                    "pay-pending.json",
                    {"AUTH99": {"phone": "09135409482", "orderId": "ord1", "gateway": "zarinpal"}},
                    shared=True,
                )
                with patch.object(
                    payment_service,
                    "zarinpal_verify",
                    new=AsyncMock(return_value={"ok": True, "refId": "77", "code": 100}),
                ):
                    url = asyncio.run(pay_service.finish_order(authority="AUTH99", ok=True))
                wallet = wallet_service.get()
                order = pay_service.get_order("ord1")
                sales = storefront_service.list_sales()
        self.assertIn("pay=ok", url)
        self.assertEqual(wallet["available"], 980)
        self.assertEqual(order["status"], "paid")
        self.assertEqual(order["refId"], "77")
        self.assertEqual(sales["sales"][0]["channel"], "دایرکت")

    def test_start_subscription_from_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                wallet_service.credit_sale(
                    amount=2_000_000, commission=0, order_id="seed", note="", owner="hub"
                )
                with patch.object(payment_service, "zarinpal_request", new=AsyncMock()) as request:
                    out = asyncio.run(billing_service.start_subscription("pro", phone="09135409482"))
                self.assertTrue(out["activated"])
                self.assertTrue(out["fromWallet"])
                self.assertEqual(plan_service.current_plan_id(), "pro")
                request.assert_not_called()
                self.assertEqual(
                    wallet_service.get()["available"],
                    2_000_000 - plan_service.effective_price("pro"),
                )

    def test_withdraw_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                wallet_service.credit_sale(
                    amount=1000, commission=0, order_id="seed", note="", owner="hub"
                )
                row = wallet_service.request_withdraw(
                    amount=400, iban="IR120170000000111111111111", name="علی"
                )
                self.assertEqual(wallet_service.get()["available"], 600)
                self.assertEqual(wallet_service.get()["pendingWithdraw"], 400)
                paid = wallet_service.decide_withdraw(row["withdraw"]["id"], ok=True, phone="09135409482")
                self.assertEqual(paid["withdraw"]["status"], "paid")
                self.assertEqual(wallet_service.get()["available"], 600)
                self.assertEqual(wallet_service.get()["pendingWithdraw"], 0)

    def test_public_shop_hides_pay_secret(self) -> None:
        hidden = _public_shop({"slug": "demo", "paySecret": "secret-value"})
        self.assertNotIn("paySecret", hidden)
        self.assertEqual(hidden["slug"], "demo")
