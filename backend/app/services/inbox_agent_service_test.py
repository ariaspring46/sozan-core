import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.config import settings
from app.services import inbox_agent_service, storefront_service
from app.state_store import tenant_scope


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://127.0.0.1:9292/v1/chat/completions"))


def _chat(content: str = "", calls: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return {"usage": {"prompt_tokens": 2, "completion_tokens": 3}, "choices": [{"message": message}]}


def _call(name: str, arguments: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def script_tools(payloads: list[dict], seen: list):
    async def fake(**kwargs):
        seen.append({"url": "tools", "body": kwargs})
        payload = payloads.pop(0)
        message = ((payload.get("choices") or [{}])[0].get("message") or {})
        _text, calls = inbox_agent_service._calls_from(payload)
        return {"text": str(message.get("content") or ""), "tool_calls": calls}

    return fake


class ScriptedClient:
    def __init__(self, payloads: list[dict], seen: list):
        self.payloads = payloads
        self.seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        self.seen.append({"url": url, "body": json, "auth": (headers or {}).get("Authorization")})
        payload = self.payloads.pop(0)
        return _response(payload)


class InboxAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        inbox_agent_service.clear_intent_cache()
        self.claims_complete = AsyncMock(return_value={"claims": []})
        self.claims_patch = patch("app.services.llm.complete_json", self.claims_complete)
        self.claims_patch.start()
        self.edge_patch = patch("app.services.arvan_dns_service.edge_dry", return_value=False)
        self.edge_patch.start()

    def tearDown(self) -> None:
        self.edge_patch.stop()
        self.claims_patch.stop()
        self.dir.cleanup()
        inbox_agent_service.clear_intent_cache()

    def test_stock_uses_inbox_surface_masks_pii_and_quotes_catalog(self) -> None:
        seen: list = []
        payloads = [
            _chat(calls=[_call("stock", {"product": "کفش چرم"})]),
            _chat(content="کفش چرم مشکی دو عدد موجود است و قیمتش چهار میلیون تومان است."),
        ]

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, seen)):
            storefront_service.add_product(title="کفش چرم مشکی", price=4000000, stock=2, sku="a")
            reply = asyncio.run(
                inbox_agent_service.answer("کفش چرم موجود است؟ شماره‌ام ۰۹۱۲۱۲۳۴۵۶۷", thread={"sender": "علی"})
            )
        self.assertIn("دو عدد", reply or "")
        self.assertEqual(seen[0]["body"]["surface"], "inbox")
        sent = json.dumps(seen[0]["body"]["messages"], ensure_ascii=False)
        self.assertIn("[تلفن]", sent)
        self.assertNotIn("09121234567", sent)
        tool_blob = seen[1]["body"]["messages"][-1]["content"]
        self.assertIn("4000000", tool_blob)
        self.assertIn('"stock": 2', tool_blob)

    def test_stock_matches_one_edit_typo(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)):
            storefront_service.add_product(title="انگشتر نقره", price=2500000, stock=3, sku="s")
            storefront_service.add_product(title="گردنبند فیروزه", price=1800000, stock=0, sku="t")
            hits = inbox_agent_service._match_products("نفره")
        self.assertEqual(len(hits), 1)
        self.assertIn("نقره", str(hits[0].get("title") or ""))

    def test_missing_order_is_honest(self) -> None:
        seen: list = []
        payloads = [
            _chat(calls=[_call("order_status", {"order_id": "nope"})]),
            _chat(content="این شماره سفارش را در فروشگاه پیدا نکردم."),
        ]

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, seen)), patch(
            "app.services.inbox_agent_service.intent_hint", return_value=""
        ):
            reply = asyncio.run(inbox_agent_service.answer("سفارش nope کجاست؟"))
        self.assertIn("پیدا نکردم", reply or "")
        self.assertIn("سفارش پیدا نشد", seen[1]["body"]["messages"][-1]["content"])

    def test_payment_link_is_appended_and_secrets_stay_out(self) -> None:
        seen: list = []
        payloads = [
            _chat(calls=[_call("payment_link", {"product": "کیف", "qty": 1})]),
            _chat(content="لینک پرداخت را می‌فرستم."),
        ]

        async def fake_order(**kwargs):
            return {
                "title": "کیف",
                "amount": 1000,
                "payUrl": "https://api.sozan-core.ir/p/abc",
                "merchant": "SECRET-MERCHANT",
                "apiKey": "SECRET-KEY",
            }

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, seen)), patch(
            "app.services.pay_service.create_order", new=fake_order
        ):
            storefront_service.add_product(title="کیف دوشی", price=1000, stock=1, sku="b")
            reply = asyncio.run(inbox_agent_service.answer("لینک پرداخت کیف را بفرست"))
        self.assertIn("https://api.sozan-core.ir/p/abc", reply or "")
        blob = seen[1]["body"]["messages"][-1]["content"]
        self.assertNotIn("SECRET", blob)

    def test_cloud_chat_is_allowed_and_local_embed_is_not_sent_to_arvan(self) -> None:
        seen: list = []
        posted = []

        def client(*args, **kwargs):
            posted.append(True)
            return ScriptedClient([], seen)

        async def fake_tools(**kwargs):
            seen.append(kwargs)
            return {"text": "سلام، کدام کالا را می‌خواهید؟", "tool_calls": []}

        with patch.object(settings, "local_llm_url", "https://api.arvancloudai.ir/v1"), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.httpx.AsyncClient", client), patch(
            "app.services.inbox_agent_service.complete_tools", fake_tools
        ):
            reply = asyncio.run(inbox_agent_service.answer("سلام، موجود است این کالا؟"))
        self.assertIn("کدام", reply or "")
        self.assertEqual(posted, [])
        self.assertEqual(seen[0]["surface"], "inbox")

    def test_embed_nudge_stays_on_local_bge(self) -> None:
        seen: list = []
        chat_payloads = [
            _chat(content="بگذارید بررسی کنم و برگردم خدمتتان."),
            _chat(calls=[_call("stock", {"product": "کفش"})]),
            _chat(content="کفش چرم یک عدد در انبار است."),
        ]
        embed_payloads = [
            {
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 2, "embedding": [0.0, 1.0]},
                    {"index": 3, "embedding": [0.0, 1.0]},
                    {"index": 4, "embedding": [0.0, 1.0]},
                    {"index": 5, "embedding": [0.0, 1.0]},
                    {"index": 6, "embedding": [0.0, 1.0]},
                    {"index": 7, "embedding": [0.0, 1.0]},
                    {"index": 8, "embedding": [0.0, 1.0]},
                ]
            },
            {"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        ]

        def client(*args, **kwargs):
            return ScriptedClient(embed_payloads, seen)

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch.object(
            settings, "local_llm_url", "http://127.0.0.1:9292/v1"
        ), patch("app.services.inbox_agent_service.emit_later"), patch(
            "app.services.inbox_agent_service.httpx.AsyncClient", client
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(chat_payloads, seen)):
            storefront_service.add_product(title="کفش چرم", price=10, stock=1, sku="c")
            reply = asyncio.run(inbox_agent_service.answer("این کفش هنوز هست؟"))
        self.assertIn("یک عدد", reply or "")
        embed = next(row for row in seen if row["url"].endswith("/embeddings"))
        self.assertEqual(embed["body"]["model"], "bge-m3")
        self.assertNotIn("arvan", embed["url"])
        self.assertTrue(any("ابزار stock" in str(row.get("body")) for row in seen))

    def test_invented_amount_is_rebuilt_once_then_handed_off(self) -> None:
        seen: list = []
        payloads = [
            _chat(content="قیمت ۵۵۵۵۵۵۵ تومان است."),
            _chat(content="باز هم ۵۵۵۵۵۵۵."),
        ]

        async def no_hint(_text: str) -> str:
            return ""

        from app.services import inbox_service

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, seen)), patch(
            "app.services.inbox_agent_service.intent_hint", no_hint
        ):
            created = inbox_service.inbound(platform="instagram", sender="مشتری", text="قیمت؟")
            reply = asyncio.run(
                inbox_agent_service.answer("قیمت چقدر است؟", thread=created["thread"])
            )
            shown = inbox_service.get_thread(created["thread"]["id"])
            waiting = inbox_service.list_threads(status_filter="pending")
        self.assertEqual(reply, inbox_agent_service.HANDOFF_LINE)
        self.assertNotIn("5555555", reply or "")
        reminder = seen[1]["body"]["messages"][-1]["content"]
        self.assertIn("رد شد", reminder)
        self.assertNotIn("5555555", reminder)
        self.assertTrue(shown["thread"]["paused"])
        self.assertEqual(shown["thread"]["handoffReason"], "عدد نامجاز")
        self.assertGreaterEqual(shown["thread"]["unread"], 1)
        self.assertTrue(any(row.get("handoffReason") == "عدد نامجاز" for row in waiting["threads"]))

    def test_rebuilt_amount_can_use_the_tool_number(self) -> None:
        payloads = [
            _chat(calls=[_call("stock", {"product": "کفش"})]),
            _chat(content="قیمت ۵۵۵۵۵۵۵ تومان است."),
            _chat(content="قیمت ۴۰۰۰۰۰۰ تومان است."),
        ]

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])):
            storefront_service.add_product(title="کفش چرم", price=4000000, stock=2, sku="n")
            reply = asyncio.run(inbox_agent_service.answer("قیمت کفش؟"))
        self.assertIn("۴۰۰۰۰۰۰", reply or "")
        self.assertNotIn("5555555", reply or "")
        self.assertNotEqual(reply, inbox_agent_service.HANDOFF_LINE)

    def test_foreign_shop_link_is_replaced_and_payment_link_stays(self) -> None:
        from app.state_store import write_json

        payloads = [
            _chat(calls=[_call("payment_link", {"product": "کیف", "qty": 1})]),
            _chat(content="سایت https://joahr-froshi.sozan-core.ir را ببین."),
        ]

        async def fake_order(**kwargs):
            return {
                "title": "کیف",
                "amount": 1000,
                "payUrl": "https://api.sozan-core.ir/p/abc",
            }

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])), patch(
            "app.services.pay_service.create_order", new=fake_order
        ):
            write_json("shop.json", {"url": "https://battery.example", "slug": "sales-battery"})
            storefront_service.add_product(title="کیف دوشی", price=1000, stock=1, sku="k")
            reply = asyncio.run(inbox_agent_service.answer("لینک سایت و پرداخت"))
        self.assertIn("https://battery.example", reply or "")
        self.assertIn("https://api.sozan-core.ir/p/abc", reply or "")
        self.assertNotIn("joahr-froshi", reply or "")

    def test_fake_url_is_removed_when_the_shop_has_no_address(self) -> None:
        from app.state_store import write_json

        payloads = [_chat(content="سایت https://example.com/fake را باز کن.")]

        async def no_hint(_text: str) -> str:
            return ""

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])), patch(
            "app.services.inbox_agent_service.intent_hint", no_hint
        ):
            write_json("shop.json", {"url": "", "slug": "", "port": 0, "domain": ""})
            reply = asyncio.run(inbox_agent_service.answer("لینک سایت"))
        self.assertIn("باز کن", reply or "")
        self.assertNotIn("example.com", reply or "")
        self.assertNotIn("http", reply or "")

    def test_real_claims_guard_keeps_a_clean_reply_and_replaces_a_fake_one(self) -> None:
        seen: list = []

        async def fake_json(system, user, *, surface="llm", max_tokens=700):
            seen.append({"surface": surface, "user": user})
            if "طبیعی" in user:
                return {"claims": ["طبیعی"]}
            return {"claims": []}

        self.claims_complete.side_effect = fake_json
        payloads = [
            _chat(content="سلام، در خدمتم"),
            _chat(content="کفش چرم موجود است."),
            _chat(content="این چرم طبیعی است. شماره ۰۹۱۲۰۰۰۰۰۰۰"),
        ]

        async def no_hint(_text: str) -> str:
            return ""

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.intent_hint", no_hint):
            storefront_service.add_product(title="کفش چرم", price=10, stock=1, sku="c")
            with patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads[:1], [])):
                greeting = asyncio.run(inbox_agent_service.answer("سلام"))
            self.assertEqual(greeting, "سلام، در خدمتم")
            self.assertEqual(seen, [])
            with patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads[1:2], [])):
                clean = asyncio.run(inbox_agent_service.answer("کفش هست؟"))
            with patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads[2:], [])):
                fake = asyncio.run(inbox_agent_service.answer("جنس چیست؟"))
        self.assertIn("چرم", clean or "")
        self.assertEqual(fake, inbox_agent_service.CLAIMS_LINE)
        self.assertEqual(seen[-1]["surface"], "inbox")
        self.assertNotIn("09120000000", seen[-1]["user"])
        self.assertIn("[تلفن]", seen[-1]["user"])

    def test_payment_tool_error_hands_off_instead_of_empty(self) -> None:
        from app.services import inbox_service

        payloads = [_chat(calls=[_call("payment_link", {"product": "کفش", "qty": 1})])]

        async def broken(*_args, **_kwargs):
            raise ValueError("درگاه سوزان هنوز تنظیم نشده.")

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])), patch(
            "app.services.inbox_agent_service.tool_payment_link", broken
        ):
            created = inbox_service.inbound(platform="instagram", sender="مشتری", text="لینک پرداخت")
            reply = asyncio.run(inbox_agent_service.answer("لینک پرداخت", thread=created["thread"]))
            shown = inbox_service.get_thread(created["thread"]["id"])
            waiting = inbox_service.list_threads(status_filter="pending")
        self.assertEqual(reply, inbox_agent_service.HANDOFF_LINE)
        self.assertTrue(shown["thread"]["paused"])
        self.assertEqual(shown["thread"]["handoffReason"], "خطای ابزار پرداخت")
        self.assertGreaterEqual(shown["thread"]["unread"], 1)
        self.assertTrue(any(row.get("handoffReason") == "خطای ابزار پرداخت" for row in waiting["threads"]))

    def test_exhausted_rounds_hand_off(self) -> None:
        from app.services import inbox_service

        payloads = [_chat(calls=[_call("stock", {"product": "کفش"}, call_id=f"c{i}")]) for i in range(4)]

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])):
            storefront_service.add_product(title="کفش چرم", price=10, stock=1, sku="c")
            created = inbox_service.inbound(platform="instagram", sender="مشتری", text="موجودی")
            reply = asyncio.run(inbox_agent_service.answer("موجودی", thread=created["thread"]))
            shown = inbox_service.get_thread(created["thread"]["id"])
        self.assertEqual(reply, inbox_agent_service.HANDOFF_LINE)
        self.assertEqual(shown["thread"]["handoffReason"], "دورها تمام شد")
        self.assertTrue(shown["thread"]["paused"])
        self.assertEqual(payloads, [])

    def test_tool_echo_skips_the_claims_model(self) -> None:
        payloads = [
            _chat(calls=[_call("stock", {"product": "کفش چرم"})]),
            _chat(content="کفش چرم موجود است."),
        ]
        self.claims_complete.reset_mock()

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])):
            storefront_service.add_product(title="کفش چرم", price=10, stock=2, sku="c")
            reply = asyncio.run(inbox_agent_service.answer("هست؟"))
        self.assertIn("موجود", reply or "")
        self.claims_complete.assert_not_called()

    def test_sold_out_claim_is_replaced_without_a_second_model(self) -> None:
        payloads = [
            _chat(calls=[_call("stock", {"product": "صندل"})]),
            _chat(content="صندل تابستانی موجود است."),
        ]
        self.claims_complete.reset_mock()

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])):
            storefront_service.add_product(title="صندل تابستانی", price=10, stock=0, sku="s")
            reply = asyncio.run(inbox_agent_service.answer("هست؟"))
        self.assertEqual(reply, inbox_agent_service.CLAIMS_LINE)
        self.claims_complete.assert_not_called()

    def test_dry_edge_mock_gateway_returns_a_fake_pay_link(self) -> None:
        payloads = [
            _chat(calls=[_call("payment_link", {"product": "کفش چرم", "qty": 1})]),
            _chat(content="لینک پرداخت اینجاست."),
        ]

        async def no_hint(_text: str) -> str:
            return ""

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])), patch(
            "app.services.inbox_agent_service.intent_hint", no_hint
        ), patch("app.services.arvan_dns_service.edge_dry", return_value=True), patch(
            "app.services.pay_service.create_order", new=AsyncMock()
        ) as create:
            storefront_service.add_product(title="کفش چرم", price=4000000, stock=2, sku="c")
            reply = asyncio.run(inbox_agent_service.answer("لینک پرداخت کفش را بفرست"))
        self.assertIn("dry-mock.invalid", reply or "")
        self.assertNotIn("zarinpal", reply or "")
        create.assert_not_called()

    def test_multi_product_message_does_not_open_payment(self) -> None:
        payloads = [
            _chat(calls=[_call("payment_link", {"product": "کفش", "qty": 1})]),
            _chat(content="هر دو کالا موجود است."),
        ]
        pay = AsyncMock()

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])), patch(
            "app.services.inbox_agent_service.tool_payment_link", pay
        ):
            storefront_service.add_product(title="کفش چرم مشکی", price=4000000, stock=2, sku="c")
            storefront_service.add_product(title="کمربند چرم", price=900000, stock=5, sku="b")
            reply = asyncio.run(inbox_agent_service.answer("هم کفش می‌خواهم هم کمربند"))
        self.assertIn("موجود", reply or "")
        self.assertNotEqual(reply, inbox_agent_service.HANDOFF_LINE)
        pay.assert_not_called()

    def test_shipping_uses_the_stored_policy_without_the_model(self) -> None:
        from app.state_store import write_json

        async def forbidden(**_kwargs):
            raise AssertionError("model")

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", forbidden):
            write_json("sales-policy.json", {"shippingMethod": "پست پیشتاز", "shippingCost": 60000})
            reply = asyncio.run(inbox_agent_service.answer("ارسال به شهرستان چقدر است؟"))
        self.assertIn("۶۰۰۰۰", reply or "")
        self.assertIn("پست پیشتاز", reply or "")

    def test_unset_return_policy_hands_off_without_the_model(self) -> None:
        from app.services import inbox_service

        async def forbidden(**_kwargs):
            raise AssertionError("model")

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", forbidden):
            created = inbox_service.inbound(platform="instagram", sender="مشتری", text="مرجوع")
            reply = asyncio.run(inbox_agent_service.answer("مهلت مرجوعی چند روز است؟", thread=created["thread"]))
            shown = inbox_service.get_thread(created["thread"]["id"])
        self.assertEqual(reply, inbox_agent_service.HANDOFF_LINE)
        self.assertEqual(shown["thread"]["handoffReason"], "سیاست ثبت نشده")

    def test_catalog_color_skips_the_claims_model(self) -> None:
        payloads = [_chat(content="رنگش طلایی است.")]
        self.claims_complete.reset_mock()

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", script_tools(payloads, [])):
            storefront_service.add_product(title="گوشواره", price=10, stock=2, sku="g", colors=["طلایی"])
            reply = asyncio.run(inbox_agent_service.answer("رنگ گوشواره چیست؟"))
        self.assertIn("طلایی", reply or "")
        self.claims_complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
