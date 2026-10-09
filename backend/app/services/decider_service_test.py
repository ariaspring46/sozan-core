import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import decider_service, router_service
from app.services.shop_edit_service import hero_scene_prompt
from app.services.shop_service import stated_vertical
from app.state_store import read_json, tenant_scope, write_json


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
        self.assertTrue(parsed["loopEnough"])
        self.assertEqual(parsed["action"], "scan_page")
        closed = decider_service.read_decision(
            {"answers": {"action": {"choice": "read_status", "probabilities": {"read_status": 0.9}}, "loop_enough": {"choice": "false"}}}
        )
        self.assertFalse(closed["loopEnough"])
        self.assertEqual(closed["skill"], "none")
        picked = decider_service.read_decision(
            {
                "answers": {
                    "action": {"choice": "advise_live_site", "probabilities": {"advise_live_site": 0.9}},
                    "skill": {"choice": "ui-ux-pro-max"},
                }
            }
        )
        self.assertEqual(picked["skill"], "ui-ux-pro-max")
        self.assertEqual(decider_service.tool_names("read_status"), ["status"])
        self.assertEqual(decider_service.tool_names("studio_image"), ["studio_chat"])
        self.assertEqual(decider_service.tool_names("identity"), [])

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
        async def echo(_messages, tools):
            name = tools[0]["function"]["name"]
            return {"text": "", "tool_calls": [{"name": name, "arguments": {}}]}

        with tenant_scope("09129900001"):
            write_json("shop.json", {"slug": "sozan-shop", "status": "ready", "brand": "سوزان", "tagline": "جواهر", "url": "https://sozan.sozan-core.ir"})
            created = router_service.new_thread()
            tid = thread_id or str((created.get("threads") or [{}])[0].get("id") or "")
            return asyncio.run(
                router_service.turn(
                    text,
                    complete=complete or echo,
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

    def test_api_down_does_not_hand_every_tool_to_the_model(self) -> None:
        seen = []

        async def complete(_messages, tools):
            seen.append([item["function"]["name"] for item in tools])
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
        self.assertEqual(seen, [])
        self.assertIn("مدل پاسخ نداد", out["messages"][-1]["text"])

    def test_missing_photo_sentence_reads_then_opens_a_card(self) -> None:
        given: list[list[str]] = []
        seen: list[dict] = []

        async def decider(state):
            seen.append(state)
            if not state.get("lastTool"):
                return {**_decision("read_status"), "loopEnough": False}
            return {**_decision("studio_image"), "loopEnough": True}

        async def complete(_messages, tools):
            names = [item["function"]["name"] for item in tools]
            given.append(names)
            return {"text": "", "tool_calls": [{"name": names[0], "arguments": {}}]}

        with tenant_scope("09129900001"):
            write_json(
                "products.json",
                [
                    {"title": "ویترین", "image": "hero.jpg", "images": ["hero.jpg"]},
                    {"title": "انگشتر فیروزه", "image": "", "images": []},
                    {"title": "انگشتر نقره", "image": "", "images": []},
                ],
            )
        with patch(
            "app.services.shop_service.snapshot",
            return_value={"shop": {"status": "ready", "slug": "sozan-shop", "cnameOk": True}, "scan": {}, "build": {"status": "ready"}},
        ), patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
            "app.services.plan_service.snapshot", return_value={"plan": "promax"}
        ), patch("app.services.wallet_service.get", return_value={"available": 0}):
            out = self._turn("سایت من رو بررسی کن و جاهایی که عکس نداره براش عکس بساز", decider, complete=complete)
        self.assertEqual(given, [["status"], ["studio_chat"]])
        self.assertTrue(all(len(names) == 1 for names in given))
        self.assertIn("انگشتر فیروزه", str((seen[1].get("lastTool") or {}).get("text") or ""))
        self.assertIn("انگشتر نقره", str((seen[1].get("lastTool") or {}).get("text") or ""))
        self.assertEqual((out.get("pendingConfirm") or {}).get("tool"), "studio_chat")
        self.assertIn("انگشتر فیروزه", str((out.get("pendingConfirm") or {}).get("summary") or ""))
        self.assertIn("انگشتر نقره", str((out.get("pendingConfirm") or {}).get("summary") or ""))

    def test_website_advice_plans_then_loops_until_the_goal(self) -> None:
        modes: list[str] = []

        async def decider(state):
            return {
                **_decision("advise_live_site"),
                "loopEnough": False,
                "skill": "ui-ux-pro-max",
                "mode": "act",
                "goalReached": state.get("phase") == "act",
            }

        async def complete(_messages, tools):
            name = tools[0]["function"]["name"]
            return {"text": "", "tool_calls": [{"name": name, "arguments": {}}]}

        async def chat(text, media=None, view_path="", view_target="", confirmed=False, skill="", mode="", goal=""):
            modes.append(mode)
            if mode == "suggest":
                return {"assistant": {"role": "assistant", "text": "دکمه کم‌رنگ است."}}
            if mode == "revise":
                return {"assistant": {"role": "assistant", "text": "هدف: دکمهٔ ثبت سفارش مسی شود."}}
            return {"assistant": {"role": "assistant", "text": "دکمه مسی شد."}}

        with patch("app.services.shop_service.chat", new=chat):
            out = self._turn("برو سایت خودمون رو ببین و پیشنهاد بهبود بده", decider, complete=complete)
        self.assertEqual(modes, ["suggest", "revise", "act"])
        text = "\n".join(str(item.get("text") or "") for item in out["messages"])
        self.assertIn("پیشنهادها:", text)
        self.assertIn("پلن اصلاح:", text)
        self.assertIn("هدف: دکمهٔ ثبت سفارش مسی شود.", text)
        self.assertIn("دکمه مسی شد.", text)
        self.assertIsNone(out.get("pendingConfirm"))

    def test_low_sales_reaches_the_growth_skill_and_stores_one_plan(self) -> None:
        from app.services.shop_intent_service import classify_actions
        from app.services.skill_catalog import append_business_plan, load_business_plans, prompt_block

        block = prompt_block("ecommerce-growth-mba")[:800]
        self.assertIn("مسئله", block)
        self.assertIn("آزمایش", block)
        self.assertIn("داده نداریم", block)
        self.assertNotIn("جدول اولویت", block)
        self.assertEqual(router_service.decide("فروشم کمه", use_decider=True)["kind"], "model")
        self.assertFalse(router_service._wants_growth("قیمت انگشتر نقره را ۳ میلیون کن"))
        self.assertIn("انبار", classify_actions("قیمت انگشتر نقره را ۳ میلیون کن")[0]["reply"])

        prompts: list[str] = []

        async def decider(state):
            return {
                **_decision("advise_growth"),
                "loopEnough": False,
                "skill": "ecommerce-growth-mba",
                "goalReached": state.get("phase") == "act",
            }

        async def complete_chat(*, system, turns, surface="shop"):
            prompts.append(system)
            if "حالت تشخیص" in system:
                return "مسئله: بازدید داده نداریم.\n- عکس کالا ضعیف است"
            if "پلن اصلاح" in system:
                return "هدف: سنجهٔ بازدید ثبت شود.\nسنجه: تعداد بازدید"
            return "عدد بازدید را ثبت کن."

        with tenant_scope("09129900001"):
            write_json(
                "router-growth-keep-goal.json",
                {"goal": "دکمه مسی", "skill": "ui-ux-pro-max", "suggestions": "دکمه", "reached": False},
            )
            write_json("products.json", [{"title": "انگشتر فیروزه", "price": 500000, "stock": 1, "image": ""}])
        with patch("app.services.shop_service.complete_chat", new=complete_chat):
            out = self._turn("فروشم کمه. درآمد ماهانه‌ام ۱۸ میلیون است.", decider, thread_id="growth-keep")
        text = "\n".join(str(item.get("text") or "") for item in out["messages"])
        self.assertIn("داده نداریم", text)
        self.assertIn("هدف: سنجهٔ بازدید ثبت شود.", text)
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertTrue(prompts)
        self.assertIn("داده نداریم", prompts[0])
        self.assertNotIn("10000", prompts[0])
        self.assertNotIn("۱۰٬۰۰۰", prompts[0])
        self.assertIn("انبار", prompts[1])
        with tenant_scope("09129900001"):
            goal = read_json("router-growth-keep-goal.json", {})
            plans = load_business_plans()
            product = read_json("products.json", [])[0]
            self.assertEqual(goal.get("goal"), "دکمه مسی")
            self.assertEqual(goal.get("skill"), "ui-ux-pro-max")
            self.assertFalse(goal.get("reached"))
            self.assertEqual(plans["plans"][0]["experiment"], "سنجهٔ بازدید ثبت شود.")
            self.assertEqual(plans["plans"][0]["status"], "open")
            self.assertIn("۱۸", plans["stated"][0]["text"])
            self.assertEqual(product.get("price"), 500000)
            self.assertNotIn("۸۵۰", str(plans))

        with tenant_scope("09120000001"):
            append_business_plan(diagnosis="مسئله الف", revision="هدف: آزمایش الف", goal="آزمایش الف")
        with tenant_scope("09120000002"):
            append_business_plan(diagnosis="مسئله ب", revision="هدف: آزمایش ب", goal="آزمایش ب")
            self.assertEqual(load_business_plans()["plans"][0]["experiment"], "آزمایش ب")
        with tenant_scope("09120000001"):
            self.assertEqual(load_business_plans()["plans"][0]["experiment"], "آزمایش الف")

    def test_a_recorded_sale_is_in_the_diagnosis_and_not_copied_into_the_plan_file(self) -> None:
        from app.services.skill_catalog import load_business_plans

        prompts: list[str] = []

        async def decider(state):
            return {
                **_decision("advise_growth"),
                "loopEnough": False,
                "skill": "ecommerce-growth-mba",
                "goalReached": state.get("phase") == "act",
            }

        async def complete_chat(*, system, turns, surface="shop"):
            prompts.append(system)
            if "حالت تشخیص" in system:
                return "مسئله: بازدید داده نداریم."
            if "پلن اصلاح" in system:
                return "هدف: سنجهٔ بازدید ثبت شود."
            return "عدد بازدید را ثبت کن."

        with tenant_scope("09129900001"):
            write_json("sales.json", [{"title": "انگشتر", "amount": 850000, "at": 1}])
        with patch("app.services.shop_service.complete_chat", new=complete_chat):
            second = self._turn("فروشم کمه", decider, thread_id="growth-sale")
        self.assertIn("۸۵۰٬۰۰۰", prompts[0])
        self.assertIsNone(second.get("pendingConfirm"))
        with tenant_scope("09129900001"):
            self.assertNotIn("۸۵۰", str(load_business_plans()))
        again: list[str] = []

        async def complete_again(*, system, turns, surface="shop"):
            again.append(system)
            if "حالت تشخیص" in system:
                return "مسئله: همان سنجه مانده."
            if "پلن اصلاح" in system:
                return "هدف: همان سنجه بماند."
            return "منتظر عدد بازدید."

        with patch("app.services.shop_service.complete_chat", new=complete_again):
            self._turn("فروشم کمه", decider, thread_id="growth-sale")
        self.assertIn("سنجهٔ بازدید ثبت شود", again[0])

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
