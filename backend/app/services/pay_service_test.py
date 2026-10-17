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

                    async def read(self, size=-1):
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


class CancelThenOkTests(unittest.TestCase):
    """A cancel keeps the hint: a later OK for the same authority is verified with the gateway, not dropped."""

    def _order(self) -> dict:
        return {
            "id": "ord50",
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
            "authority": "AUTH50",
        }

    def test_cancelled_authority_is_verified_when_an_ok_arrives_later(self) -> None:
        verify = AsyncMock(return_value={"ok": True, "refId": "R50", "code": 100})
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
            write_json("pay-orders.json", [self._order()])
            write_json("pay-pending.json", {"AUTH50": {"phone": PHONE, "orderId": "ord50", "gateway": "zarinpal"}}, shared=True)
            with patch.object(payment_service, "zarinpal_verify", new=verify), patch.object(
                pay_service, "_resync_storefront_after_paid", lambda: None
            ):
                asyncio.run(pay_service.finish_order(authority="AUTH50", ok=False))
                cancelled = pay_service.get_order("ord50")
                still_pending = read_json("pay-pending.json", {}, shared=True)
                asyncio.run(pay_service.finish_order(authority="AUTH50", ok=True))
                paid = pay_service.get_order("ord50")
        self.assertEqual(cancelled["status"], "failed")
        self.assertIn("AUTH50", still_pending)
        self.assertEqual(paid["status"], "paid")
        verify.assert_awaited_once()

    def test_cancelled_hints_are_pruned_after_a_week(self) -> None:
        import time

        now = int(time.time())
        pending = {
            "OLD": {"phone": PHONE, "orderId": "a", "cancelledAt": now - 8 * 24 * 3600},
            "RECENT": {"phone": PHONE, "orderId": "b", "cancelledAt": now - 3600},
            "LIVE": {"phone": PHONE, "orderId": "c"},
        }
        kept = pay_service._prune_cancelled(pending)
        self.assertNotIn("OLD", kept)
        self.assertIn("RECENT", kept)
        self.assertIn("LIVE", kept)
class _SlowUpload:
    """A receipt upload whose body arrives late; another order is saved while it is still reading."""

    filename = "receipt.jpg"
    content_type = "image/jpeg"

    def __init__(self, while_reading) -> None:
        self.while_reading = while_reading

    async def read(self, size: int = -1) -> bytes:
        self.while_reading()
        return b"jpg-bytes"


class AttachReceiptRaceTests(unittest.TestCase):
    """An order created while a receipt uploads must survive the receipt being saved."""

    def test_order_created_during_a_slow_upload_is_kept(self) -> None:
        first = {
            "id": "ord1", "title": "کیف", "amount": 1000, "productId": "", "qty": 1, "customer": "علی",
            "channel": "دایرکت", "gateway": "zarinpal", "owner": "hub", "merchant": HUB, "commissionBps": 0,
            "status": "pending", "authority": "A1",
        }
        second = {**first, "id": "ord2", "authority": "A2"}

        def another_order_is_saved() -> None:
            write_json("pay-orders.json", [first, second])

        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
            write_json("pay-orders.json", [first])
            with patch.object(pay_service, "verify_pay_secret", return_value=PHONE), patch.object(
                pay_service, "_tell_receipt", lambda row: None
            ), patch("app.services.support_service.create_ticket", lambda **kwargs: None), patch(
                "app.services.chat_media_service.save", return_value={"name": "r.jpg"}
            ):
                asyncio.run(
                    pay_service.attach_receipt(slug="x", secret="s", order_no="ord1", upload=_SlowUpload(another_order_is_saved))
                )
                stored = {row["id"]: row["status"] for row in pay_service._orders()}
        self.assertIn("ord2", stored)
        self.assertEqual(stored["ord1"], "awaiting_receipt")


class PaymentSignKeyTests(unittest.TestCase):
    """The payment webhook never falls back to the JWT key in production."""

    BODY = b'{"slug":"x"}'

    def test_production_without_its_own_secret_refuses_every_webhook(self) -> None:
        import hmac as _hmac
        import hashlib

        jwt_sig = _hmac.new(settings.jwt_secret.encode(), self.BODY, hashlib.sha256).hexdigest()
        with patch.object(pay_service.env, "payments_enabled", True), patch.object(pay_service.env, "payment_sign_secret", ""):
            self.assertFalse(pay_service.valid_sign(self.BODY, jwt_sig))

    def test_own_secret_is_checked(self) -> None:
        import hmac as _hmac
        import hashlib

        sig = _hmac.new(b"webhook-key", self.BODY, hashlib.sha256).hexdigest()
        with patch.object(pay_service.env, "payments_enabled", True), patch.object(pay_service.env, "payment_sign_secret", "webhook-key"):
            self.assertTrue(pay_service.valid_sign(self.BODY, sig))
            self.assertFalse(pay_service.valid_sign(self.BODY, "0" * 64))

    def test_development_keeps_the_jwt_fallback(self) -> None:
        import hmac as _hmac
        import hashlib

        jwt_sig = _hmac.new(settings.jwt_secret.encode(), self.BODY, hashlib.sha256).hexdigest()
        with patch.object(pay_service.env, "payments_enabled", False), patch.object(pay_service.env, "payment_sign_secret", ""):
            self.assertTrue(pay_service.valid_sign(self.BODY, jwt_sig))


class _OversizeUpload:
    """A receipt bigger than the cap: the service asks for at most cap+1 bytes, never the whole body."""

    filename = "receipt.jpg"
    content_type = "image/jpeg"

    def __init__(self) -> None:
        self.asked: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.asked.append(size)
        return b"x" * (size if size > 0 else 30_000_000)


class ReceiptSizeTests(unittest.TestCase):
    def test_oversize_receipt_is_refused_after_a_bounded_read(self) -> None:
        upload = _OversizeUpload()
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope(PHONE):
            write_json("pay-orders.json", [{"id": "ord1", "status": "pending", "authority": "A1", "merchant": HUB}])
            with patch.object(pay_service, "verify_pay_secret", return_value=PHONE), patch(
                "app.services.chat_media_service.save", return_value={"name": "r.jpg"}
            ) as save:
                with self.assertRaises(ValueError):
                    asyncio.run(pay_service.attach_receipt(slug="x", secret="s", order_no="ord1", upload=upload))
        self.assertEqual(upload.asked, [pay_service.RECEIPT_MAX_BYTES + 1])
        save.assert_not_called()


class OpenOrderWindowTests(unittest.TestCase):
    """The history window (400 rows) drops finished orders only; an order waiting for a receipt is never dropped."""

    def test_awaiting_receipt_survives_a_full_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                rows = [{"id": "waiting", "status": "awaiting_receipt"}]
                rows += [{"id": f"done-{i}", "status": "paid"} for i in range(450)]
                pay_service._save_orders(rows)
                saved = read_json("pay-orders.json", [])
        ids = [row["id"] for row in saved]
        self.assertIn("waiting", ids)
        self.assertLessEqual(len(saved), 400)

    def test_receipt_rejected_and_needs_action_survive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                rows = [
                    {"id": "rejected", "status": "receipt_rejected"},
                    {"id": "stock", "status": "paid", "needsAction": {"reason": "stock"}},
                ]
                rows += [{"id": f"done-{i}", "status": "paid"} for i in range(450)]
                pay_service._save_orders(rows)
                ids = [row["id"] for row in read_json("pay-orders.json", [])]
        self.assertIn("rejected", ids)
        self.assertIn("stock", ids)
