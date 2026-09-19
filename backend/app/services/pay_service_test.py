from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import pay_service, payment_service, storefront_service
from app.state_store import read_json, tenant_scope, write_json

HUB = "11111111-1111-1111-1111-111111111111"
PHONE = "09135409482"
SLUG = "demo-shop"
SECRET = "pay-secret"


def _gateway():
    return (
        patch.object(payment_service.env, "zarinpal_merchant_id", HUB),
        patch.object(
            payment_service,
            "zarinpal_request",
            new=AsyncMock(
                return_value={
                    "authority": "AUTH-CART",
                    "startPayUrl": "https://payment.zarinpal.com/pg/StartPay/AUTH-CART",
                }
            ),
        ),
        patch.object(
            payment_service,
            "zarinpal_verify",
            new=AsyncMock(return_value={"ok": True, "refId": "ref-1", "code": 100}),
        ),
    )


class ShopPayB1Tests(unittest.TestCase):
    def test_checkout_decrements_stock_for_every_line(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
                first = storefront_service.add_product(title="کیف", price=1000, stock=5, sku="bag")["product"]
                second = storefront_service.add_product(title="کفش", price=2000, stock=4, sku="shoe")["product"]
                ctx = _gateway()
                with ctx[0], ctx[1], ctx[2]:
                    order = asyncio.run(
                        pay_service.shop_checkout(
                            slug=SLUG,
                            secret=SECRET,
                            name="علی",
                            lines=[
                                {"productId": first["id"], "qty": 2},
                                {"productId": second["id"], "qty": 1},
                            ],
                        )
                    )
                    url = asyncio.run(pay_service.finish_order(authority="AUTH-CART", ok=True))
                products = {row["id"]: row for row in storefront_service.list_products()["products"]}
                saved = pay_service.get_order(str(order["id"]))
        self.assertIn("pay=ok", url)
        self.assertEqual(products[first["id"]]["stock"], 3)
        self.assertEqual(products[second["id"]]["stock"], 3)
        self.assertEqual(saved["lines"], [{"productId": first["id"], "qty": 2}, {"productId": second["id"], "qty": 1}])

    def test_shop_paid_empty_ref_does_not_match_other_pending(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
                write_json(
                    "pay-orders.json",
                    [
                        {
                            "id": "ord-a",
                            "title": "اول",
                            "amount": 1000,
                            "productId": "",
                            "qty": 1,
                            "customer": "یک",
                            "channel": "فروشگاه",
                            "status": "pending",
                            "refId": "",
                            "owner": "hub",
                            "commissionBps": 0,
                        },
                        {
                            "id": "ord-b",
                            "title": "دوم",
                            "amount": 2000,
                            "productId": "",
                            "qty": 1,
                            "customer": "دو",
                            "channel": "فروشگاه",
                            "status": "pending",
                            "refId": "",
                            "owner": "hub",
                            "commissionBps": 0,
                        },
                    ],
                )
                paid = pay_service.shop_paid(
                    slug=SLUG,
                    order_id="ord-b",
                    amount=2000,
                    title="دوم",
                    customer="دو",
                    ref_id="",
                )
                first = pay_service.get_order("ord-a")
                second = pay_service.get_order("ord-b")
                empty = pay_service.shop_paid(
                    slug=SLUG,
                    order_id="",
                    amount=3000,
                    title="جدید",
                    customer="سه",
                    ref_id="",
                )
        self.assertEqual(paid["id"], "ord-b")
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "paid")
        self.assertNotEqual(empty["id"], "ord-a")
        self.assertNotEqual(empty["id"], "ord-b")

    def test_finish_order_keeps_pending_if_mark_paid_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
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
                            "commissionBps": 0,
                            "status": "pending",
                            "authority": "AUTH99",
                        }
                    ],
                )
                write_json(
                    "pay-pending.json",
                    {"AUTH99": {"phone": PHONE, "orderId": "ord1", "gateway": "zarinpal"}},
                    shared=True,
                )
                with (
                    patch.object(
                        payment_service,
                        "zarinpal_verify",
                        new=AsyncMock(return_value={"ok": True, "refId": "77", "code": 100}),
                    ),
                    patch.object(pay_service, "_mark_paid", side_effect=RuntimeError("boom")),
                ):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(pay_service.finish_order(authority="AUTH99", ok=True))
                pending = read_json("pay-pending.json", {}, shared=True)
                order = pay_service.get_order("ord1")
                with patch.object(
                    payment_service,
                    "zarinpal_verify",
                    new=AsyncMock(return_value={"ok": True, "refId": "77", "code": 100}),
                ):
                    url = asyncio.run(pay_service.finish_order(authority="AUTH99", ok=True))
                retry = pay_service.get_order("ord1")
        self.assertIn("AUTH99", pending)
        self.assertEqual(order["status"], "pending")
        self.assertIn("pay=ok", url)
        self.assertEqual(retry["status"], "paid")
        self.assertEqual(retry["refId"], "77")
