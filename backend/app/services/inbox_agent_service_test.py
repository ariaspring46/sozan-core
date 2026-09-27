import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class FallbackClient:
    def __init__(self, seen: list):
        self.seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        self.seen.append({"url": url, "model": (json or {}).get("model")})
        if "9292" in url:
            raise httpx.ConnectError("down")
        return _response(_chat(content="از مسیر ابر: موجود است."))


class InboxAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        inbox_agent_service.clear_intent_cache()

    def tearDown(self) -> None:
        self.dir.cleanup()
        inbox_agent_service.clear_intent_cache()

    def test_stock_uses_local_9b_and_quotes_catalog(self) -> None:
        seen: list = []
        payloads = [
            _chat(calls=[_call("stock", {"product": "کفش چرم"})]),
            _chat(content="کفش چرم مشکی دو عدد موجود است و قیمتش چهار میلیون تومان است."),
        ]

        def client(*args, **kwargs):
            self.assertIsNone(kwargs.get("proxy"))
            self.assertFalse(kwargs.get("trust_env"))
            return ScriptedClient(payloads, seen)

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch.object(
            settings, "local_llm_url", "http://127.0.0.1:9292/v1"
        ), patch(
            "app.services.llm.inbox_hops",
            return_value=[{"kind": "local", "url": "http://127.0.0.1:9292/v1", "model": "qwen3.5-9b", "token": ""}],
        ), patch("app.services.inbox_agent_service.emit_later"), patch(
            "app.services.inbox_agent_service.httpx.AsyncClient", client
        ):
            storefront_service.add_product(title="کفش چرم مشکی", price=4000000, stock=2, sku="a")
            reply = asyncio.run(inbox_agent_service.answer("کفش چرم موجود است؟", thread={"sender": "علی"}))
        self.assertIn("دو عدد", reply or "")
        self.assertEqual(seen[0]["body"]["model"], "qwen3.5-9b")
        self.assertTrue(all("9292" in row["url"] for row in seen))
        self.assertTrue(seen[0]["url"].startswith("http://127.0.0.1:9292/v1/"))
        self.assertNotIn("arvan", seen[0]["url"])
        tool_blob = seen[1]["body"]["messages"][-1]["content"]
        self.assertIn("4000000", tool_blob)
        self.assertIn('"stock": 2', tool_blob)

    def test_chat_cloud_is_first_and_local_is_last(self) -> None:
        seen: list = []

        class CloudFirst:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen.append({"url": url, "model": (json or {}).get("model")})
                if "openrouter.ai" in url:
                    raise httpx.ConnectError("cloud-down")
                return _response(_chat(content="از مدل محلی: موجود است."))

        route = {
            "kind": "cloud",
            "url": "https://openrouter.ai/api/v1",
            "token": "test-token",
            "model": "deepseek/deepseek-v4.1-flash",
        }
        with patch.object(settings, "local_llm_url", "http://127.0.0.1:9292/v1"), patch(
            "app.services.llm.inbox_hops",
            return_value=[route, {"kind": "local", "url": "http://127.0.0.1:9292/v1", "model": "qwen3.5-9b", "token": ""}],
        ), patch("app.services.inbox_agent_service.httpx.AsyncClient", lambda *args, **kwargs: CloudFirst()):
            text, calls = asyncio.run(
                inbox_agent_service._complete([{"role": "user", "content": "موجود است؟"}])
            )
        self.assertEqual(calls, [])
        self.assertIn("موجود است", text)
        self.assertIn("openrouter.ai", seen[0]["url"])
        self.assertEqual(seen[0]["model"], "deepseek/deepseek-v4.1-flash")
        self.assertIn("9292", seen[1]["url"])
        self.assertEqual(seen[1]["model"], "qwen3.5-9b")

    def test_local_failure_without_cloud_stays_failed(self) -> None:
        seen: list = []

        def client(*args, **kwargs):
            return FallbackClient(seen)

        with patch.object(settings, "local_llm_url", "http://127.0.0.1:9292/v1"), patch(
            "app.services.llm.inbox_hops",
            return_value=[{"kind": "local", "url": "http://127.0.0.1:9292/v1", "model": "qwen3.5-9b", "token": ""}],
        ), patch("app.services.inbox_agent_service.httpx.AsyncClient", client):
            with self.assertRaises(httpx.ConnectError):
                asyncio.run(inbox_agent_service._complete([{"role": "user", "content": "سلام"}]))
        self.assertEqual(len(seen), 1)

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

        def client(*args, **kwargs):
            return ScriptedClient(payloads, seen)

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.httpx.AsyncClient", client):
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

        def client(*args, **kwargs):
            return ScriptedClient(payloads, seen)

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.httpx.AsyncClient", client), patch(
            "app.services.pay_service.create_order", new=fake_order
        ):
            storefront_service.add_product(title="کیف دوشی", price=1000, stock=1, sku="b")
            reply = asyncio.run(inbox_agent_service.answer("لینک پرداخت کیف را بفرست"))
        self.assertIn("https://api.sozan-core.ir/p/abc", reply or "")
        blob = seen[1]["body"]["messages"][-1]["content"]
        self.assertNotIn("SECRET", blob)

    def test_arvan_base_is_refused(self) -> None:
        posted = []

        def client(*args, **kwargs):
            posted.append(True)
            return ScriptedClient([], [])

        with patch.object(settings, "local_llm_url", "https://api.arvancloudai.ir/v1"), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.httpx.AsyncClient", client):
            reply = asyncio.run(inbox_agent_service.answer("سلام، موجود است این کالا؟"))
        self.assertIsNone(reply)
        self.assertEqual(posted, [])

    def test_embed_nudge_stays_on_local_bge(self) -> None:
        seen: list = []
        payloads = [
            _chat(content="بگذارید بررسی کنم و برگردم خدمتتان."),
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
            _chat(calls=[_call("stock", {"product": "کفش"})]),
            _chat(content="کفش چرم یک عدد در انبار است."),
        ]

        def client(*args, **kwargs):
            return ScriptedClient(payloads, seen)

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch.object(
            settings, "local_llm_url", "http://127.0.0.1:9292/v1"
        ), patch("app.services.inbox_agent_service.emit_later"), patch(
            "app.services.inbox_agent_service.httpx.AsyncClient", client
        ):
            storefront_service.add_product(title="کفش چرم", price=10, stock=1, sku="c")
            reply = asyncio.run(inbox_agent_service.answer("این کفش هنوز هست؟"))
        self.assertIn("یک عدد", reply or "")
        embed = next(row for row in seen if row["url"].endswith("/embeddings"))
        self.assertEqual(embed["body"]["model"], "bge-m3")
        self.assertNotIn("arvan", embed["url"])
        self.assertTrue(any("ابزار stock" in str(row["body"]) for row in seen))


if __name__ == "__main__":
    unittest.main()
