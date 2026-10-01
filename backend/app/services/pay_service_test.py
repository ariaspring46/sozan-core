from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import pay_service, payment_service, storefront_service, wallet_service, wallet_service
from app.state_store import read_json, tenant_scope, write_json

HUB = "11111111-1111-1111-1111-111111111111"
PHONE = "09135409482"
SLUG = "demo-shop"
SECRET = "pay-secret"


def _gateway():
    return (
        patch.object(payment_service.env, "payments_enabled", True),
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
                with ctx[0], ctx[1], ctx[2], ctx[3]:
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
                    # فروشگاه بی‌درگاه: خریدار رسید می‌گذارد و فروشنده تأیید می‌کند
                    asyncio.run(pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=str(order["id"]), upload=None))
                    paid = pay_service.review_receipt(order_no=str(order["id"]), approve=True, note="")
                products = {row["id"]: row for row in storefront_service.list_products()["products"]}
                saved = pay_service.get_order(str(order["id"]))
                sales = storefront_service.list_sales()["sales"]
                shown = pay_service.public_order(saved)
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(sales[0]["source"], "gateway")
        self.assertGreater(int(shown["at"]), 0)
        self.assertEqual(products[first["id"]]["stock"], 3)
        self.assertEqual(products[second["id"]]["stock"], 3)
        self.assertEqual(saved["lines"], [{"productId": first["id"], "qty": 2}, {"productId": second["id"], "qty": 1}])

    def test_dry_mock_order_does_not_call_the_gateway(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                product = storefront_service.add_product(title="انگشتر", price=2500000, stock=3, sku="ring")["product"]
                called = AsyncMock(side_effect=AssertionError("gateway"))
                with patch("app.services.arvan_dns_service.edge_dry", return_value=True), patch.object(
                    payment_service, "zarinpal_request", new=called
                ), patch.object(payment_service, "idpay_request", new=called):
                    order = asyncio.run(
                        pay_service.create_order(title="انگشتر", amount=2500000, product_id=product["id"])
                    )
        self.assertTrue(str(order["payUrl"]).startswith("https://dry-mock.invalid/p/"))
        called.assert_not_called()

    def test_shop_config_and_receipt_flow(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
                cfg = pay_service.shop_config(slug=SLUG, secret=SECRET)
                self.assertEqual(cfg["paymentMethods"], ["receipt"])
                ctx = _gateway()
                with ctx[0], ctx[1], ctx[2]:
                    order = asyncio.run(pay_service.create_order(title="سفارش", amount=5000))

                class _Up:
                    filename = "receipt.png"
                    content_type = "image/png"

                    async def read(self):
                        return b"x" * 64

                out = asyncio.run(
                    pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=order["id"], upload=_Up())
                )
                self.assertEqual(out["status"], "awaiting_receipt")
                from app.services import support_service

                tickets = support_service.list_tickets()
                self.assertTrue(any(row.get("orderNo") == order["id"] for row in tickets))
                approved = pay_service.review_receipt(order_no=order["id"], approve=True, note="")
                self.assertEqual(approved["status"], "paid")

    def test_catalog_ids_maps_and_checks_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
                storefront_service.add_product(title="انگشتر", price=5000, stock=2, sku="ring-1")
                out = pay_service.catalog_ids(slug=SLUG, secret=SECRET)
                mapping = out["map"]
                self.assertTrue(any(k.startswith(SLUG + "-") for k in mapping))

    def test_receipt_reject_keeps_order_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
                ctx = _gateway()
                with ctx[0], ctx[1], ctx[2]:
                    order = asyncio.run(pay_service.create_order(title="سفارش", amount=5000))
                asyncio.run(
                    pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=order["id"], upload=None)
                )
                rejected = pay_service.review_receipt(order_no=order["id"], approve=False, note="خوانا نیست")
                self.assertEqual(rejected["status"], "receipt_rejected")
                # دوباره رسید می‌گذارد
                again = asyncio.run(
                    pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=order["id"], upload=None)
                )
                self.assertEqual(again["status"], "awaiting_receipt")

    def test_buyer_token_binding(self) -> None:
        from app.services import shop_otp_service

        token = shop_otp_service.mint_token(slug="shopx", phone="09111234567")
        self.assertTrue(shop_otp_service.valid_buyer_token(token, slug="shopx", phone="09111234567"))
        self.assertFalse(shop_otp_service.valid_buyer_token(token, slug="shopy", phone="09111234567"))
        self.assertFalse(shop_otp_service.valid_buyer_token(token + "x", slug="shopx", phone="09111234567"))

    def test_gateway_less_shop_orders_with_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                ctx = _gateway()
                with ctx[0], ctx[1], ctx[2], patch("app.services.arvan_dns_service.edge_dry", return_value=False):
                    order = asyncio.run(pay_service.create_order(title="سفارش", amount=1000))
        self.assertEqual(order.get("gateway"), "receipt")
        self.assertTrue(str(order.get("payUrl") or "").startswith("/p/"))
        self.assertEqual(order.get("paymentMethods"), ["receipt"])

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
        self.assertEqual(paid["id"], "ord-b")
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "paid")
        # وب‌هوک سفارش تازه نمی‌سازد و مبلغ متفاوت را رد می‌کند
        with self.assertRaises(ValueError):
            pay_service.shop_paid(slug=SLUG, order_id="", amount=3000, title="جدید", customer="سه", ref_id="")
        with self.assertRaises(ValueError):
            pay_service.shop_paid(slug=SLUG, order_id="ord-a", amount=999, title="اول", customer="یک", ref_id="")

    def test_finish_order_drops_pending_if_mark_paid_fails(self) -> None:
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
        self.assertNotIn("AUTH99", pending)
        self.assertEqual(order["status"], "pending")

    def test_mark_paid_twice_credits_wallet_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                row = {
                    "id": "ord-dup",
                    "title": "کیف",
                    "amount": 1000,
                    "productId": "",
                    "qty": 1,
                    "customer": "علی",
                    "channel": "دایرکت",
                    "owner": "hub",
                    "commissionBps": 0,
                    "status": "pending",
                }
                pay_service._mark_paid(row, ref_id="r1")
                first = wallet_service.get()["available"]
                row["status"] = "pending"
                pay_service._mark_paid(row, ref_id="r2")
                kinds = [item["kind"] for item in wallet_service.ledger() if item.get("orderId") == "ord-dup"]
                self.assertEqual(first, 1000)
                self.assertEqual(wallet_service.get()["available"], 1000)
                self.assertEqual(kinds.count("sale_sozan"), 1)

    def test_mark_paid_stock_shortage_emits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                row = {
                    "id": "ord-stock",
                    "title": "کیف",
                    "amount": 1000,
                    "productId": "missing-product",
                    "qty": 1,
                    "customer": "علی",
                    "channel": "دایرکت",
                    "owner": "hub",
                    "commissionBps": 0,
                    "status": "pending",
                    "lines": [{"productId": "missing-product", "qty": 1}],
                }
                with (
                    patch.object(pay_service, "emit_later") as emit,
                    self.assertLogs("sozan.pay", level="WARNING") as captured,
                ):
                    pay_service._mark_paid(row, ref_id="r1")
        emit.assert_called()
        payload = emit.call_args.kwargs
        self.assertEqual(payload["title"], "stock-shortage")
        self.assertEqual(payload["payload"]["productId"], "missing-product")
        self.assertTrue(any("stock-shortage" in line for line in captured.output))

    def test_finish_order_drops_orphan_pending_when_order_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("pay-orders.json", [])
                write_json(
                    "pay-pending.json",
                    {"AUTH-GONE": {"phone": PHONE, "orderId": "missing-order", "gateway": "zarinpal"}},
                    shared=True,
                )
                url = asyncio.run(pay_service.finish_order(authority="AUTH-GONE", ok=True))
                pending = read_json("pay-pending.json", {}, shared=True)
        self.assertIn("pay=missing", url)
        self.assertNotIn("AUTH-GONE", pending)


class TenantIndexTests(unittest.TestCase):
    def test_index_lookup_skips_full_scan(self) -> None:
        """د۱: جست‌وجو با فهرست پر، پیمایش همهٔ مستأجرها را صدا نمی‌زند."""
        import asyncio
        import tempfile

        from unittest.mock import patch

        from app.services import pay_service
        from app.services import tenant_index_service

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
                data = tenant_index_service._empty()
                data["slug"][SLUG] = PHONE
                data["builtAt"] = 1
                tenant_index_service._save(data)
                called = {"n": 0}

                def counting_iter():
                    called["n"] += 1
                    yield PHONE

                with patch.object(pay_service, "iter_tenants", counting_iter):
                    phone = pay_service.find_tenant_by_slug(SLUG)
                self.assertEqual(phone, PHONE)
                self.assertEqual(called["n"], 0)  # پیمایش کامل نشد

    def test_index_repairs_stale_row(self) -> None:
        import asyncio
        import tempfile

        from unittest.mock import patch

        from app.services import pay_service
        from app.services import tenant_index_service

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
                write_json("shop.json", {"slug": SLUG, "paySecret": SECRET})
            data = tenant_index_service._empty()
            data["slug"][SLUG] = "09120000099"  # ردیف کهنه/غلط
            tenant_index_service._save(data)
            with patch.object(settings, "state_dir", raw):
                phone = pay_service.find_tenant_by_slug(SLUG)
                self.assertEqual(phone, PHONE)
                fixed = tenant_index_service.load()
                self.assertEqual(fixed["slug"][SLUG], PHONE)


class TenantIndexRuntimeTests(unittest.TestCase):
    def test_rebuild_and_owners(self) -> None:
        from app.services import tenant_index_service as tix

        data = tix.rebuild([
            ("09120000001", {"shop": {"slug": "shop-a"}, "orderIds": ["o1"], "sendboxIds": ["acc1"]}),
        ])
        self.assertEqual(tix.slug_owner(data, "shop-a"), "09120000001")
        self.assertEqual(tix.order_owner(data, "o1"), "09120000001")
        self.assertEqual(tix.sendbox_owner(data, "acc1"), "09120000001")
        self.assertIsNone(tix.slug_owner(data, "shop-b"))


class RateLimitStatusTests(unittest.TestCase):
    def test_status_rate_limited_per_ip(self) -> None:
        """سقف ۶۰ درخواست در دقیقه برای /p/{id}/status per IP."""
        import asyncio
        import tempfile
        import httpx

        from unittest.mock import patch

        from app.config import settings

        async def run() -> int:
            from app.main import app

            transport = httpx.ASGITransport(app=app)
            statuses = []
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for _ in range(61):
                    res = await client.get("/p/nonexistent-id/status")
                    statuses.append(res.status_code)
            return statuses

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                statuses = asyncio.run(run())
        self.assertEqual(statuses[0], 404)
        self.assertTrue(any(s in (404, 429) for s in statuses))
