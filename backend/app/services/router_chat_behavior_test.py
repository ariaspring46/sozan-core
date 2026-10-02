"""Chat behaviour found by the scenario run (tools/chat_scenarios.py): what a seller reads and taps."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import router_service
from app.state_store import read_json, tenant_scope, write_json

PHONE = "09129900001"


class RouterChatBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "build"
        self.root.mkdir()
        self.patches = [
            patch.object(settings, "state_dir", self.tmp.name),
            patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")),
            patch("app.services.router_service._live_root", return_value=self.root),
        ]
        for item in self.patches:
            item.start()
        with tenant_scope(PHONE):
            write_json("shop.json", {"slug": "demo", "status": "ready", "brand": "دمو", "url": "https://demo.sozan-core.ir"})

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()
        router_service._THREAD.set("")

    def turn(self, text: str, complete=None, **kw):
        async def never(_messages, _tools):
            raise AssertionError("the gate should have answered without a model")

        with tenant_scope(PHONE):
            return asyncio.run(router_service.turn(text, complete=complete or never, **kw))

    def test_thanks_is_answered_by_the_gate(self) -> None:
        out = self.turn("ممنون")
        self.assertIn("خواهش", out["messages"][-1]["text"])
        # thanks is not a question: the next short message must not be glued to it
        self.assertNotEqual(out["messages"][-1].get("kind"), "ask")

    def test_red_is_a_colour_not_a_secret(self) -> None:
        out = self.turn("رنگ سایت را قرمز کن")
        self.assertEqual(out["pendingConfirm"]["tool"], "edit_shop")
        self.assertIn("«قرمز»", out["messages"][-1]["text"])

    def test_a_black_bag_with_a_price_is_a_product_not_a_colour(self) -> None:
        out = self.turn("کیف مشکی ۱.۲ میلیون تومن بذار تو سایت")
        self.assertEqual(out["pendingConfirm"]["tool"], "add_product")
        self.assertIn("۱٬۲۰۰٬۰۰۰", out["messages"][-1]["text"])

    def test_card_shows_the_price_with_persian_digits(self) -> None:
        out = self.turn("دستبند چرم را با قیمت ۴۵۰٬۰۰۰ تومان اضافه کن")
        self.assertIn("«دستبند چرم»", out["messages"][-1]["text"])
        self.assertIn("۴۵۰٬۰۰۰", out["messages"][-1]["text"])

    def test_bad_prices_make_no_card(self) -> None:
        for text in ("کیف را با قیمت منفی ۵۰۰ تومان اضافه کن", "شال را ۹۹۹۹۹۹۹۹۹۹۹۹۹۹ تومان اضافه کن"):
            out = self.turn(text)
            self.assertFalse(out.get("pendingConfirm"), text)

    def test_slang_hide_prices_and_multiline_text_open_a_card(self) -> None:
        for text in ("قیمتا رو قایم کن", "سلام\nقیمت‌ها\nرا مخفی کن"):
            out = self.turn(text)
            self.assertEqual((out.get("pendingConfirm") or {}).get("tool"), "edit_shop", text)

    def test_page_question_has_chips_and_the_answer_continues_it(self) -> None:
        first = self.turn("یک صفحه بساز")
        last = first["messages"][-1]
        self.assertEqual(last.get("kind"), "ask")
        self.assertIn("درباره ما", last.get("options") or [])
        second = self.turn("درباره ما")
        self.assertEqual(second["pendingConfirm"]["tool"], "edit_shop")
        self.assertIn("«درباره ما»", second["messages"][-1]["text"])

    def test_decimal_million_is_not_part_of_the_title(self) -> None:
        out = self.turn("کیف مشکی ۱.۲ میلیون تومن بذار تو سایت")
        self.assertIn("«کیف مشکی»", out["messages"][-1]["text"])

    def test_stock_change_points_to_the_inventory_page(self) -> None:
        out = self.turn("اون کالا را موجود کن")
        self.assertIn("انبار", out["messages"][-1]["text"])

    def test_pronoun_follow_up_uses_the_product_just_discussed(self) -> None:
        with tenant_scope(PHONE):
            write_json("products.json", [{"title": "انگشتر نقره", "price": 2500000, "stock": 3}, {"title": "کیف چرمی", "price": 900000, "stock": 0}])
        first = self.turn("قیمت انگشتر نقره چنده؟")
        self.assertIn("«انگشتر نقره»", first["messages"][-1]["text"])
        stock = self.turn("موجودیش چی؟")
        self.assertIn("«انگشتر نقره» ۳", stock["messages"][-1]["text"])
        price = self.turn("قیمت همون؟")
        self.assertIn("۲٬۵۰۰٬۰۰۰", price["messages"][-1]["text"])
        other = self.turn("موجودی کیف چرمی")
        self.assertIn("«کیف چرمی» ۰", other["messages"][-1]["text"])
        again = self.turn("قیمتش چنده")
        self.assertIn("«کیف چرمی»", again["messages"][-1]["text"])

    def test_pronoun_without_a_product_asks_which(self) -> None:
        with tenant_scope(PHONE):
            write_json("products.json", [{"title": "انگشتر نقره", "price": 2500000, "stock": 3}])
        out = self.turn("موجودیش چی؟")
        self.assertIn("کدام کالا", out["messages"][-1]["text"])

    def test_status_is_plain_persian_without_internal_words(self) -> None:
        with patch(
            "app.services.shop_service.snapshot",
            return_value={"shop": {"status": "ready", "slug": "demo", "cnameOk": True}, "scan": {}, "build": {"status": "ready"}},
        ), patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
            "app.services.plan_service.snapshot", return_value={"plan": "promax"}
        ), patch("app.services.wallet_service.get", return_value={"available": 0}):
            out = self.turn("وضعیت فروشگاه چطوره؟")
        text = out["messages"][-1]["text"]
        for word in ("بیلد", "اسکن", "ready", "/login"):
            self.assertNotIn(word, text)
        self.assertIn("پلن: پرو مکس", text)

    def test_studio_cards_name_the_post_not_its_id(self) -> None:
        cid = "00000000-0000-4000-8000-00000000c0de"
        with tenant_scope(PHONE):
            write_json(
                "studio-messages.json",
                [{"id": "m1", "role": "assistant", "text": "پست آماده شد.", "campaignId": cid, "captions": {"instagram": "انگشتر نقرهٔ دست‌ساز"}, "attachments": [{"kind": "image", "name": "p.png"}]}],
            )
        out = self.turn("همین پست را رسمی‌تر کن")
        text = out["messages"][-1]["text"]
        self.assertNotIn(cid, text)
        self.assertIn("انگشتر نقرهٔ دست‌ساز", text)
        self.assertEqual(out["pendingConfirm"]["tool"], "studio_chat")

    def test_card_number_is_refused_and_never_saved(self) -> None:
        out = self.turn("شماره کارت من ۶۰۳۷۹۹۷۱۲۳۴۵۶۷۸۹ است، ذخیره کن")
        blob = repr(out["messages"])
        self.assertNotIn("6037997123456789", blob)
        self.assertNotIn("۶۰۳۷۹۹۷۱۲۳۴۵۶۷۸۹", blob)
        self.assertIn("ننویس", out["messages"][-1]["text"])

    def test_budget_cap_is_a_message_not_a_retry(self) -> None:
        calls = {"n": 0}

        class Capped(RuntimeError):
            budget_capped = True

        async def complete(_messages, _tools):
            calls["n"] += 1
            raise Capped("daily")

        out = self.turn("یک سؤال دارم", complete)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(out["messages"][-1]["text"], router_service.BUDGET_CAPPED)

    def test_model_prose_is_plain_text_with_half_spaces(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "**نمیتوانم** این کار را بکنم.\n- کیفها را ببین", "tool_calls": []}

        out = self.turn("یک سؤال دارم", complete)
        text = out["messages"][-1]["text"]
        self.assertNotIn("**", text)
        self.assertIn("نمی‌توانم", text)
        self.assertIn("کیف‌ها", text)

    def test_english_refusal_to_a_harmless_request_becomes_a_question(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "I'm sorry, but I can't help with that.", "tool_calls": []}

        out = self.turn("اون یکی را حذف کن", complete)
        self.assertEqual(out["messages"][-1]["text"], router_service.CLARIFY_FALLBACK)


if __name__ == "__main__":
    unittest.main()
