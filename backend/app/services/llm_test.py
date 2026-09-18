import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services.llm import (
    _classify_llm_error,
    _ensure_gpu1,
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


class RouteSurfaceTests(unittest.TestCase):
    def test_voice_stays_on_27b(self) -> None:
        with patch("app.services.llm.settings") as settings:
            settings.local_llm_url = "http://127.0.0.1:9292/v1"
            settings.local_llm_model = "qwen3.8-27b"
            settings.local_llm_token = "sk-local"
            settings.chat_llm_model = "ornith-1.5-35b"
            settings.cloud_llm_url = "https://ollama.com/v1"
            settings.cloud_llm_model = "deepseek-v4.1-flash:cloud"
            settings.cloud_llm_token = "secret"
            settings.cloud_llm_proxy = ""
            settings.channel_proxy = "socks5h://127.0.0.1:10888"
            route = route_for_surface("voice")
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "qwen3.8-27b")

    def test_shop_uses_ornith(self) -> None:
        with patch("app.services.llm.settings") as settings:
            settings.local_llm_url = "http://127.0.0.1:9292/v1"
            settings.local_llm_model = "qwen3.8-27b"
            settings.local_llm_token = "sk-local"
            settings.chat_llm_model = "ornith-1.5-35b"
            settings.studio_llm_model = "qwen3.5-9b"
            settings.cloud_llm_url = "https://ollama.com/v1"
            settings.cloud_llm_model = "deepseek-v4.1-flash:cloud"
            settings.cloud_llm_token = "secret"
            settings.cloud_llm_proxy = ""
            settings.channel_proxy = "socks5h://127.0.0.1:10888"
            route = route_for_surface("shop-edit")
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "ornith-1.5-35b")

    def test_studio_stays_on_vulkan0_chat(self) -> None:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get", return_value=None
        ):
            settings.local_llm_url = "http://127.0.0.1:9292/v1"
            settings.local_llm_model = "qwen3.8-27b"
            settings.local_llm_token = "sk-local"
            settings.chat_llm_model = "ornith-1.5-35b"
            settings.studio_llm_model = "qwen3.5-9b"
            settings.cloud_llm_url = "https://ollama.com/v1"
            settings.cloud_llm_model = "deepseek-v4.1-flash:cloud"
            settings.cloud_llm_token = "secret"
            settings.cloud_llm_proxy = ""
            settings.channel_proxy = "socks5h://127.0.0.1:10888"
            route = route_for_surface("studio")
        self.assertEqual(route["kind"], "local")
        self.assertEqual(route["model"], "qwen3.5-9b")
        self.assertEqual(route["source"], "default")

    def test_studio_ignores_gpu1_override(self) -> None:
        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get",
            return_value={"kind": "local", "model": "ornith-1.5-35b"},
        ), patch("app.services.llm_routing_service.provider", return_value={}):
            settings.local_llm_url = "http://127.0.0.1:9292/v1"
            settings.local_llm_model = "qwen3.8-27b"
            settings.local_llm_token = "sk-local"
            settings.chat_llm_model = "ornith-1.5-35b"
            settings.studio_llm_model = "qwen3.5-9b"
            settings.cloud_llm_url = ""
            settings.cloud_llm_model = ""
            settings.cloud_llm_token = ""
            settings.cloud_llm_proxy = ""
            settings.channel_proxy = ""
            route = route_for_surface("studio")
        self.assertEqual(route["model"], "qwen3.5-9b")
        self.assertEqual(route["source"], "default")

    def test_factory_uses_flash_and_channel_proxy(self) -> None:
        with patch("app.services.llm.settings") as settings:
            settings.local_llm_url = "http://127.0.0.1:9292/v1"
            settings.local_llm_model = "qwen3.8-27b"
            settings.local_llm_token = "sk-local"
            settings.chat_llm_model = "ornith-1.5-35b"
            settings.cloud_llm_url = "https://ollama.com/v1"
            settings.cloud_llm_model = "deepseek-v4.1-flash:cloud"
            settings.cloud_llm_token = "secret"
            settings.cloud_llm_proxy = ""
            settings.channel_proxy = "socks5h://127.0.0.1:10888"
            route = route_for_surface("factory")
        self.assertEqual(route["kind"], "cloud")
        self.assertEqual(route["model"], "deepseek-v4.1-flash:cloud")
        self.assertEqual(route["proxy"], "socks5h://127.0.0.1:10888")
        self.assertNotIn("secret", str(route["url"]))


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
        with patch("app.services.llm._running_models", new=AsyncMock(return_value={"muse-glimmer-30b", "qwen3.5-9b"})), patch(
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


if __name__ == "__main__":
    unittest.main()
