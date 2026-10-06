import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.services.llm import (
    _chat_completion,
    _choice_text,
    _classify_llm_error,
    _decorate_cloud_body,
    _ensure_gpu1,
    _tool_result,
    complete_tools,
    factory_holds_gpu1,
    parse_json_object,
    report_llm_fail,
    route_for_surface,
    spoken_model_reply,
    visible_chat_turns,
)


class ParseJsonTests(unittest.TestCase):
    def test_strips_think_fence_and_picks_object(self) -> None:
        raw = """<think>plan</think>
```json
{"reply":"سلام","brand":{"ctaLabelFa":"خرید"}}
```
"""
        data = parse_json_object(raw)
        self.assertEqual(data["reply"], "سلام")
        self.assertEqual(data["brand"]["ctaLabelFa"], "خرید")

    def test_skips_leading_double_brace(self) -> None:
        data = parse_json_object("{{\n  \"reply\": \"ok\"\n}")
        self.assertEqual(data.get("reply"), "ok")


class SpokenReplyTests(unittest.TestCase):
    def test_keeps_persian_json_reply(self) -> None:
        self.assertEqual(
            spoken_model_reply('{"reply":"رنگ دکمه عوض شد."}'),
            "رنگ دکمه عوض شد.",
        )

    def test_drops_english_chain_of_thought(self) -> None:
        raw = (
            "The user is asking me to look at the main page of the site and suggest improvements. "
            "Let me analyze the Next.js HomePage with Hero and StoryBand. "
            'The skin is "لوکس و خلوت".'
        )
        self.assertEqual(spoken_model_reply(raw), "مدل پاسخ خوانا نداد. پیام را کوتاه‌تر دوباره بفرست.")

    def test_choice_prefers_content_over_reasoning(self) -> None:
        text = _choice_text(
            {
                "choices": [
                    {
                        "message": {
                            "content": "رنگ دکمه عوض شد.",
                            "reasoning": "The user asked to change the button. Chain of thought.",
                        }
                    }
                ]
            }
        )
        self.assertEqual(text, "رنگ دکمه عوض شد.")
        self.assertNotIn("Chain of thought", text)
        self.assertEqual(spoken_model_reply(text), "رنگ دکمه عوض شد.")

    @staticmethod
    def _msg(content: str = "", reasoning: str = "") -> dict:
        return {"choices": [{"message": {"content": content, "reasoning_content": reasoning}, "finish_reason": "length"}]}

    def test_out_of_tokens_thinking_is_never_the_answer(self) -> None:
        # seen live 2026-10-04: Arvan GPT-OSS with the router's 150 tokens, content empty, the thinking went to the seller
        payload = self._msg("", 'The user wrote in Persian: "فروشگاهم کی آماده میشه". We need to answer briefly.')
        self.assertEqual(_choice_text(payload), "")

    def test_misplaced_persian_answer_in_reasoning_is_kept(self) -> None:
        self.assertEqual(_choice_text(self._msg("", "فروشگاهت تا چند دقیقهٔ دیگر آماده است.")), "فروشگاهت تا چند دقیقهٔ دیگر آماده است.")

    def test_raw_channel_format_keeps_only_the_final_answer(self) -> None:
        raw = (
            "<|channel|>analysis<|message|>User asks when the shop is ready.<|end|>"
            '<|start|>assistant<|channel|>final<|message|>{"reply":"تا چند دقیقهٔ دیگر آماده است."}<|return|>'
        )
        self.assertEqual(_choice_text(self._msg(raw)), '{"reply":"تا چند دقیقهٔ دیگر آماده است."}')
        self.assertEqual(_choice_text(self._msg("<|start|>assistant<|channel|>")), "")
        self.assertEqual(_choice_text(self._msg("<|channel|>analysis<|message|>Thinking only")), "")
        tool = _tool_result({"model": "GPT-OSS-120B"}, self._msg(raw), {})
        self.assertEqual(tool["text"], '{"reply":"تا چند دقیقهٔ دیگر آماده است."}')

    def test_gpt_oss_thinks_briefly_with_room_to_answer(self) -> None:
        body = {"model": "GPT-OSS-120B", "max_tokens": 150}
        _decorate_cloud_body(body, {"kind": "cloud", "url": "https://ai.sozan-core.ir/v1", "model": "GPT-OSS-120B"})
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertGreaterEqual(body["max_tokens"], 800)
        other = {"model": "deepseek/deepseek-v4.1-flash", "max_tokens": 150}
        _decorate_cloud_body(other, {"kind": "cloud", "url": "https://ai.sozan-core.ir/v1", "model": "deepseek/deepseek-v4.1-flash"})
        self.assertEqual(other, {"model": "deepseek/deepseek-v4.1-flash", "max_tokens": 150})


class ChatHistoryTests(unittest.TestCase):
    def test_drops_stale_edit_refusal(self) -> None:
        rows = visible_chat_turns(
            [
                {"role": "user", "text": "چه بهبودی پیشنهاد میدی؟"},
                {
                    "role": "assistant",
                    "text": "این پیام ویرایش فروشگاه نیست؛ المان را در پیش‌نمایش لمس کن.",
                },
                {"role": "user", "text": "سیستم ورود به چه شکل است؟"},
            ]
        )
        self.assertEqual([row["role"] for row in rows], ["user", "user"])
        self.assertIn("ورود", rows[1]["content"])

    def test_drops_foreign_url_user_turns(self) -> None:
        rows = visible_chat_turns(
            [
                {"role": "user", "text": "فوتر را https://evil.example/callback کن"},
                {"role": "assistant", "text": "این پیام ویرایش فروشگاه نیست."},
                {"role": "user", "text": "خب"},
            ]
        )
        self.assertEqual([row["content"] for row in rows], ["خب"])

    def test_router_keeps_user_links(self) -> None:
        rows = visible_chat_turns(
            [{"role": "user", "text": "اسکن https://instagram.com/shop"}],
            keep_links=True,
        )
        self.assertIn("instagram.com", rows[0]["content"])


def _route_settings(**extra) -> dict:
    values = {
        "local_llm_url": "http://127.0.0.1:9292/v1",
        "local_llm_model": "qwen3.8-27b",
        "local_llm_token": "sk-local",
        "chat_llm_model": "ornith-1.5-35b",
        "studio_llm_model": "qwen3.5-9b",
        "cloud_llm_url": "",
        "cloud_llm_model": "DeepSeek-V4-Pro",
        "cloud_llm_token": "",
        "cloud_llm_auth": "Bearer",
        "cloud_llm_proxy": "",
        "channel_proxy": "socks5h://127.0.0.1:10888",
        "studio_cloud_url": "",
        "studio_cloud_model": "Gemini-3.1-Flash-Lite-Preview",
        "studio_cloud_token": "",
        "studio_cloud_auth": "Bearer",
    }
    values.update(extra)
    return values


def _apply_settings(mock_settings, values: dict) -> None:
    for key, value in values.items():
        setattr(mock_settings, key, value)


class RouteSurfaceTests(unittest.TestCase):
    def _route(self, surface: str, **extra) -> dict:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ):
            _apply_settings(settings, _route_settings(**extra))
            return route_for_surface(surface)

    def test_six_surfaces_without_cloud_stay_local(self) -> None:
        expected = {
            "voice": "qwen3.8-27b",
            "inbox": "qwen3.5-9b",
            "shop": "ornith-1.5-35b",
            "shop-edit": "ornith-1.5-35b",
            "studio": "qwen3.5-9b",
            "factory": "ornith-1.5-35b",
        }
        for surface, model in expected.items():
            with self.subTest(surface=surface):
                route = self._route(surface)
                self.assertEqual(route["kind"], "local")
                self.assertEqual(route["model"], model)
                self.assertIsNone(route["proxy"])

    def test_six_surfaces_with_separate_clouds(self) -> None:
        extra = {
            "cloud_llm_url": "https://api.arvancloudai.ir/v1",
            "cloud_llm_token": "shop-secret",
            "cloud_llm_auth": "apikey",
            "studio_cloud_url": "https://studio.arvancloudai.ir/v1",
            "studio_cloud_token": "studio-secret",
            "studio_cloud_auth": "apikey",
        }
        shop = self._route("shop", **extra)
        edit = self._route("shop-edit", **extra)
        studio = self._route("studio", **extra)
        factory = self._route("factory", **extra)
        router = self._route("router", **extra)
        voice = self._route("voice", **extra)
        inbox = self._route("inbox", **extra)
        for route in (shop, edit, factory, router):
            self.assertEqual(route["kind"], "cloud")
            self.assertEqual(route["model"], "DeepSeek-V4-Pro")
            self.assertEqual(route["url"], "https://api.arvancloudai.ir/v1")
            self.assertIsNone(route["proxy"])
            self.assertEqual(route["auth"], "apikey")
            self.assertNotIn("shop-secret", str(route["url"]))
        self.assertEqual(studio["kind"], "cloud")
        self.assertEqual(studio["model"], "Gemini-3.1-Flash-Lite-Preview")
        self.assertEqual(studio["url"], "https://studio.arvancloudai.ir/v1")
        self.assertIsNone(studio["proxy"])
        self.assertEqual(studio["auth"], "apikey")
        self.assertNotIn("studio-secret", str(studio["url"]))
        self.assertEqual(voice["kind"], "local")
        self.assertEqual(voice["model"], "qwen3.8-27b")
        self.assertEqual(inbox["kind"], "cloud")
        self.assertEqual(inbox["model"], "DeepSeek-V4-Pro")
        self.assertEqual(inbox["url"], "https://api.arvancloudai.ir/v1")

    def test_inbox_ignores_a_gpu1_local_override(self) -> None:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get",
            return_value={"kind": "local", "model": "qwen3.8-27b"},
        ):
            _apply_settings(settings, _route_settings())
            route = route_for_surface("inbox")
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "qwen3.5-9b")

    def test_shop_cloud_does_not_move_studio(self) -> None:
        extra = {
            "cloud_llm_url": "https://api.arvancloudai.ir/v1",
            "cloud_llm_token": "shop-secret",
        }
        self.assertEqual(self._route("studio", **extra)["kind"], "local")
        self.assertEqual(self._route("shop", **extra)["kind"], "cloud")

    def test_studio_cloud_does_not_move_shop(self) -> None:
        extra = {
            "studio_cloud_url": "https://studio.arvancloudai.ir/v1",
            "studio_cloud_token": "studio-secret",
        }
        self.assertEqual(self._route("shop", **extra)["kind"], "local")
        self.assertEqual(self._route("studio", **extra)["kind"], "cloud")

    def test_voice_stays_on_27b(self) -> None:
        route = self._route(
            "voice",
            cloud_llm_url="https://api.arvancloudai.ir/v1",
            cloud_llm_token="secret",
            studio_cloud_url="https://studio.arvancloudai.ir/v1",
            studio_cloud_token="gemini",
        )
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "qwen3.8-27b")

    def test_shop_uses_ornith_without_cloud(self) -> None:
        route = self._route("shop-edit")
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "ornith-1.5-35b")

    def test_studio_stays_on_vulkan0_chat(self) -> None:
        route = self._route(
            "studio",
            cloud_llm_url="https://ollama.com/v1",
            cloud_llm_token="secret",
        )
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "qwen3.5-9b")
        self.assertEqual(route["source"], "default")

    def test_studio_ignores_gpu1_override(self) -> None:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get",
            return_value={"kind": "local", "model": "ornith-1.5-35b"},
        ), patch("app.services.llm_routing_service.provider", return_value={}):
            _apply_settings(settings, _route_settings())
            route = route_for_surface("studio")
        self.assertEqual(route["model"], "qwen3.5-9b")
        self.assertEqual(route["source"], "default")

    def test_factory_uses_flash_and_channel_proxy(self) -> None:
        route = self._route(
            "factory",
            cloud_llm_url="https://ollama.com/v1",
            cloud_llm_model="deepseek-v4.1-flash:cloud",
            cloud_llm_token="secret",
        )
        self.assertEqual(route["kind"], "cloud")
        self.assertEqual(route["model"], "deepseek-v4.1-flash:cloud")
        self.assertEqual(route["proxy"], "socks5h://127.0.0.1:10888")
        self.assertNotIn("secret", str(route["url"]))

    def test_arvan_shop_skips_channel_proxy(self) -> None:
        route = self._route(
            "shop",
            cloud_llm_url="https://api.arvancloudai.ir/v1",
            cloud_llm_token="secret",
            cloud_llm_proxy="socks5h://127.0.0.1:10801",
        )
        self.assertEqual(route["kind"], "cloud")
        self.assertIsNone(route["proxy"])


class CloudFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests exercise cloud routing, not the cost cap; keep cloud reachable.
        cap = patch("app.services.llm._budget_capped", return_value=None)
        cap.start()
        self.addCleanup(cap.stop)

    def _run(self, surface: str, handler, **extra):
        captured = {}

        class FakeClient:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                self.timeout = timeout
                self.trust_env = trust_env
                self.proxy = proxy
                FakeClient.seen.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                return handler(url, json, headers)

        FakeClient.seen = []

        titles: list[str] = []

        def fake_emit(**kw):
            titles.append(str(kw.get("title") or ""))
            captured.update(kw)
            captured["titles"] = titles

        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ), patch.dict(
            # env هاب fallback واقعی دارد؛ این کلاس مسیر arvan ساختگی خودش را می‌سنجد.
            os.environ,
            {"CLOUD_LLM_FALLBACK_URL": "", "CLOUD_LLM_FALLBACK_MODEL": "", "CLOUD_LLM_FALLBACK_TOKEN": ""},
            clear=False,
        ), patch("app.services.llm.httpx.AsyncClient", FakeClient), patch(
            "app.services.llm._ensure_gpu1", new=AsyncMock(side_effect=lambda model: model)
        ), patch("app.services.llm.emit_later", new=fake_emit), patch(
            "asyncio.sleep", new=AsyncMock()
        ):
            _apply_settings(settings, _route_settings(**extra))
            text = asyncio.run(
                _chat_completion(
                    messages=[{"role": "user", "content": "سلام"}],
                    temperature=0.2,
                    max_tokens=700,
                    surface=surface,
                )
            )
        return text, FakeClient.seen, captured

    @staticmethod
    def _json_ok(url: str, payload: dict) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=payload, request=request)

    @staticmethod
    def _http_error(url: str, status: int) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", url)
        response = httpx.Response(status, request=request)
        return httpx.HTTPStatusError("busy", request=request, response=response)

    def test_shop_falls_back_to_local_after_cloud_503(self) -> None:
        calls: list[str] = []

        def handler(url, body, headers):
            calls.append(url)
            if "arvancloudai.ir" in url:
                raise self._http_error(url, 503)
            return self._json_ok(url, {"choices": [{"message": {"content": '{"reply":"رنگ دکمه عوض شد."}'}}]})

        text, seen, captured = self._run(
            "shop",
            handler,
            cloud_llm_url="https://api.arvancloudai.ir/v1",
            cloud_llm_token="shop-secret",
        )
        self.assertIn("رنگ دکمه عوض شد", text)
        self.assertTrue(any("arvancloudai.ir" in url for url in calls))
        self.assertTrue(any("127.0.0.1:9292" in url for url in calls))
        self.assertIn("cloud-fallback", captured.get("titles") or [])
        self.assertTrue(all(item.trust_env is False for item in seen))
        self.assertTrue(all(item.timeout == 120 or item.proxy is None for item in seen))

    def test_studio_falls_back_to_local_after_gemini_503(self) -> None:
        calls: list[str] = []

        def handler(url, body, headers):
            calls.append(url)
            if "arvancloudai.ir" in url:
                raise self._http_error(url, 503)
            return self._json_ok(url, {"choices": [{"message": {"content": '{"reply":"پوستر آماده است."}'}}]})

        text, _, captured = self._run(
            "studio",
            handler,
            studio_cloud_url="https://studio.arvancloudai.ir/v1",
            studio_cloud_token="studio-secret",
        )
        self.assertIn("پوستر آماده است", text)
        self.assertTrue(any("studio.arvancloudai.ir" in url for url in calls))
        self.assertTrue(any("127.0.0.1:9292" in url for url in calls))
        self.assertIn("cloud-fallback", captured.get("titles") or [])

    def test_shop_cloud_uses_apikey_scheme_and_no_proxy(self) -> None:
        seen_headers = {}
        seen_body = {}
        proxies = []

        def handler(url, body, headers):
            seen_headers.update(headers)
            if isinstance(body, dict):
                seen_body.update(body)
            return self._json_ok(url, {"choices": [{"message": {"content": '{"reply":"انجام شد."}'}}]})

        text, seen, _ = self._run(
            "shop",
            handler,
            cloud_llm_url="https://api.arvancloudai.ir/v1",
            cloud_llm_token="shop-secret",
            cloud_llm_auth="apikey",
            cloud_llm_proxy="socks5h://127.0.0.1:10801",
        )
        self.assertIn("انجام شد", text)
        self.assertEqual(seen_headers.get("Authorization"), "apikey shop-secret")
        self.assertTrue(all(item.proxy is None for item in seen))
        self.assertTrue(all(item.timeout == 120 for item in seen))
        self.assertNotIn("shop-secret", str(proxies))
        self.assertIs(seen_body.get("think"), False)

    def test_router_cloud_failure_does_not_fall_back(self) -> None:
        calls: list[str] = []

        def handler(url, body, headers):
            calls.append(url)
            raise self._http_error(url, 503)

        with self.assertRaises(httpx.HTTPStatusError):
            self._run(
                "router",
                handler,
                cloud_llm_url="https://api.arvancloudai.ir/v1",
                cloud_llm_token="shop-secret",
            )
        self.assertTrue(any("arvancloudai.ir" in url for url in calls))
        self.assertFalse(any("127.0.0.1:9292" in url for url in calls))


class RouterToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests exercise cloud routing, not the cost cap; keep cloud reachable.
        cap = patch("app.services.llm._budget_capped", return_value=None)
        cap.start()
        self.addCleanup(cap.stop)

    def test_requires_cloud(self) -> None:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ):
            _apply_settings(settings, _route_settings())
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(complete_tools(messages=[{"role": "user", "content": "hi"}], tools=[]))
        self.assertIn("router_requires_cloud", str(ctx.exception))

    def test_parses_tool_calls(self) -> None:
        seen_body: dict = {}

        class FakeClient:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                self.timeout = timeout
                self.proxy = proxy

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen_body.update(json or {})
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "c1",
                                            "function": {"name": "status", "arguments": "{}"},
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                    request=request,
                )

        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ), patch("app.services.llm.httpx.AsyncClient", FakeClient):
            _apply_settings(
                settings,
                _route_settings(
                    cloud_llm_url="https://api.arvancloudai.ir/v1",
                    cloud_llm_token="shop-secret",
                ),
            )
            out = asyncio.run(
                complete_tools(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
            )
        self.assertEqual(out["tool_calls"][0]["name"], "status")
        self.assertEqual(seen_body.get("tool_choice"), "auto")
        self.assertEqual(seen_body.get("max_tokens"), 150)
        self.assertIs(seen_body.get("think"), False)
        self.assertTrue(seen_body.get("tools"))
        self.assertEqual(seen_body.get("model"), "DeepSeek-V4-Pro")


class OpenRouterCutoverTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests exercise cloud routing, not the cost cap; keep cloud reachable.
        cap = patch("app.services.llm._budget_capped", return_value=None)
        cap.start()
        self.addCleanup(cap.stop)

    def _client(self, seen: list):
        class FakeClient:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                self.timeout = timeout
                self.proxy = proxy

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen.append(
                    {
                        "url": url,
                        "timeout": self.timeout,
                        "proxy": self.proxy,
                        "body": json or {},
                        "auth": (headers or {}).get("Authorization"),
                    }
                )
                if "openrouter.ai" in url:
                    raise httpx.TimeoutException("late")
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    json={
                        "provider": "arvan",
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "tool_calls": [
                                        {"id": "c1", "function": {"name": "ask_user", "arguments": "{}"}}
                                    ],
                                }
                            }
                        ],
                    },
                    request=request,
                )

        return FakeClient

    def test_openrouter_body_key_and_ten_second_budget(self) -> None:
        seen: list = []

        class OkClient:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                self.timeout = timeout
                self.proxy = proxy

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen.append({"url": url, "timeout": self.timeout, "proxy": self.proxy, "body": json or {}, "auth": (headers or {}).get("Authorization")})
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    json={
                        "provider": "Together",
                        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "cost": 0.001},
                        "choices": [
                            {"message": {"tool_calls": [{"id": "c1", "function": {"name": "status", "arguments": "{}"}}]}}
                        ],
                    },
                    request=request,
                )

        extra = json.dumps(
            {"provider": {"sort": "latency", "ignore": ["Relace"], "allow_fallbacks": True}, "reasoning": {"enabled": False}}
        )
        env = {
            "open_router_api_token": "or-test-key",
            "CLOUD_LLM_EXTRA_BODY": extra,
            "CLOUD_LLM_FALLBACK_URL": "https://api.arvancloudai.ir/v1",
            "CLOUD_LLM_FALLBACK_MODEL": "GPT-OSS-120B",
            "CLOUD_LLM_FALLBACK_TOKEN": "arvan-test",
        }
        with patch.dict(os.environ, env), patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ), patch("app.services.llm.httpx.AsyncClient", OkClient), patch("app.services.llm.emit_later"):
            _apply_settings(
                settings,
                _route_settings(
                    cloud_llm_url="https://openrouter.ai/api/v1",
                    cloud_llm_model="deepseek/deepseek-v4.1-flash",
                    cloud_llm_token="should-not-use",
                ),
            )
            out = asyncio.run(complete_tools(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))
        self.assertEqual(seen[0]["auth"], "Bearer or-test-key")
        self.assertIsNone(seen[0]["proxy"])
        self.assertEqual(seen[0]["timeout"], 10)
        self.assertNotIn("think", seen[0]["body"])
        self.assertEqual(seen[0]["body"]["provider"]["ignore"], ["Relace"])
        self.assertIs(seen[0]["body"]["reasoning"]["enabled"], False)
        self.assertEqual(out["provider"], "Together")
        self.assertEqual(out["usage"]["cost"], 0.001)
        self.assertNotIn("or-test-key", seen[0]["url"])

    def test_timeout_then_arvan_fallback(self) -> None:
        seen: list = []
        titles: list[str] = []

        def emit(**kwargs):
            if kwargs.get("title") == "cloud-fallback":
                titles.append(str((kwargs.get("payload") or {}).get("reason") or ""))

        with patch.dict(
            os.environ,
            {
                "open_router_api_token": "or-test-key",
                "CLOUD_LLM_EXTRA_BODY": '{"reasoning":{"enabled":false}}',
                "CLOUD_LLM_FALLBACK_URL": "https://api.arvancloudai.ir/v1",
                "CLOUD_LLM_FALLBACK_MODEL": "GPT-OSS-120B",
                "CLOUD_LLM_FALLBACK_TOKEN": "arvan-test",
            },
        ), patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ), patch("app.services.llm.httpx.AsyncClient", self._client(seen)), patch(
            "app.services.llm.emit_later", new=emit
        ), patch("app.services.llm._ensure_gpu1", new=AsyncMock(side_effect=lambda model: model)):
            _apply_settings(
                settings,
                _route_settings(
                    cloud_llm_url="https://openrouter.ai/api/v1",
                    cloud_llm_model="deepseek/deepseek-v4.1-flash",
                    cloud_llm_token="should-not-use",
                ),
            )
            out = asyncio.run(complete_tools(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}], timeout=45))
        self.assertEqual(out["tool_calls"][0]["name"], "ask_user")
        self.assertEqual(seen[0]["timeout"], 10)
        self.assertIn("openrouter.ai", seen[0]["url"])
        self.assertIn("arvancloudai.ir", seen[1]["url"])
        self.assertIs(seen[1]["body"].get("think"), False)
        self.assertNotIn("provider", seen[1]["body"])
        self.assertEqual(titles, ["timeout"])
        self.assertEqual(len(seen), 2)

    def test_unauthorized_then_next_provider(self) -> None:
        seen: list[dict] = []

        class DeniedThenOk:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen.append({"url": url, "auth": (headers or {}).get("Authorization")})
                request = httpx.Request("POST", url)
                if "openrouter.ai" in url:
                    response = httpx.Response(401, request=request)
                    raise httpx.HTTPStatusError("denied", request=request, response=response)
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "tool_calls": [
                                        {"id": "c1", "function": {"name": "ask_user", "arguments": "{}"}}
                                    ],
                                }
                            }
                        ]
                    },
                    request=request,
                )

        with tempfile.TemporaryDirectory() as raw, patch.dict(
            os.environ,
            {
                "open_router_api_token": "",
                "CLOUD_LLM_FALLBACK_URL": "",
                "CLOUD_LLM_FALLBACK_MODEL": "",
                "CLOUD_LLM_FALLBACK_TOKEN": "",
                "CLOUD_LLM_FALLBACK_AUTH": "",
            },
        ), patch("app.services.llm.settings") as settings, patch(
            "app.state_store.settings"
        ) as state_settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ), patch("app.services.llm.httpx.AsyncClient", DeniedThenOk), patch(
            "app.services.llm.emit_later"
        ), patch("app.services.llm._ensure_gpu1", new=AsyncMock(side_effect=lambda model: model)):
            state_settings.state_path = Path(raw)
            _apply_settings(
                settings,
                _route_settings(
                    cloud_llm_url="https://openrouter.ai/api/v1",
                    cloud_llm_model="deepseek/deepseek-v4.1-flash",
                    cloud_llm_token="should-not-use",
                    open_router_api_token="or-from-settings",
                    cloud_llm_fallback_url="https://api.arvancloudai.ir/v1",
                    cloud_llm_fallback_model="GPT-OSS-120B",
                    cloud_llm_fallback_token="arvan-from-settings",
                ),
            )
            out = asyncio.run(complete_tools(messages=[{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))
        self.assertEqual(out["tool_calls"][0]["name"], "ask_user")
        self.assertIn("openrouter.ai", seen[0]["url"])
        self.assertIn("arvancloudai.ir", seen[1]["url"])
        self.assertEqual(seen[0]["auth"], "Bearer or-from-settings")
        self.assertEqual(seen[1]["auth"], "Bearer arvan-from-settings")
        self.assertEqual(len(seen), 2)

    def test_provider_auth_alert_once_per_hour(self) -> None:
        from app.services.llm import note_provider_denied

        emitted: list[str] = []

        def emit(**kwargs):
            if kwargs.get("title") == "provider-auth":
                emitted.append(str((kwargs.get("payload") or {}).get("code") or ""))

        with tempfile.TemporaryDirectory() as raw, patch("app.state_store.settings") as state_settings, patch(
            "app.services.llm.emit_later", new=emit
        ):
            state_settings.state_path = Path(raw)
            note_provider_denied("https://openrouter.ai/api/v1", 401)
            note_provider_denied("https://openrouter.ai/api/v1", 401)
        self.assertEqual(emitted, ["401"])


class ChatFailReportTests(unittest.TestCase):
    def test_timeout_classifies_and_emits_chat_failed(self) -> None:
        captured = {}

        def fake_emit_later(**kwargs):
            captured.update(kwargs)

        with patch("app.services.llm.emit_later", new=fake_emit_later):
            report_llm_fail(
                surface="shop",
                error_class="timeout",
                detail="TimeoutException: timed out",
                request_id="req-9",
                prompt="سلام",
            )
        self.assertEqual(captured["kind"], "llm")
        self.assertEqual(captured["title"], "chat-failed")
        self.assertEqual(captured["surface"], "shop")
        self.assertEqual(captured["status"], "failed")
        self.assertEqual(captured["payload"]["errorClass"], "timeout")
        self.assertEqual(captured["payload"]["requestId"], "req-9")

    def test_httpx_timeout_maps_to_timeout(self) -> None:
        import httpx

        self.assertEqual(_classify_llm_error(httpx.TimeoutException("late")), "timeout")
        self.assertEqual(_classify_llm_error(httpx.ConnectError("down")), "unreachable")


class Gpu1GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "queue" / "fastpath").mkdir(parents=True)
        self.settings = patch("app.services.llm.settings.site_builder_dir", str(self.root))
        self.settings.start()

    def tearDown(self) -> None:
        self.settings.stop()
        self.tmp.cleanup()

    def _phase(self, phase: str, age_sec: float = 0) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - age_sec))
        (self.root / "queue" / "phase.json").write_text(json.dumps({"phase": phase, "updatedAt": stamp}), encoding="utf-8")

    def _active(self, pid: int) -> None:
        (self.root / "queue" / "fastpath" / "ACTIVE").write_text(
            json.dumps({"id": "fp-1", "status": "running", "pid": pid}), encoding="utf-8"
        )

    def test_idle_factory_does_not_hold(self) -> None:
        self.assertEqual(factory_holds_gpu1(), "")
        self._phase("CHAT")
        self.assertEqual(factory_holds_gpu1(), "")

    def test_running_build_holds(self) -> None:
        self._active(os.getpid())
        self.assertEqual(factory_holds_gpu1(), "build:fp-1")

    def test_dead_build_pid_ignored(self) -> None:
        self._active(2147483646)
        self.assertEqual(factory_holds_gpu1(), "")

    def test_fresh_design_phase_holds_and_stale_does_not(self) -> None:
        self._phase("DESIGN_27B")
        self.assertEqual(factory_holds_gpu1(), "phase:DESIGN_27B")
        self._phase("DESIGN_27B", age_sec=3600)
        self.assertEqual(factory_holds_gpu1(), "")

    def test_idle_factory_evicts_other_gpu1_model(self) -> None:
        unload = AsyncMock()
        with patch("app.services.llm._running_models", new=AsyncMock(return_value={"qwen3.8-27b", "qwen3.5-9b"})), patch(
            "app.services.llm._unload_model", new=unload
        ):
            used = asyncio.run(_ensure_gpu1("ornith-1.5-35b"))
        self.assertEqual(used, "ornith-1.5-35b")
        unload.assert_awaited_once_with("qwen3.8-27b")

    def test_busy_factory_shares_27b_without_unload(self) -> None:
        self._active(os.getpid())
        unload = AsyncMock()
        captured = {}
        with patch("app.services.llm._running_models", new=AsyncMock(return_value={"qwen3.8-27b", "qwen3.5-9b"})), patch(
            "app.services.llm._unload_model", new=unload
        ), patch("app.services.llm.emit_later", new=lambda **kw: captured.update(kw)):
            used = asyncio.run(_ensure_gpu1("ornith-1.5-35b"))
        self.assertEqual(used, "qwen3.8-27b")
        unload.assert_not_awaited()
        self.assertEqual(captured["title"], "gpu1-busy")
        self.assertEqual(captured["payload"]["holder"], "build:fp-1")

    def test_busy_factory_falls_back_to_9b(self) -> None:
        self._phase("TRANSITION")
        unload = AsyncMock()
        with patch("app.services.llm._running_models", new=AsyncMock(return_value={"gpt-oss-20b", "qwen3.5-9b"})), patch(
            "app.services.llm._unload_model", new=unload
        ), patch("app.services.llm.emit_later", new=lambda **kw: None):
            used = asyncio.run(_ensure_gpu1("qwen3.8-27b"))
        self.assertEqual(used, "qwen3.5-9b")
        unload.assert_not_awaited()

    def test_requested_model_already_loaded_is_kept(self) -> None:
        self._active(os.getpid())
        with patch("app.services.llm._running_models", new=AsyncMock(return_value={"qwen3.8-27b", "qwen3.5-9b"})):
            self.assertEqual(asyncio.run(_ensure_gpu1("qwen3.8-27b")), "qwen3.8-27b")
        self.assertEqual(asyncio.run(_ensure_gpu1("qwen3.5-9b")), "qwen3.5-9b")


class InboxHopTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests exercise cloud routing, not the cost cap; keep cloud reachable.
        cap = patch("app.services.llm._budget_capped", return_value=None)
        cap.start()
        self.addCleanup(cap.stop)

    def _client(self, seen: list, *, fail_cloud: bool = False):
        class Client:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen.append({"url": url, "timeout": self.timeout, "model": (json or {}).get("model")})
                if fail_cloud and "ai.example" in url:
                    raise httpx.TimeoutException("late")
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "سلام"}}]},
                    request=request,
                )

        return Client

    def _run(self, seen: list, *, fail_cloud: bool = False) -> dict:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ), patch("app.services.llm.httpx.AsyncClient", self._client(seen, fail_cloud=fail_cloud)), patch(
            "app.services.llm.emit_later"
        ):
            _apply_settings(
                settings,
                _route_settings(
                    cloud_llm_url="https://ai.example/v1",
                    cloud_llm_model="GPT-OSS-120B",
                    cloud_llm_token="cloud-token",
                ),
            )
            return asyncio.run(
                complete_tools(messages=[{"role": "user", "content": "سلام"}], tools=[], surface="inbox")
            )

    def _chats(self, seen: list) -> list:
        return [row for row in seen if str(row.get("url") or "").endswith("/chat/completions")]

    def test_inbox_starts_on_the_cloud_within_fifteen_seconds(self) -> None:
        seen: list = []
        out = self._run(seen)
        chats = self._chats(seen)
        self.assertEqual(out["text"], "سلام")
        self.assertEqual(len(chats), 1)
        self.assertIn("ai.example", chats[0]["url"])
        self.assertEqual(chats[0]["model"], "GPT-OSS-120B")
        # the route has a proxy: 15 s overall, and only a few of them to connect through it (proxy_health)
        self.assertEqual(chats[0]["timeout"].read, 15)
        self.assertEqual(chats[0]["timeout"].connect, 4.0)
        self.assertNotIn("9292", chats[0]["url"])

    def test_inbox_uses_the_local_model_only_after_the_cloud_fails(self) -> None:
        seen: list = []
        out = self._run(seen, fail_cloud=True)
        chats = self._chats(seen)
        self.assertEqual(out["text"], "سلام")
        self.assertEqual(len(chats), 2)
        self.assertIn("ai.example", chats[0]["url"])
        self.assertIn("127.0.0.1:9292", chats[1]["url"])
        self.assertEqual(chats[1]["model"], "qwen3.5-9b")
        self.assertEqual(chats[1]["timeout"], 15)

    def test_openrouter_inbox_is_haiku_then_deepseek_then_9b(self) -> None:
        from app.services.llm import _inbox_hops

        cloud = {
            "kind": "cloud",
            "url": "https://openrouter.ai/api/v1",
            "model": "anthropic/claude-haiku-4.5",
            "token": "x",
            "source": "override",
        }
        extra = {
            "kind": "cloud",
            "url": "https://fallback.example/v1",
            "model": "GPT-OSS-120B",
            "token": "y",
            "source": "fallback",
        }
        local = {
            "kind": "local",
            "url": "http://127.0.0.1:9292/v1",
            "model": "qwen3.5-9b",
            "token": "",
            "source": "default",
        }
        with patch("app.services.llm.route_for_surface", return_value=cloud), patch(
            "app.services.llm._fallback_cloud_route", return_value=extra
        ), patch("app.services.llm._local_default_route", return_value=local):
            hops = _inbox_hops("inbox")
        self.assertEqual(
            [hop["model"] for hop in hops],
            ["anthropic/claude-haiku-4.5", "deepseek/deepseek-v4.1-flash", "qwen3.5-9b"],
        )


class ArvanOnlyFallbackTests(unittest.TestCase):
    CLOUD = {"kind": "cloud", "url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-v4.1-flash", "token": "x", "source": "override"}
    ARVAN = {"kind": "cloud", "url": "https://ai.sozan-core.ir/v1", "model": "GPT-OSS-120B", "token": "y", "source": "fallback"}
    LOCAL = {"kind": "local", "url": "http://127.0.0.1:9292/v1", "model": "qwen3.8-27b", "token": "", "source": "default"}

    def _run(self, env: dict, *, surface: str = "studio") -> tuple[object, list[str]]:
        calls: list[str] = []

        async def fake(route, **_kw):
            calls.append(str(route.get("model")))
            if route.get("kind") == "local":
                return "محلی"
            raise RuntimeError("cloud down")

        with (
            patch.dict(os.environ, env, clear=False),
            patch("app.services.llm.route_for_surface", return_value=self.CLOUD),
            patch("app.services.llm._fallback_cloud_route", return_value=self.ARVAN),
            patch("app.services.llm._local_default_route", return_value=self.LOCAL),
            patch("app.services.llm._budget_capped", return_value=None),
            patch("app.services.llm._complete_with_route", side_effect=fake),
        ):
            try:
                out: object = asyncio.run(
                    _chat_completion(messages=[{"role": "user", "content": "x"}], temperature=0.2, max_tokens=50, surface=surface)
                )
            except Exception as exc:
                out = exc
        return out, calls

    def test_default_still_ends_on_local(self) -> None:
        out, calls = self._run({"LLM_LOCAL_FALLBACK": "1"})
        self.assertEqual(out, "محلی")
        self.assertEqual(calls, ["deepseek/deepseek-v4.1-flash", "GPT-OSS-120B", "qwen3.8-27b"])

    def test_local_off_ends_at_arvan(self) -> None:
        out, calls = self._run({"LLM_LOCAL_FALLBACK": "0"})
        self.assertIsInstance(out, Exception)
        self.assertEqual(calls, ["deepseek/deepseek-v4.1-flash", "GPT-OSS-120B"])

    def test_arvan_fallback_host_skips_foreign_proxy(self) -> None:
        from app.config import settings
        from app.services.llm import _proxy_for_url, local_fallback_enabled

        with patch.dict(os.environ, {"CLOUD_LLM_FALLBACK_URL": "https://ai.sozan-core.ir/v1", "LLM_LOCAL_FALLBACK": "0"}), patch.object(
            settings, "channel_proxy", "socks5h://127.0.0.1:10888"
        ):
            self.assertIsNone(_proxy_for_url("https://ai.sozan-core.ir/v1"))
            self.assertEqual(_proxy_for_url("https://other.example/v1"), "socks5h://127.0.0.1:10888")
            self.assertFalse(local_fallback_enabled())


if __name__ == "__main__":
    unittest.main()
