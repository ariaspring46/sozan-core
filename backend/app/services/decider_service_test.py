import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import decider_service, router_service
from app.services.shop_edit_service import hero_scene_prompt
from app.services.shop_service import stated_vertical
from app.state_store import tenant_scope, write_json


def setUpModule() -> None:
    global _VOICE
    _VOICE = []
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE.append(started)


def tearDownModule() -> None:
    while _VOICE:
        _VOICE.pop().stop()


def _decision(action: str, *, accepted: bool = True, frustrated: bool = False, ranked=None) -> dict:
    return {
        "action": action,
        "accepted": accepted,
        "probability": 0.91 if accepted else 0.4,
        "margin": 0.5 if accepted else 0.05,
        "effort": "normal",
        "refers_back": False,
        "frustrated": frustrated,
        "ranked": ranked or [],
        "observed": {},
    }


class DeciderParseTests(unittest.TestCase):
    def test_thresholds(self) -> None:
        choice, prob, margin, ok = decider_service.accept_action(
            {"choice": "hero_image", "probabilities": {"hero_image": 0.7, "edit_page": 0.2}}
        )
        self.assertTrue(ok)
        self.assertEqual(choice, "hero_image")
        self.assertGreaterEqual(prob, 0.6)
        self.assertGreaterEqual(margin, 0.2)
        _choice, _prob, _margin, low = decider_service.accept_action(
            {"choice": "hero_image", "probabilities": {"hero_image": 0.55, "edit_page": 0.4}}
        )
        self.assertFalse(low)

    def test_jewelry_vertical_from_a_broken_word(self) -> None:
        self.assertEqual(stated_vertical("کسخل ج.اهر فروشیه"), "jewelry")
        self.assertEqual(stated_vertical("سایت مربوط به جواهر فروشی است"), "jewelry")

    def test_yes_reads_the_real_response_shape(self) -> None:
        self.assertTrue(decider_service._yes(True))
        self.assertTrue(decider_service._yes({"answer": True}))
        self.assertTrue(decider_service._yes({"result": "yes"}))
        self.assertTrue(decider_service._yes({"probabilities": {"True": 0.8, "False": 0.2}}))
        self.assertFalse(decider_service._yes({"choice": "false"}))
        self.assertFalse(decider_service._yes(False))
        parsed = decider_service.read_decision(
            {
                "answers": {
                    "action": {"choice": "scan_page", "probabilities": {"scan_page": 0.9, "clarify": 0.05}},
                    "refers_back": True,
                    "frustrated": {"answer": False},
                }
            }
        )
        self.assertTrue(parsed["refers_back"])
        self.assertFalse(parsed["frustrated"])
        self.assertEqual(parsed["action"], "scan_page")

    def test_channel_actions_use_the_channel_tool(self) -> None:
        scan = decider_service.plan_for(
            "scan_page", "صفحه ی اینستاگرام من رو ببین sozan_core", frustrated=False, effort="quick"
        )
        self.assertEqual(scan["tool"], "channel")
        self.assertEqual(scan["arguments"]["action"], "scan")
        self.assertEqual(scan["arguments"]["platform"], "instagram")
        connect = decider_service.plan_for("connect_channel", "بریم تلگرام را وصل کنیم", frustrated=False, effort="quick")
        self.assertEqual(connect["arguments"]["action"], "connect")
        self.assertEqual(connect["arguments"]["platform"], "telegram")
        status = decider_service.plan_for("channel_status", "من وصل کردم", frustrated=False, effort="quick")
        self.assertEqual(status["arguments"]["action"], "status")

    def test_state_keeps_eight_turns_topic_and_channels(self) -> None:
        rows = []
        for index in range(10):
            rows.append({"role": "user", "text": f"پیام {index}"})
            rows.append({"role": "assistant", "text": f"جواب {index}"})
        rows.append({"role": "user", "text": "اینستاگرام را ببین"})
        accounts = {"accounts": [{"platform": "instagram", "handle": "sozan_core", "connected": True}]}
        scan = {"accounts": [{"platform": "instagram", "handle": "@sozan_core"}]}
        with patch("app.services.channel_service.list_accounts", return_value=accounts), patch(
            "app.services.channel_scan_service.get_scan", return_value=scan
        ):
            state = decider_service.state_from(rows, shop={"brand": "سوزان"}, card_open=False, last_post=False, media=None)
        self.assertEqual(len(state["previous_turns"]), 8)
        self.assertEqual(state["topic"]["topic"], "channel_scan")
        self.assertEqual(state["topic"]["platform"], "instagram")
        self.assertEqual(state["channels"][0]["handle"], "sozan_core")
        self.assertEqual(state["scanned_pages"], ["sozan_core"])

    def test_hero_prompt_uses_shop_tagline(self) -> None:
        with patch("app.services.shop_service.get_settings", return_value={"storeName": "", "storeTagline": ""}):
            prompt = hero_scene_prompt(
                {"brand": "سوزان", "tagline": "جواهر فروش و سنگ های گران قیمت"},
                "برای هدر",
            )
        self.assertIn("jewelry", prompt)


class DeciderTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(settings, "state_dir", self.tmp.name),
            patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")),
            patch("app.services.studio_publish_service.channel_block", return_value=""),
            patch.object(settings, "decider_enabled", False),
            patch.object(settings, "decider_tenants", "09129900001"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()
        router_service._THREAD.set("")

    def _turn(self, text: str, decider, *, media=None, complete=None, thread_id: str = ""):
        async def boom(_messages, _tools):
            raise AssertionError("chooser must not run")

        with tenant_scope("09129900001"):
            write_json("shop.json", {"slug": "sozan-shop", "status": "ready", "brand": "سوزان", "tagline": "جواهر", "url": "https://sozan.sozan-core.ir"})
            created = router_service.new_thread()
            tid = thread_id or str((created.get("threads") or [{}])[0].get("id") or "")
            return asyncio.run(
                router_service.turn(
                    text,
                    complete=complete or boom,
                    decider=decider,
                    media=media,
                    thread_id=tid,
                )
            )

    def test_ten_turns(self) -> None:
        cases = [
            ("از دیزاینش خوشم نمیاد میخوام از نو ساخته شه", "rebuild_shop", "shop_chat"),
            ("الان در چه مرحله ایه؟", "read_status", ""),
            ("تو توسط چه کسی ساخته شدی؟", "identity", ""),
            ("گردنبند را در استودیو بساز", "studio_image", "studio_chat"),
            ("برای این گردنبند یک تصویر تبلیغاتی جدا بساز", "studio_image", "studio_chat"),
            ("کسخل ج.اهر فروشیه", "correct_category", "shop_chat"),
            ("سایت مربوط به جواهر فروشی است", "correct_category", "shop_chat"),
            ("بیا برای هدر تصویر رو بسازیم", "hero_image", "edit_shop"),
        ]
        status = patch(
            "app.services.shop_service.snapshot",
            return_value={"shop": {"status": "ready", "slug": "sozan-shop", "cnameOk": True}, "scan": {}, "build": {"status": "ready"}},
        )
        with status, patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
            "app.services.plan_service.snapshot", return_value={"plan": "free"}
        ), patch("app.services.wallet_service.get", return_value={"available": 0}), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=__import__("pathlib").Path("/tmp")
        ):
            for index, (spoken, action, tool) in enumerate(cases):
                frustrated = action == "correct_category" and "کسخل" in spoken
                out = self._turn(
                    spoken,
                    AsyncMock(return_value=_decision(action, frustrated=frustrated)),
                    thread_id=f"t{index}",
                )
                if action == "identity":
                    self.assertIn("سوزان", out["messages"][-1]["text"])
                    continue
                if action == "read_status":
                    self.assertIsNone(out.get("pendingConfirm"))
                    self.assertIn("فروشگاه", out["messages"][-1]["text"])
                    continue
                self.assertEqual((out.get("pendingConfirm") or {}).get("tool"), tool, spoken)
                if action == "hero_image":
                    self.assertIn("هدر", out["pendingConfirm"]["summary"])
                if action == "correct_category":
                    from app.state_store import read_json

                    with tenant_scope("09129900001"):
                        self.assertEqual(read_json("shop.json", {}).get("vertical"), "jewelry")

    def test_low_margin_opens_chips(self) -> None:
        decision = _decision(
            "hero_image",
            accepted=False,
            ranked=[("hero_image", 0.42), ("edit_page", 0.4)],
        )
        with patch("app.services.shop_edit_service.build_dir_for", return_value=__import__("pathlib").Path("/tmp")):
            out = self._turn("یه چیزی برای بالا", AsyncMock(return_value=decision))
        last = out["messages"][-1]
        self.assertEqual(last.get("kind"), "ask")
        self.assertIn("تصویر هدر", last.get("options") or [])
        self.assertIn("ویرایش صفحه", last.get("options") or [])

    def test_api_down_uses_the_chooser(self) -> None:
        seen = []

        async def complete(_messages, _tools):
            seen.append(1)
            return {"text": "", "tool_calls": [{"name": "status", "arguments": {}}]}

        async def down(_state):
            return None

        with patch(
            "app.services.shop_service.snapshot",
            return_value={"shop": {"status": "ready", "slug": "sozan-shop"}, "scan": {}, "build": {}},
        ), patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
            "app.services.plan_service.snapshot", return_value={"plan": "free"}
        ), patch("app.services.wallet_service.get", return_value={"available": 0}):
            out = self._turn("الان کجای کاریم", down, complete=complete)
        self.assertEqual(seen, [1])
        self.assertIn("فروشگاه", out["messages"][-1]["text"])

    def test_media_turn_records_media_kind(self) -> None:
        seen = []

        async def decider(state):
            seen.append(state["media_kind"])
            return _decision("studio_image")

        out = self._turn("بیا برای هدر تصویر رو بسازیم", decider, media={"kind": "image"}, thread_id="media")
        self.assertEqual(seen, ["image"])
        self.assertEqual(out["pendingConfirm"]["tool"], "studio_chat")

    def test_shadow_does_not_change_the_reply_or_wait(self) -> None:
        async def slow(_state):
            await asyncio.sleep(2)
            return _decision("read_status")

        tasks: list[str] = []
        real = asyncio.create_task

        def spy(coro, *args, **kwargs):
            tasks.append(getattr(coro, "__name__", "") or coro.cr_code.co_name)
            coro.close()
            return real(asyncio.sleep(0))

        with patch.object(settings, "decider_enabled", False), patch(
            "app.services.decider_service.choose", new=slow
        ), patch("app.services.decider_service.asyncio.create_task", spy), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=__import__("pathlib").Path("/tmp")
        ):
            started = time.monotonic()
            out = self._turn("دوباره بساز", None)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.5)
        self.assertEqual(out["pendingConfirm"]["tool"], "shop_chat")
        self.assertIn("run", tasks)


if __name__ == "__main__":
    unittest.main()
