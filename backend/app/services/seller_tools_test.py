from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import router_service, seller_tools
from app.state_store import read_json, tenant_scope, write_json

TENANT = "09129900007"
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=seller_tools.TEHRAN).timestamp()
_VOICE_PATCHES: list = []


def setUpModule() -> None:
    # the assistant's voice asks the cloud model; these tests take the plain sentences
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE_PATCHES.append(started)


def tearDownModule() -> None:
    while _VOICE_PATCHES:
        _VOICE_PATCHES.pop().stop()


def _shop() -> None:
    write_json(
        "products.json",
        [
            {"id": "p1", "title": "انگشتر فیروزه", "price": 500000, "stock": 2, "discount": 0},
            {"id": "p2", "title": "انگشتر نقره", "price": 300000, "stock": 0, "discount": 0},
            {"id": "p3", "title": "گردنبند مروارید", "price": 1200000, "stock": 1, "discount": 15},
        ],
    )
    write_json(
        "sales.json",
        [
            {"id": "s1", "title": "انگشتر فیروزه", "amount": 500000, "status": "paid", "at": int(NOW - 3600)},
            {"id": "s2", "title": "انگشتر فیروزه", "amount": 500000, "status": "paid", "at": int(NOW - 3 * 86400)},
            {"id": "s3", "title": "گردنبند مروارید", "amount": 1200000, "status": "paid", "at": int(NOW - 20 * 86400)},
            {"id": "s4", "title": "قدیمی", "amount": 999, "status": "paid", "at": int(NOW - 40 * 86400)},
        ],
    )
    write_json(
        "pay-orders.json",
        [
            {"id": "o1", "title": "انگشتر فیروزه", "amount": 500000, "status": "paid", "at": int(NOW - 7200)},
            {"id": "o2", "title": "گردنبند مروارید", "amount": 1200000, "status": "awaiting_receipt", "at": int(NOW - 600)},
            {"id": "o3", "title": "انگشتر نقره", "amount": 300000, "status": "pending", "at": int(NOW - 60)},
        ],
    )
    write_json(
        "inbox.json",
        {
            "threads": [
                {
                    "id": "t1",
                    "platform": "instagram",
                    "sender": "مریم",
                    "senderId": "ig-1",
                    "chatId": "",
                    "messages": [{"id": "m1", "role": "inbound", "text": "سفارشم کی میرسه؟", "at": int(NOW)}],
                    "updatedAt": int(NOW),
                },
                {
                    "id": "t2",
                    "platform": "telegram",
                    "sender": "رضا احمدی",
                    "senderId": "tg-2",
                    "chatId": "tg-2",
                    "messages": [{"id": "m2", "role": "inbound", "text": "سلام", "at": int(NOW - 100)}],
                    "updatedAt": int(NOW - 100),
                },
            ]
        },
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
        _shop()

    def tearDown(self) -> None:
        self.scope.__exit__(None, None, None)
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()
        router_service._THREAD.set("")

    def _turn(self, text: str, complete=None, **kwargs) -> dict:
        async def model_unused(_messages, _tools):
            raise AssertionError("the gate owns this sentence")

        return asyncio.run(router_service.turn(text, complete=complete or model_unused, **kwargs))

    def _card(self, text: str, complete=None) -> dict:
        out = self._turn(text, complete)
        card = out.get("pendingConfirm") or {}
        self.assertTrue(card.get("id"), out.get("messages", [])[-1:])
        return card

    def _last(self, out: dict) -> str:
        return str((out.get("messages") or [{}])[-1].get("text") or "")

    def _product(self, product_id: str) -> dict:
        return next(row for row in read_json("products.json", []) if row["id"] == product_id)


class RouteTests(_Tenant):
    def test_plain_business_sentences_pick_their_tool(self) -> None:
        cases = {
            "قیمت انگشتر فیروزه رو بکن ۶۰۰ هزار تومان": "edit_product",
            "موجودی انگشتر نقره رو ۵ کن": "edit_product",
            "۳ تا انگشتر فیروزه دیگه رسید، به موجودی اضافه کن": "edit_product",
            "انگشتر فیروزه تموم شد": "edit_product",
            "روی انگشتر فیروزه ۲۰ درصد تخفیف بذار": "set_discount",
            "روی همه ۱۰ درصد تخفیف بزن": "set_discount",
            "تخفیف گردنبند مروارید رو بردار": "set_discount",
            "سفارش جدید داریم؟": "orders",
            "امروز چقدر فروختم؟": "sales_report",
            "گزارش فروش این هفته": "sales_report",
            "به مریم بگو فردا ارسال میشه": "reply_customer",
            "جواب رضا رو بده که موجوده": "reply_customer",
        }
        for sentence, tool in cases.items():
            self.assertEqual(router_service.route_tool(sentence), tool, sentence)

    def test_other_jobs_keep_their_routes(self) -> None:
        self.assertEqual(router_service.route_tool("قیمت‌ها رو پنهان کن"), "edit_shop")
        self.assertEqual(router_service.route_tool("دستبند طلا با قیمت ۹۰۰ هزار تومان اضافه کن"), "add_product")
        self.assertEqual(router_service.route_tool("دستبند طلا با موجودی ۵ و قیمت ۲ میلیون تومان اضافه کن"), "add_product")
        self.assertEqual(router_service.route_tool("موجودی رو روی سایت نشون بده"), "")
        self.assertNotEqual(seller_tools.route("موجودی همه کالاها رو بده"), "edit_product")
        self.assertEqual(seller_tools.route("۲۰ درصد تخفیف بده به انگشتر فیروزه"), "set_discount")
        self.assertEqual(seller_tools._int("۶۰۰٬۰۰۰"), 600000)
        self.assertNotEqual(router_service.route_tool("برای این عکس کپشن بنویس"), "reply_customer")
        # a customer the inbox does not have, and a question, never open a write card
        self.assertEqual(seller_tools.route("به علی بگو سلام"), "")
        self.assertNotEqual(seller_tools.route("انگشتر فیروزه ناموجوده؟"), "edit_product")

    def test_the_sentences_that_missed_on_the_lab_phone(self) -> None:
        # live check 2026-10-09: advice, the old stock fact reply, «ده درصدی» and the model's inbox_status took these
        self.assertEqual(router_service.route_tool("این هفته فروش چطور بوده؟"), "sales_report")
        self.assertEqual(router_service.route_tool("ببین کدوم کالاها موجودی ندارن"), "products")
        self.assertEqual(router_service.route_tool("کدوم کالاها تموم شده"), "products")
        self.assertEqual(router_service.route_tool("واسه انگشتر فیروزه یه تخفیف ده درصدی بذار"), "set_discount")
        self.assertEqual(router_service.route_tool("مشتری آخر پرسیده کی ارسال میشه، بهش بگو پس‌فردا"), "reply_customer")
        self.assertEqual(router_service.route_tool("رضا احمدی پرسیده موجوده؟ بهش بگو آره"), "reply_customer")
        self.assertEqual(seller_tools._reply_parts({}, "مشتری آخر پرسیده کی ارسال میشه، بهش بگو پس‌فردا"), ("آخرین", "پس‌فردا"))
        self.assertIn("انگشتر نقره", seller_tools.products_text("", "ببین کدوم کالاها موجودی ندارن"))
        self.assertNotIn("انگشتر فیروزه", seller_tools.products_text("", "ببین کدوم کالاها موجودی ندارن"))
        self.assertEqual(seller_tools._percent_in("بیست و پنج درصد"), 25)
        self.assertIsNone(seller_tools._percent_in("ده تا انگشتر"))

    def test_the_reply_to_the_last_customer_goes_to_the_newest_waiting_thread(self) -> None:
        card = self._card("مشتری آخر پرسیده کی ارسال میشه، بهش بگو پس‌فردا")
        self.assertEqual(card["summary"], "این پیام برای «مریم» در اینستاگرام فرستاده شود؟\n«پس‌فردا»")

    def test_counting_and_discount_questions_get_the_numbers(self) -> None:
        with patch("app.services.seller_tools.time.time", return_value=NOW):
            said = router_service.decide("امروز چند تا خرید داشتیم؟")
        self.assertEqual(said["kind"], "direct")
        self.assertIn("فروش امروز: ۱ سفارش، ۵۰۰٬۰۰۰ تومان", said["text"])
        said = router_service.decide("تخفیف داریم؟")
        self.assertIn("گردنبند مروارید", said["text"])

    def test_a_sales_number_is_not_a_growth_plan(self) -> None:
        from app.services.router_loop import _wants_growth

        self.assertFalse(_wants_growth("فروشم امروز چقدر بوده؟"))
        self.assertTrue(_wants_growth("فروشم کمه چیکار کنم"))


class ReadTests(_Tenant):
    def test_orders_count_by_status_and_list_the_newest(self) -> None:
        text = seller_tools.orders_text(now=NOW)
        self.assertIn("۱ پرداخت‌شده، ۱ در انتظار پرداخت، ۱ رسید منتظر بررسی", text)
        self.assertLess(text.index("انگشتر نقره"), text.index("گردنبند مروارید"))
        self.assertIn("۱ رسید منتظر تأیید توست", text)

    def test_sales_report_counts_tehran_days(self) -> None:
        text = seller_tools.sales_text(now=NOW)
        self.assertIn("فروش امروز: ۱ سفارش، ۵۰۰٬۰۰۰ تومان", text)
        self.assertIn("فروش ۷ روز اخیر: ۲ سفارش، ۱٬۰۰۰٬۰۰۰ تومان", text)
        self.assertIn("فروش ۳۰ روز اخیر: ۳ سفارش، ۲٬۲۰۰٬۰۰۰ تومان", text)
        self.assertIn("انگشتر فیروزه (۲)", text)
        self.assertNotIn("قدیمی", text)

    def test_empty_shop_says_so(self) -> None:
        write_json("pay-orders.json", [])
        write_json("sales.json", [])
        self.assertEqual(seller_tools.orders_text(now=NOW), "هنوز سفارشی ثبت نشده.")
        self.assertIn("در ۳۰ روز اخیر فروشی ثبت نشده", seller_tools.sales_text(now=NOW))

    def test_catalog_lookup_shows_price_discount_and_stock(self) -> None:
        text = seller_tools.products_text("گردنبند")
        self.assertIn("۱٬۲۰۰٬۰۰۰ تومان، با ۱۵٪ تخفیف ۱٬۰۲۰٬۰۰۰", text)
        self.assertIn("موجودی ۱", text)
        self.assertIn("۱ تا موجودی ندارد", seller_tools.products_text())

    def test_read_tools_answer_without_a_card(self) -> None:
        out = self._turn("سفارش جدید داریم؟")
        self.assertFalse((out.get("pendingConfirm") or {}).get("id"))
        self.assertIn("سفارش‌ها:", self._last(out))


class ProductEditTests(_Tenant):
    def test_price_change_waits_for_the_card_then_applies(self) -> None:
        card = self._card("قیمت انگشتر فیروزه رو بکن ۶۰۰ هزار تومان")
        self.assertEqual(card["summary"], "«انگشتر فیروزه»: قیمت از ۵۰۰٬۰۰۰ به ۶۰۰٬۰۰۰ تومان شود؟")
        self.assertEqual(self._product("p1")["price"], 500000)
        out = self._turn("", confirm_id=card["id"])
        self.assertEqual(self._product("p1")["price"], 600000)
        self.assertIn("روی سایت هم به‌روز شد", self._last(out))

    def test_stock_set_add_and_sold_out(self) -> None:
        card = self._card("موجودی انگشتر نقره رو ۵ کن")
        self.assertIn("موجودی از ۰ به ۵", card["summary"])
        self._turn("", confirm_id=card["id"])
        self.assertEqual(self._product("p2")["stock"], 5)
        card = self._card("۳ تا انگشتر فیروزه دیگه رسید، به موجودی اضافه کن")
        self.assertIn("موجودی از ۲ به ۵", card["summary"])
        card = self._card("انگشتر فیروزه تموم شد")
        self.assertIn("موجودی از ۲ به ۰", card["summary"])

    def test_a_tiny_price_is_questioned_before_any_card(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "edit_product", "arguments": {"product": "انگشتر فیروزه", "price": 600}}]}

        out = self._turn("قیمت انگشتر فیروزه ۶۰۰ تومن بشه", complete)
        self.assertFalse((out.get("pendingConfirm") or {}).get("id"))
        self.assertIn("هزار", self._last(out))
        self.assertEqual(self._product("p1")["price"], 500000)

    def test_an_unclear_product_asks_which_one(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "edit_product", "arguments": {"product": "انگشتر", "price": 400000}}]}

        out = self._turn("قیمت انگشترا بشه ۴۰۰ هزار", complete)
        self.assertFalse((out.get("pendingConfirm") or {}).get("id"))
        self.assertIn("انگشتر فیروزه", self._last(out))
        self.assertIn("انگشتر نقره", self._last(out))

    def test_a_pointer_uses_the_product_just_discussed(self) -> None:
        self.assertIn("انگشتر فیروزه", self._last(self._turn("قیمت انگشتر فیروزه چنده؟")))
        card = self._card("قیمتش رو بکن ۷۰۰ هزار تومان")
        self.assertEqual(card["summary"], "«انگشتر فیروزه»: قیمت از ۵۰۰٬۰۰۰ به ۷۰۰٬۰۰۰ تومان شود؟")

    def test_a_card_for_a_product_removed_since_does_not_write(self) -> None:
        card = self._card("قیمت انگشتر فیروزه رو بکن ۶۰۰ هزار تومان")
        write_json("products.json", [row for row in read_json("products.json", []) if row["id"] != "p1"])
        out = self._turn("", confirm_id=card["id"])
        self.assertIn("پیدا نکردم", self._last(out))
        self.assertNotIn("p1", [row["id"] for row in read_json("products.json", [])])


class DiscountTests(_Tenant):
    def test_one_product_card_shows_the_new_price(self) -> None:
        card = self._card("روی انگشتر فیروزه ۲۰ درصد تخفیف بذار")
        self.assertIn("۲۰٪ تخفیف روی «انگشتر فیروزه»", card["summary"])
        self.assertIn("۵۰۰٬۰۰۰ ← ۴۰۰٬۰۰۰", card["summary"])
        self._turn("", confirm_id=card["id"])
        self.assertEqual(self._product("p1")["discount"], 20)

    def test_all_products_and_removal(self) -> None:
        card = self._card("روی همه ۱۰ درصد تخفیف بزن")
        self.assertIn("۱۰٪ تخفیف روی ۳ کالا", card["summary"])
        self._turn("", confirm_id=card["id"])
        self.assertEqual({row["discount"] for row in read_json("products.json", [])}, {10})
        card = self._card("تخفیف گردنبند مروارید رو بردار")
        self.assertEqual(card["summary"], "تخفیف «گردنبند مروارید» برداشته شود؟")
        self._turn("", confirm_id=card["id"])
        self.assertEqual(self._product("p3")["discount"], 0)

    def test_out_of_range_is_refused(self) -> None:
        self.assertIn("۹۰", seller_tools._discount_check({"product": "انگشتر فیروزه", "percent": 95}, ""))


class ReplyTests(_Tenant):
    def test_reply_shows_the_exact_text_then_sends_it(self) -> None:
        card = self._card("به مریم بگو فردا ارسال میشه")
        self.assertEqual(card["summary"], "این پیام برای «مریم» در اینستاگرام فرستاده شود؟\n«فردا ارسال میشه»")
        with patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as sent:
            out = self._turn("", confirm_id=card["id"])
        sent.assert_awaited_once()
        self.assertEqual(sent.await_args.kwargs["text"], "فردا ارسال میشه")
        self.assertEqual(sent.await_args.kwargs["sender_id"], "ig-1")
        self.assertIn("فرستاده شد", self._last(out))
        thread = read_json("inbox.json", {})["threads"][0]
        self.assertEqual(thread["messages"][-1]["status"], "sent")

    def test_a_failed_send_says_so(self) -> None:
        card = self._card("جواب رضا رو بده که موجوده")
        with patch("app.services.channel_outbound_service.deliver", new=AsyncMock(side_effect=ValueError("حساب این کانال وصل نیست"))):
            out = self._turn("", confirm_id=card["id"])
        self.assertIn("فرستاده نشد", self._last(out))

    def test_nothing_is_sent_without_the_card(self) -> None:
        with patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as sent:
            self._card("به مریم بگو فردا ارسال میشه")
        sent.assert_not_awaited()

    def test_the_decider_route_fills_the_customer_from_the_model(self) -> None:
        async def decider(_state):
            return {"action": "reply_customer", "accepted": True, "loopEnough": True, "effort": "quick", "ranked": []}

        async def complete(_messages, tools):
            self.assertEqual([item["function"]["name"] for item in tools], ["reply_customer"])
            return {"text": "", "tool_calls": [{"name": "reply_customer", "arguments": {"customer": "مریم", "text": "پنجشنبه می‌رسه"}}]}

        out = self._turn("مریم منتظر جوابه، جوابش اینه که پنجشنبه می‌رسه", complete, decider=decider)
        self.assertIn("«پنجشنبه می‌رسه»", (out.get("pendingConfirm") or {}).get("summary", ""))

    def test_an_unknown_customer_lists_the_recent_ones(self) -> None:
        text = seller_tools._reply_check({"customer": "علی", "text": "سلام"}, "")
        self.assertIn("«علی»", text)
        self.assertIn("«مریم»", text)


if __name__ == "__main__":
    unittest.main()
