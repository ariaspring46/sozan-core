import unittest
from unittest.mock import patch

from app.services.llm import (
    _classify_llm_error,
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


if __name__ == "__main__":
    unittest.main()
