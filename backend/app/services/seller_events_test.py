from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import pay_service, router_service, seller_events, storefront_service
from app.services.pay_service_test import _gateway
from app.state_store import read_json, tenant_scope, write_json

PHONE = "09135409482"
SLUG = "demo-shop"
SECRET = "pay-secret"
HOUR = 3600
NOW = seller_events.SINCE + 30 * 24 * HOUR
_VOICE_PATCHES: list = []


def setUpModule() -> None:
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE_PATCHES.append(started)


def tearDownModule() -> None:
    while _VOICE_PATCHES:
        _VOICE_PATCHES.pop().stop()


class _Shop(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.patches = [
            patch.object(settings, "state_dir", self.tmp.name),
            patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")),
            patch("app.services.catalog_sync_service.sync_live", return_value={"live": False}),
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
        router_service._THREAD.set("")

    def _chat(self) -> list[dict]:
        router_service._THREAD.set("")
        return router_service.snapshot().get("messages") or []

    def _card(self) -> dict:
        router_service._THREAD.set("")
        return router_service.snapshot().get("pendingConfirm") or {}

    def _turn(self, text: str, **kwargs) -> dict:
        async def model_unused(_messages, _tools):
            raise AssertionError("no model in these turns")

        router_service._THREAD.set("")
        return asyncio.run(router_service.turn(text, complete=model_unused, **kwargs))

    def _receipt_order(self) -> dict:
        order = asyncio.run(
            pay_service.shop_checkout(slug=SLUG, secret=SECRET, name="مریم", phone="09121234567", lines=[{"productId": self.ring["id"], "qty": 1}])
        )
        asyncio.run(pay_service.attach_receipt(slug=SLUG, secret=SECRET, order_no=str(order["id"]), upload=None))
        return order


class MomentTests(_Shop):
    def test_a_receipt_arrives_with_a_ready_card_that_approves_it(self) -> None:
        order = self._receipt_order()
        texts = [str(row.get("text") or "") for row in self._chat()]
        self.assertTrue(any("رسید کارت‌به‌کارت برای «انگشتر فیروزه» (۵۰۰٬۰۰۰ تومان، مریم) آمد" in text for text in texts))
        card = self._card()
        self.assertEqual(card["tool"], "approve_receipt")
        self.assertIn("تأیید شود؟", card["summary"])
        self.assertEqual(seller_events.unseen(), 1)
        self._turn("", confirm_id=card["id"])
        self.assertEqual(pay_service.get_order(str(order["id"]))["status"], "paid")
        self.assertTrue(any("سفارش تازه پرداخت شد" in str(row.get("text") or "") for row in self._chat()))

    def test_an_open_card_is_never_replaced_by_an_event(self) -> None:
        mine = self._turn("قیمت انگشتر فیروزه رو بکن ۶۰۰ هزار تومان")["pendingConfirm"]
        self._receipt_order()
        self.assertEqual(self._card()["id"], mine["id"])  # the seller's card stays; the event is only said
        self.assertTrue(any("رسید کارت‌به‌کارت" in str(row.get("text") or "") for row in self._chat()))

    def test_said_once_and_the_badge_clears(self) -> None:
        self.assertTrue(seller_events.announce("demo:1", "یک"))
        self.assertFalse(seller_events.announce("demo:1", "یک"))
        self.assertEqual(seller_events.unseen(), 1)
        seller_events.mark_seen()
        self.assertEqual(seller_events.unseen(), 0)
        self.assertEqual(sum(1 for row in self._chat() if row.get("text") == "یک"), 1)


def _order(oid: str, **fields) -> dict:
    row = {"id": oid, "title": "انگشتر فیروزه", "amount": 500000, "customer": "مریم", "at": NOW - 100 * HOUR, "lines": []}
    row.update(fields)
    return row


class SweepTests(_Shop):
    def test_what_is_owed_and_what_is_not(self) -> None:
        rows = [
            _order("ship", status="paid", paidAt=NOW - 49 * HOUR),
            _order("fresh", status="paid", paidAt=NOW - 10 * HOUR),
            _order("receipt", status="awaiting_receipt", history=[{"at": NOW - 25 * HOUR, "event": "receipt"}]),
            _order("receipt-new", status="awaiting_receipt", history=[{"at": NOW - 2 * HOUR, "event": "receipt"}]),
            _order("shipped", status="paid", stage="shipped", stageAt=NOW - 8 * 24 * HOUR),
            _order("action", status="paid", paidAt=NOW - 30 * HOUR, needsAction={"reason": "stock"}, history=[{"at": NOW - 30 * HOUR, "event": "needsAction"}]),
            _order("old", status="paid", paidAt=seller_events.SINCE - 10 * 24 * HOUR, at=seller_events.SINCE - 10 * 24 * HOUR),
            _order("done", status="paid", stage="delivered", stageAt=NOW - 30 * 24 * HOUR),
        ]
        owed = {key: card for key, _row, _text, card in seller_events.due(rows, NOW)}
        self.assertEqual(set(owed), {"ship48:ship", "receipt24:receipt", "delivered7:shipped", "action24:action"})
        self.assertEqual(owed["receipt24:receipt"], ("approve_receipt", {"order": "receipt", "approve": True}))
        self.assertEqual(owed["delivered7:shipped"], ("update_order", {"order": "shipped", "stage": "delivered"}))
        self.assertIsNone(owed["ship48:ship"])

    def test_a_sweep_says_each_thing_once_and_logs_it_on_the_order(self) -> None:
        write_json("pay-orders.json", [_order("ship1", status="paid", paidAt=NOW - 49 * HOUR), _order("shipped1", status="paid", stage="shipped", stageAt=NOW - 8 * 24 * HOUR)])
        self.assertEqual(seller_events.sweep_shop(NOW), 2)
        self.assertEqual(seller_events.sweep_shop(NOW + HOUR), 0)
        events = [item["event"] for item in pay_service.get_order("ship1")["history"]]
        self.assertEqual(events, ["reminded"])
        texts = "\n".join(str(row.get("text") or "") for row in self._chat())
        self.assertIn("دو روز است پرداخت شده و هنوز ارسال نشده", texts)
        self.assertNotIn("0912", texts)

    def test_the_delivery_card_from_a_sweep_marks_it_delivered(self) -> None:
        write_json("pay-orders.json", [_order("shipped2", status="paid", stage="shipped", stageAt=NOW - 8 * 24 * HOUR)])
        seller_events.sweep_shop(NOW)
        card = self._card()
        self.assertEqual(card["tool"], "update_order")
        self.assertIn("«تحویل‌شده» شود؟", card["summary"])
        self._turn("", confirm_id=card["id"])
        self.assertEqual(read_json("pay-orders.json", [])[0]["stage"], "delivered")

    def test_sweep_all_visits_only_shops_with_orders(self) -> None:
        write_json("pay-orders.json", [_order("ship3", status="paid", paidAt=NOW - 49 * HOUR)])
        out = seller_events.sweep_all(NOW)
        self.assertEqual(out, {"shops": 1, "said": 1})


if __name__ == "__main__":
    unittest.main()
