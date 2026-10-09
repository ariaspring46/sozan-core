from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import order_tools, router_service, seller_tools
from app.state_store import read_json, tenant_scope, write_json

TENANT = "09129900008"
_VOICE_PATCHES: list = []


def setUpModule() -> None:
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE_PATCHES.append(started)


def tearDownModule() -> None:
    while _VOICE_PATCHES:
        _VOICE_PATCHES.pop().stop()


def _orders() -> None:
    now = int(time.time())
    write_json("shop.json", {"slug": "sara", "brand": "جواهری سارا"})
    write_json(
        "pay-orders.json",
        [
            {"id": "o1aaaaaaaaaa", "title": "انگشتر فیروزه", "amount": 500000, "status": "paid", "customer": "مریم", "threadId": "t1", "at": now - 300, "lines": []},
            {"id": "o2bbbbbbbbbb", "title": "گردنبند مروارید", "amount": 1200000, "status": "paid", "customer": "رضا احمدی", "customerMobile": "09121234567", "at": now - 200, "lines": []},
            {"id": "o3cccccccccc", "title": "انگشتر نقره", "amount": 890000, "status": "awaiting_receipt", "customer": "سارا", "at": now - 100, "lines": []},
        ],
    )


class _Tenant(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.patches = [
            patch.object(settings, "state_dir", self.tmp.name),
            patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")),
            patch("app.services.catalog_sync_service.sync_live", return_value={"live": True}),
        ]
        for item in self.patches:
            item.start()
        self.scope = tenant_scope(TENANT)
        self.scope.__enter__()
        _orders()

    def tearDown(self) -> None:
        self.scope.__exit__(None, None, None)
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()
        router_service._THREAD.set("")

    def _turn(self, text: str, **kwargs) -> dict:
        async def model_unused(_messages, _tools):
            raise AssertionError("the gate owns this sentence")

        return asyncio.run(router_service.turn(text, complete=model_unused, **kwargs))

    def _order(self, order_id: str) -> dict:
        return next(row for row in read_json("pay-orders.json", []) if row["id"] == order_id)

    def _last(self, out: dict) -> str:
        return str((out.get("messages") or [{}])[-1].get("text") or "")


class RouteTests(_Tenant):
    def test_sentences(self) -> None:
        cases = {
            "سفارش مریم رو فرستادم کد رهگیری 123456789012": "update_order",
            "رضا احمدی رو با تیپاکس فرستادم": "update_order",
            "سفارش گردنبند مروارید تحویل شد": "update_order",
            "سفارش مریم رو لغو کن": "update_order",
            "رسید سارا رو تأیید کن": "approve_receipt",
            "رسید سارا رو رد کن، پول نیومده": "approve_receipt",
            "سفارش مریم ارسال شد؟": "orders",
        }
        for sentence, tool in cases.items():
            self.assertEqual(router_service.route_tool(sentence), tool, sentence)
        self.assertEqual(seller_tools.route("پست کردم تو اینستا"), "")
        self.assertEqual(seller_tools.route("پاسخ خودکار رو لغو کن"), "")

    def test_parsing(self) -> None:
        self.assertEqual(order_tools.tracking_in("کد رهگیری: ۱۲۳۴۵۶۷۸۹۰۱۲"), "123456789012")
        self.assertEqual(order_tools.tracking_in("بارکد پستی 2045 6789 01 هست"), "")
        self.assertEqual(order_tools.carrier_in("با تیپاکس فرستادم"), "تیپاکس")
        self.assertEqual(order_tools.stage_in("تحویل پست دادم"), "shipped")
        self.assertEqual(order_tools.stage_in("به دستش رسید"), "delivered")


class UpdateOrderTests(_Tenant):
    def test_shipping_from_chat_tells_the_dm_customer(self) -> None:
        out = self._turn("سفارش مریم رو فرستادم کد رهگیری 123456789012")
        card = out["pendingConfirm"]
        self.assertEqual(
            card["summary"],
            "سفارش «انگشتر فیروزه» (۵۰۰٬۰۰۰ تومان، مریم) «ارسال‌شده» شود، کد رهگیری ۱۲۳۴۵۶۷۸۹۰۱۲؟\nبه مشتری در دایرکت خبر می‌دهم.",
        )
        self.assertEqual(self._order("o1aaaaaaaaaa").get("stage", ""), "")
        with patch("app.services.inbox_service.reply", new=AsyncMock()) as sent:
            done = self._turn("", confirm_id=card["id"])
        sent.assert_awaited_once()
        self.assertEqual(self._order("o1aaaaaaaaaa")["stage"], "shipped")
        self.assertEqual(self._order("o1aaaaaaaaaa")["tracking"], "123456789012")
        self.assertIn("به مشتری در دایرکت خبر دادم", self._last(done))

    def test_no_way_to_tell_the_customer_is_said_on_the_card(self) -> None:
        card = self._turn("رضا احمدی رو با تیپاکس فرستادم")["pendingConfirm"]
        self.assertIn("تیپاکس، بدون کد رهگیری", card["summary"])
        self.assertIn("راهی برای خبر دادن به مشتری نیست", card["summary"])

    def test_cancel_reminds_the_money_is_the_sellers_job(self) -> None:
        card = self._turn("سفارش مریم رو لغو کن")["pendingConfirm"]
        self.assertIn("«لغوشده»", card["summary"])
        self.assertIn("برگرداندن پول با خودت است", card["summary"])

    def test_an_unclear_order_asks_which(self) -> None:
        out = self._turn("سفارش رو فرستادم")
        self.assertFalse((out.get("pendingConfirm") or {}).get("id"))
        self.assertIn("کدام سفارش", self._last(out))
        self.assertIn("گردنبند مروارید", self._last(out))

    def test_orders_text_shows_the_work_left(self) -> None:
        text = seller_tools.orders_text()
        self.assertIn("کار مانده: ۲ منتظر ارسال", text)
        self.assertIn("— مریم —", text)


class ReceiptTests(_Tenant):
    def test_approve_from_chat_marks_it_paid(self) -> None:
        card = self._turn("رسید سارا رو تأیید کن")["pendingConfirm"]
        self.assertIn("رسید سفارش «انگشتر نقره» (۸۹۰٬۰۰۰ تومان، سارا) تأیید شود؟", card["summary"])
        self.assertIn("فقط اگر پول به حسابت نشسته", card["summary"])
        with patch("app.services.router_service.post_notice"):
            done = self._turn("", confirm_id=card["id"])
        self.assertEqual(self._order("o3cccccccccc")["status"], "paid")
        self.assertIn("تأیید شد", self._last(done))

    def test_reject(self) -> None:
        card = self._turn("رسید سارا رو رد کن، پول نیومده")["pendingConfirm"]
        self.assertIn("رد شود؟", card["summary"])
        self._turn("", confirm_id=card["id"])
        self.assertEqual(self._order("o3cccccccccc")["status"], "receipt_rejected")


if __name__ == "__main__":
    unittest.main()
