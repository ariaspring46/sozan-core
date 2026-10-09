"""Stock before payment, and what happens when a paid order still finds too little (2026-10-09).

Before: the storefront and the checkout never looked at stock, so a shopper could pay for a product that was gone;
after payment the shortage was only a log line and the seller had no way to reach the shopper.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import catalog_sync_service, pay_service, seller_tools, storefront_service
from app.services.pay_service_test import _gateway
from app.state_store import tenant_scope, write_json

PHONE = "09135409482"
SLUG = "demo-shop"
SECRET = "pay-secret"


class _Shop(unittest.TestCase):
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
        write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
        self.ring = storefront_service.add_product(title="انگشتر فیروزه", price=500000, stock=1, sku="ring")["product"]
        self.bag = storefront_service.add_product(title="کیف چرم", price=900000, stock=4, sku="bag")["product"]

    def tearDown(self) -> None:
        self.scope.__exit__(None, None, None)
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def _checkout(self, lines: list[dict], phone: str = "09121234567") -> dict:
        return asyncio.run(pay_service.shop_checkout(slug=SLUG, secret=SECRET, name="مریم", phone=phone, lines=lines))

    def _pay(self, order: dict) -> dict:
        asyncio.run(pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=str(order["id"]), upload=None))
        return pay_service.review_receipt(order_no=str(order["id"]), approve=True, note="")

    def _stock(self, product: dict) -> int:
        return next(int(row["stock"]) for row in storefront_service.list_products()["products"] if row["id"] == product["id"])


class BeforePaymentTests(_Shop):
    def test_a_sold_out_product_gets_no_payment_link(self) -> None:
        storefront_service.update_product(self.ring["id"], {"stock": 0})
        with self.assertRaises(ValueError) as caught:
            self._checkout([{"productId": self.ring["id"], "qty": 1}])
        self.assertEqual(str(caught.exception), "«انگشتر فیروزه» تمام شده است.")
        self.assertEqual(pay_service.list_orders(), [])

    def test_more_than_the_shop_has_says_how_many_are_left(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._checkout([{"productId": self.bag["id"], "qty": 3}, {"productId": self.bag["id"], "qty": 2}])
        self.assertEqual(str(caught.exception), "از «کیف چرم» فقط ۴ عدد مانده است.")

    def test_a_cart_that_fits_is_ordered_with_the_shoppers_number(self) -> None:
        order = self._checkout([{"productId": self.bag["id"], "qty": 2}])
        saved = pay_service.get_order(str(order["id"]))
        self.assertEqual(saved["customerMobile"], "09121234567")
        # the number is not shown for an ordinary order
        self.assertNotIn("customerMobile", pay_service.public_order(saved))

    def test_a_dm_payment_link_for_a_sold_out_product_is_left_out(self) -> None:
        storefront_service.update_product(self.ring["id"], {"stock": 0})
        reply = asyncio.run(pay_service.attach_pay_link("موجوده", {"productId": self.ring["id"]}, customer="مریم"))
        self.assertEqual(reply, "موجوده")


class AfterPaymentTests(_Shop):
    def test_two_shoppers_on_the_last_one_flag_the_second_order(self) -> None:
        first = self._checkout([{"productId": self.ring["id"], "qty": 1}])
        second = self._checkout([{"productId": self.ring["id"], "qty": 1}], phone="09351112233")
        self._pay(first)
        self.assertEqual(self._stock(self.ring), 0)
        self.assertIn("تمام شد", self.notices[-1])
        paid = self._pay(second)
        self.assertEqual(paid["status"], "paid")  # the money arrived; the seller decides, nothing is hidden
        self.assertEqual(paid["needsAction"]["items"], [{"productId": self.ring["id"], "title": "انگشتر فیروزه", "wanted": 1, "had": 0}])
        self.assertEqual(paid["customerMobile"], "09351112233")
        self.assertEqual(self._stock(self.ring), 0)
        notice = self.notices[-1]
        self.assertIn("موجودی کم بود", notice)
        self.assertIn("۵۰۰٬۰۰۰", notice)
        self.assertNotIn("0935", notice)  # the shopper's number never goes into the chat (or the model)
        self.assertIn("نیازمند اقدام: ۱ سفارش", seller_tools.orders_text())

    def test_a_partial_shortage_takes_what_is_there(self) -> None:
        order = self._checkout([{"productId": self.bag["id"], "qty": 3}])
        storefront_service.update_product(self.bag["id"], {"stock": 2})
        paid = self._pay(order)
        self.assertEqual(paid["needsAction"]["items"][0]["had"], 2)
        self.assertEqual(self._stock(self.bag), 0)

    def test_a_normal_sale_needs_nothing(self) -> None:
        paid = self._pay(self._checkout([{"productId": self.bag["id"], "qty": 1}]))
        self.assertNotIn("needsAction", paid)
        self.assertEqual(self._stock(self.bag), 3)
        self.assertEqual(self.notices, [])


class StorefrontTests(_Shop):
    def test_only_sold_out_is_published(self) -> None:
        storefront_service.update_product(self.ring["id"], {"stock": 0})
        with patch.object(catalog_sync_service.shop_service, "factory_category_slug", return_value="goods"), patch.object(
            catalog_sync_service.shop_service, "factory_item_sub", return_value=("", "")
        ):
            rows, _menu = catalog_sync_service.catalog_rows({"slug": SLUG}, prior_cats={}, prior_subs={})
        stocks = {row["title"]: row.get("stock") for row in rows}
        self.assertEqual(stocks, {"انگشتر فیروزه": 0, "کیف چرم": None})


if __name__ == "__main__":
    unittest.main()
