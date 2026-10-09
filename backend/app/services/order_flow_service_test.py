from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import order_flow_service, pay_service, storefront_service
from app.services.pay_service_test import _gateway
from app.state_store import tenant_scope, write_json

PHONE = "09135409482"
SLUG = "demo-shop"
SECRET = "pay-secret"


class _Orders(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.notices: list[str] = []
        self.patches = [
            patch.object(settings, "state_dir", self.tmp.name),
            patch("app.services.router_service.latest_thread_id", return_value="thread-1"),
            patch("app.services.router_service.post_notice", side_effect=lambda _tid, text: self.notices.append(text)),
            *_gateway(),
        ]
        for item in self.patches:
            item.start()
        self.scope = tenant_scope(PHONE)
        self.scope.__enter__()
        write_json("shop.json", {"slug": SLUG, "paySecret": SECRET, "brand": "جواهری سارا"})
        self.ring = storefront_service.add_product(title="انگشتر فیروزه", price=500000, stock=5, sku="ring")["product"]

    def tearDown(self) -> None:
        self.scope.__exit__(None, None, None)
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def _paid(self, *, phone: str = "09121234567", address: str = "") -> dict:
        order = asyncio.run(
            pay_service.shop_checkout(
                slug=SLUG, secret=SECRET, name="مریم", phone=phone, address=address, lines=[{"productId": self.ring["id"], "qty": 1}]
            )
        )
        asyncio.run(pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=str(order["id"]), upload=None))
        return pay_service.review_receipt(order_no=str(order["id"]), approve=True, note="")

    def _move(self, order: dict, stage: str, **kwargs) -> dict:
        return asyncio.run(order_flow_service.advance_order(str(order["id"]), stage, **kwargs))


class StageTests(_Orders):
    def test_paid_order_walks_to_delivered_and_keeps_a_timeline(self) -> None:
        order = self._paid(address="تهران، خیابان آزادی، پلاک ۱۲، کد پستی ۱۲۳۴۵۶۷۸۹۰")
        self.assertEqual(self._move(order, "preparing")["stage"], "preparing")
        shipped = self._move(order, "shipped", tracking="۱۲۳۴۵۶۷۸۹۰۱۲", carrier="پست")
        self.assertEqual((shipped["stage"], shipped["tracking"], shipped["carrier"]), ("shipped", "123456789012", "پست"))
        self.assertEqual(shipped["notified"], "none")  # no thread, no SMS template: nobody pretends the shopper was told
        done = self._move(order, "delivered")
        events = [item["event"] for item in done["history"]]
        self.assertEqual(events, ["created", "receipt", "paid", "preparing", "shipped", "notified", "delivered"])

    def test_steps_that_make_no_sense_are_refused(self) -> None:
        pending = asyncio.run(pay_service.create_order(title="سفارش", amount=5000))
        with self.assertRaises(ValueError) as caught:
            self._move(pending, "shipped")
        self.assertIn("پرداخت نشده", str(caught.exception))
        order = self._paid()
        self._move(order, "shipped", tracking="111111")
        with self.assertRaises(ValueError):
            self._move(order, "cancelled")
        with self.assertRaises(ValueError):
            self._move(order, "shipped", tracking="111111")
        self.assertEqual(self._move(order, "shipped", tracking="222222")["tracking"], "222222")  # a corrected code
        self._move(order, "delivered")
        with self.assertRaises(ValueError):
            self._move(order, "preparing")

    def test_an_unpaid_order_can_be_cancelled(self) -> None:
        pending = asyncio.run(pay_service.create_order(title="سفارش", amount=5000))
        self.assertEqual(self._move(pending, "cancelled")["stage"], "cancelled")
        self.assertNotIn("برگشت پول", order_flow_service.shopper_text(pending, "cancelled"))


class ShopperTests(_Orders):
    def test_a_dm_order_hears_about_the_shipment_in_its_thread(self) -> None:
        order = asyncio.run(pay_service.create_order(product_id=self.ring["id"], customer="مریم", thread_id="t-1"))
        with pay_service.tenant_file_lock("pay-orders"):
            rows = pay_service._orders()
            pay_service._mark_paid(rows[-1], ref_id="r")
            pay_service._save_orders(rows)
        with patch("app.services.inbox_service.reply", new=AsyncMock()) as sent:
            out = self._move(order, "shipped", tracking="987654321", carrier="تیپاکس")
        self.assertEqual(out["notified"], "dm")
        thread, text = sent.await_args.args[:2]
        self.assertEqual(thread, "t-1")
        self.assertIn("ارسال شد با تیپاکس", text)
        self.assertIn("987654321", text)
        self.assertIn("جواهری سارا", text)
        self.assertIn(f"/p/{order['id']}", text)

    def test_sms_goes_only_with_an_approved_template_and_counts_against_the_plan(self) -> None:
        order = self._paid()
        with patch.object(settings, "melipayamak_order_body_id", "999"), patch(
            "app.services.melipayamak_otp_service.send_pattern", new=AsyncMock(return_value="1" * 18)
        ) as sms, patch("app.services.wallet_service.consume_sms", return_value={"charged": 0}) as used:
            out = self._move(order, "shipped", tracking="555666777")
        self.assertEqual(out["notified"], "sms")
        used.assert_called_once()
        phone, text = sms.await_args.args
        self.assertEqual(phone, "09121234567")
        self.assertEqual(text.split(";")[:3], ["انگشتر فیروزه", "جواهری سارا", "555666777"])
        self.assertEqual(sms.await_args.kwargs["body_id"], "999")

    def test_a_failed_sms_is_refunded_and_said(self) -> None:
        order = self._paid()
        with patch.object(settings, "melipayamak_order_body_id", "999"), patch(
            "app.services.melipayamak_otp_service.send_pattern", new=AsyncMock(side_effect=RuntimeError("down"))
        ), patch("app.services.wallet_service.consume_sms", return_value={"charged": 200}), patch(
            "app.services.wallet_service.refund_sms"
        ) as refund:
            out = self._move(order, "shipped")
        self.assertEqual(out["notified"], "sms-failed")
        refund.assert_called_once_with(200)
        self.assertEqual(out["stage"], "shipped")  # the shipment is saved even when the message is not


class AddressTests(_Orders):
    def test_shopper_writes_the_address_until_it_ships(self) -> None:
        order = self._paid()
        out = order_flow_service.set_address(str(order["id"]), "تهران، خیابان آزادی، پلاک ۱۲")
        self.assertTrue(out["hasAddress"])
        self.assertNotIn("address", out)  # the public answer never carries it back
        with self.assertRaises(ValueError):
            order_flow_service.set_address(str(order["id"]), "کوتاه")
        self._move(order, "shipped")
        with self.assertRaises(ValueError):
            order_flow_service.set_address(str(order["id"]), "شیراز، خیابان زند، پلاک ۴")
        self.assertEqual(pay_service.seller_order(pay_service.get_order(str(order["id"])))["address"], "تهران، خیابان آزادی، پلاک ۱۲")

    def test_checkout_keeps_the_address_from_the_storefront_form(self) -> None:
        order = self._paid(address="اصفهان، چهارباغ، پلاک ۸")
        self.assertEqual(order["address"], "اصفهان، چهارباغ، پلاک ۸")

    def test_the_public_view_has_no_customer_data(self) -> None:
        order = self._paid(address="اصفهان، چهارباغ، پلاک ۸")
        shown = pay_service.public_order(pay_service.get_order(str(order["id"])))
        for key in ("customer", "customerMobile", "address", "history", "threadId"):
            self.assertNotIn(key, shown)


class SellerNoticeTests(_Orders):
    def test_the_seller_hears_about_a_receipt_and_a_paid_order(self) -> None:
        self._paid()
        self.assertIn("رسید کارت‌به‌کارت", self.notices[0])
        self.assertIn("سفارش تازه پرداخت شد: «انگشتر فیروزه»، ۵۰۰٬۰۰۰ تومان، مریم", self.notices[1])
        self.assertIn("آدرس هنوز ثبت نشده", self.notices[1])
        self.assertNotIn("0912", "".join(self.notices))


if __name__ == "__main__":
    unittest.main()
