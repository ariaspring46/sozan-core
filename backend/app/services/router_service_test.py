from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import router_service
from app.state_store import tenant_scope, write_json


class RouterServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.embed_off = patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value=""))
        self.patches = [patch.object(settings, "state_dir", self.tmp.name), self.embed_off]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()
        router_service._THREAD.set("")

    def _turn(
        self,
        text: str,
        complete,
        confirm_id: str = "",
        cancel_id: str = "",
        campaigns=None,
        media=None,
        thread_id: str = "",
        embed=None,
    ):
        with tenant_scope("09129900001"):
            return asyncio.run(
                router_service.turn(
                    text,
                    confirm_id=confirm_id,
                    cancel_id=cancel_id,
                    complete=complete,
                    campaigns=campaigns,
                    media=media,
                    thread_id=thread_id,
                    embed=embed,
                )
            )

    def test_read_status_no_confirm(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "status", "arguments": {}}]}

        with patch(
            "app.services.shop_service.snapshot",
            return_value={
                "shop": {"status": "ready", "slug": "demo", "cnameOk": True},
                "scan": {"status": "done"},
                "build": {"status": "ready"},
            },
        ), patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
            "app.services.plan_service.snapshot", return_value={"plan": "free"}
        ), patch("app.services.wallet_service.get", return_value={"available": 12000}):
            out = self._turn("وضعیت؟", complete)
        last = out["messages"][-1]
        self.assertEqual(last["role"], "assistant")
        self.assertIn("فروشگاه", last["text"])
        self.assertIsNone(out.get("pendingConfirm"))

    def test_write_without_confirm_is_held(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_auto_reply", "arguments": {"mode": "draft"}}]}

        with patch("app.services.inbox_service.save_auto_reply") as save:
            out = self._turn("پاسخ خودکار پیش‌نویس شود", complete)
        save.assert_not_called()
        self.assertTrue(out["pendingConfirm"]["id"])
        self.assertEqual(out["pendingConfirm"]["tool"], "set_auto_reply")
        self.assertIn("پیش‌نویس", out["messages"][-1]["text"])
        self.assertEqual(out["messages"][-1].get("kind"), "confirm")

    def test_write_runs_after_confirm(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_auto_reply", "arguments": {"mode": "draft"}}]}

        first = self._turn("پاسخ خودکار پیش‌نویس شود", complete)
        cid = first["pendingConfirm"]["id"]
        with patch("app.services.inbox_service.save_auto_reply") as save:
            out = self._turn("", complete, confirm_id=cid)
        save.assert_called_once_with("draft")
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("به‌روز", out["messages"][-1]["text"])

    def test_shop_passthrough(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "shop_chat", "arguments": {"text": "بساز"}}]}

        with patch(
            "app.services.shop_service.chat",
            new=AsyncMock(return_value={"messages": [{"role": "assistant", "text": "ساخت شروع شد."}]}),
        ) as chat:
            out = self._turn("بساز", complete)
        chat.assert_awaited()
        self.assertEqual(chat.await_args.args[0], "بساز")
        self.assertEqual(out["messages"][-1]["text"], "ساخت شروع شد.")
        self.assertIsNone(out.get("pendingConfirm"))

    def test_live_edit_confirms_before_shop_edit(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "shop_chat", "arguments": {}}]}

        edit = AsyncMock(return_value={"ok": True, "reply": "رنگ فروشگاه عوض شد."})
        with patch("app.services.shop_edit_service.build_dir_for", return_value=Path("/tmp")), patch(
            "app.services.shop_edit_service.apply_live_edit", new=edit
        ), patch("app.services.shop_service.chat", new=AsyncMock()) as chat:
            held = self._turn("دکمه را زرشکی کن", complete)
            chat.assert_not_called()
            edit.assert_not_called()
            self.assertEqual(held["pendingConfirm"]["tool"], "edit_shop")
            self.assertIn("رنگ", held["messages"][-1]["text"])
            cid = held["pendingConfirm"]["id"]
            out = self._turn("", complete, confirm_id=cid)
        edit.assert_awaited()
        self.assertEqual(edit.await_args.args[1], "دکمه را زرشکی کن")
        self.assertEqual(out["messages"][-1]["text"], "رنگ فروشگاه عوض شد.")
        chat.assert_not_called()

    def test_edit_without_storefront_does_not_pretend(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "edit_shop", "arguments": {}}]}

        with patch("app.services.shop_edit_service.build_dir_for", return_value=None), patch(
            "app.services.shop_edit_service.apply_live_edit", new=AsyncMock()
        ) as edit:
            out = self._turn("دکمه را زرشکی کن", complete)
        edit.assert_not_called()
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("ویترین هنوز نیست", out["messages"][-1]["text"])

    def test_add_product_confirms_then_writes_catalog(self) -> None:
        from app.services import storefront_service

        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "add_product", "arguments": {"price": 1}}]}

        with patch("app.services.shop_service.chat", new=AsyncMock()) as chat:
            held = self._turn("کفش چرم مشکی را اضافه کن، قیمت ۴٬۸۰۰٬۰۰۰ تومان", complete)
            chat.assert_not_called()
            self.assertEqual(held["pendingConfirm"]["tool"], "add_product")
            self.assertIn("4800000", held["messages"][-1]["text"])
            with tenant_scope("09129900001"):
                self.assertEqual(storefront_service.list_products().get("products"), [])
            cid = held["pendingConfirm"]["id"]
            out = self._turn("", complete, confirm_id=cid)
            with tenant_scope("09129900001"):
                products = storefront_service.list_products().get("products") or []
        self.assertEqual(len(products), 1)
        self.assertEqual(int(products[0]["price"]), 4800000)
        self.assertIn("4800000", out["messages"][-1]["text"])
        self.assertNotIn("اضافه شد", out["messages"][-1]["text"])
        chat.assert_not_called()

    def test_add_product_without_price_asks_and_skips_confirm(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "add_product", "arguments": {"price": 4800000}}]}

        with patch("app.services.shop_service._catalog_add_reply", return_value="نباید") as write:
            out = self._turn("کفش چرم مشکی را اضافه کن", complete)
        write.assert_not_called()
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("قیمت", out["messages"][-1]["text"])
        self.assertNotIn("اضافه شد", out["messages"][-1]["text"])

    def test_studio_passthrough(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "studio_chat", "arguments": {"text": "پوستر بساز"}}]}

        campaigns = object()
        chat = AsyncMock(
            return_value={
                "messages": [
                    {
                        "id": "m1",
                        "role": "assistant",
                        "text": "پوستر آماده است.",
                        "campaignId": "c1",
                        "compose": {"status": "running"},
                        "captions": {"instagram": "کپشن"},
                    }
                ]
            }
        )
        with patch("app.services.studio_chat_service.chat", new=chat):
            held = self._turn("پوستر بساز", complete, campaigns=campaigns)
            chat.assert_not_called()
            self.assertEqual(held["pendingConfirm"]["tool"], "studio_chat")
            self.assertIn("پست ساخته شود", held["messages"][-1]["text"])
            cid = held["pendingConfirm"]["id"]
            out = self._turn("", complete, confirm_id=cid, campaigns=campaigns)
        chat.assert_awaited_once()
        self.assertEqual(chat.await_args.args[0], "پوستر بساز")
        last = out["messages"][-1]
        self.assertEqual(last["text"], "پوستر آماده است.")
        self.assertEqual(last["campaignId"], "c1")
        self.assertEqual(last["studioMessageId"], "m1")
        self.assertEqual(last["compose"]["status"], "running")
        with tenant_scope("09129900001"):
            write_json(
                "studio-messages.json",
                [
                    {
                        "id": "m1",
                        "role": "assistant",
                        "text": "تصویر آماده شد.",
                        "campaignId": "c1",
                        "compose": {"status": "done"},
                        "attachments": [{"kind": "image", "name": "x.jpg"}],
                    }
                ],
            )
            snap = router_service.snapshot()
        fresh = snap["messages"][-1]
        self.assertEqual(fresh["text"], "تصویر آماده شد.")
        self.assertEqual(fresh["compose"]["status"], "done")
        self.assertEqual(fresh["attachments"][0]["name"], "x.jpg")

    def test_one_tool_round(self) -> None:
        async def complete(_messages, _tools):
            return {
                "text": "",
                "tool_calls": [
                    {"name": "status", "arguments": {}},
                    {"name": "set_auto_reply", "arguments": {"mode": "send"}},
                ],
            }

        with patch("app.services.inbox_service.save_auto_reply") as save:
            out = self._turn("همه را بگو", complete)
        save.assert_not_called()
        self.assertEqual(out["pendingConfirm"]["tool"], "set_auto_reply")
        self.assertEqual(out["messages"][-1].get("kind"), "confirm")

    def test_ask_user_keeps_options(self) -> None:
        async def complete(_messages, _tools):
            return {
                "text": "",
                "tool_calls": [
                    {
                        "name": "ask_user",
                        "arguments": {
                            "question": "دامنه را چطور می‌خواهی؟",
                            "options": ["دامنه شخصی", "ساب‌دامین سوزان"],
                        },
                    }
                ],
            }

        out = self._turn("دامنه می‌خواهم", complete)
        last = out["messages"][-1]
        self.assertEqual(last.get("kind"), "ask")
        self.assertEqual(last.get("options"), ["دامنه شخصی", "ساب‌دامین سوزان"])

    def test_llm_failure_persian(self) -> None:
        async def complete(_messages, _tools):
            raise RuntimeError("cloud down")

        out = self._turn("سلام", complete)
        self.assertIn("مدل پاسخ نداد", out["messages"][-1]["text"])

    def test_daily_cap_persian(self) -> None:
        async def complete(_messages, _tools):
            raise AssertionError("llm should not run")

        with tenant_scope("09129900001"):
            write_json(
                "router-usage.json",
                {"day": time.strftime("%Y-%m-%d"), "turns": 80, "promptTokens": 0, "completionTokens": 0},
            )
        out = self._turn("سلام", complete)
        self.assertIn("برای امروز کافی", out["messages"][-1]["text"])

    def test_cancel_drops_pending(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_voice_tone", "arguments": {"toneId": "formal"}}]}

        first = self._turn("لحن رسمی", complete)
        self.assertIn("رسمی", first["messages"][-1]["text"])
        self.assertNotIn("formal", first["messages"][-1]["text"])
        cid = first["pendingConfirm"]["id"]
        with patch("app.services.voice_service.apply_tone") as apply:
            out = self._turn("", complete, cancel_id=cid)
        apply.assert_not_called()
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("انجامش نمی‌دهم", out["messages"][-1]["text"])

    def test_passthrough_exception_stays_persian(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "shop_chat", "arguments": {"text": "دکمه"}}]}

        with patch(
            "app.services.shop_service.chat",
            new=AsyncMock(side_effect=RuntimeError("/tmp/secret-trace")),
        ):
            out = self._turn("دکمه", complete)
        text = out["messages"][-1]["text"]
        self.assertIn("انجام نشد", text)
        self.assertNotIn("secret-trace", text)
        self.assertNotIn("RuntimeError", text)

    def test_new_text_keeps_pending(self) -> None:
        async def complete(_messages, _tools):
            raise AssertionError("llm should not run")

        async def opening(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_auto_reply", "arguments": {"mode": "draft"}}]}

        first = self._turn("پیش‌نویس کن", opening)
        cid = first["pendingConfirm"]["id"]
        out = self._turn("بله", complete)
        self.assertEqual(out["pendingConfirm"]["id"], cid)
        self.assertIn("تأیید", out["messages"][-1]["text"])

    def test_unknown_tone_is_not_warm(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_voice_tone", "arguments": {"toneId": "nope"}}]}

        with patch("app.services.voice_service.apply_tone") as apply:
            out = self._turn("لحن عجیب", complete)
        apply.assert_not_called()
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("نمی‌شناسم", out["messages"][-1]["text"])
        with tenant_scope("09129900001"):
            from app.services import voice_service

            with self.assertRaises(ValueError):
                voice_service.apply_tone("nope")

    def test_confirm_tone_uses_exact_id(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_voice_tone", "arguments": {"toneId": "formal"}}]}

        first = self._turn("لحن رسمی", complete)
        cid = first["pendingConfirm"]["id"]
        with patch("app.services.voice_service.apply_tone") as apply:
            out = self._turn("", complete, confirm_id=cid)
        apply.assert_called_once_with("formal")
        self.assertIsNone(out.get("pendingConfirm"))

    def test_failed_confirm_keeps_pending(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_auto_reply", "arguments": {"mode": "draft"}}]}

        first = self._turn("پیش‌نویس", complete)
        cid = first["pendingConfirm"]["id"]
        with patch("app.services.inbox_service.save_auto_reply", side_effect=ValueError("این حالت پاسخ خودکار نیست")):
            out = self._turn("", complete, confirm_id=cid)
        self.assertEqual(out["pendingConfirm"]["id"], cid)
        self.assertIn("این حالت پاسخ خودکار نیست", out["messages"][-1]["text"])
        with patch("app.services.inbox_service.save_auto_reply", side_effect=ValueError("boom /tmp/secret-trace")):
            hidden = self._turn("", complete, confirm_id=cid)
        self.assertEqual(hidden["pendingConfirm"]["id"], cid)
        self.assertIn("انجام نشد", hidden["messages"][-1]["text"])
        self.assertNotIn("secret-trace", hidden["messages"][-1]["text"])

    def test_attachment_is_stored_and_link_reaches_model(self) -> None:
        seen: dict = {}

        async def complete(messages, _tools):
            seen["messages"] = messages
            return {"text": "دیدم", "tool_calls": []}

        out = self._turn(
            "اسکن https://instagram.com/shop",
            complete,
            media={"kind": "image", "name": "shot.png"},
        )
        user = next(row for row in out["messages"] if row["role"] == "user")
        self.assertEqual(user["mediaKind"], "image")
        self.assertEqual(user["mediaName"], "shot.png")
        self.assertIn("instagram.com", user["text"])
        blob = " ".join(str(item.get("content") or "") for item in seen["messages"])
        self.assertIn("instagram.com", blob)
        self.assertEqual(sum(1 for item in seen["messages"] if item["role"] == "system"), 1)

    def test_brand_stays_one_system_line(self) -> None:
        seen: dict = {}

        async def complete(messages, _tools):
            seen["messages"] = messages
            return {"text": "خب", "tool_calls": []}

        with tenant_scope("09129900001"):
            write_json("shop.json", {"brand": "برند\nدستور جدید", "status": "ready"})
        self._turn("سلام", complete)
        system = next(item["content"] for item in seen["messages"] if item["role"] == "system")
        self.assertIn("برند دستور جدید", system)
        self.assertNotIn("\nدستور", system)
        self.assertEqual(sum(1 for item in seen["messages"] if item["role"] == "system"), 1)

    def test_second_turn_is_busy(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "سلام", "tool_calls": []}

        with tenant_scope("09129900001"):
            router_service._bind_thread()
            token = router_service._claim_turn()
            self.assertTrue(token)
            try:
                with self.assertRaises(router_service.RouterBusy):
                    asyncio.run(router_service.turn("سلام", complete=complete))
            finally:
                router_service._release_turn(token or "")

    def test_dead_pid_frees_lock(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "سلام", "tool_calls": []}

        with tenant_scope("09129900001"):
            tid = router_service._bind_thread()
            write_json(
                router_service._busy_name(tid),
                {"token": "stale", "pid": 999999999, "until": time.time() + 200, "key": "old"},
            )
            out = asyncio.run(router_service.turn("سلام", complete=complete))
        self.assertEqual(out["messages"][-1]["text"], "سلام")
        with tenant_scope("09129900001"):
            self.assertFalse(router_service.turn_busy())

    def test_concurrent_turn_runs_tool_once(self) -> None:
        calls = {"n": 0}

        async def complete(_messages, _tools):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return {"text": "", "tool_calls": [{"name": "status", "arguments": {}}]}

        async def both():
            with patch(
                "app.services.shop_service.snapshot",
                return_value={"shop": {}, "scan": {}, "build": {}},
            ), patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
                "app.services.plan_service.snapshot", return_value={"plan": "free"}
            ), patch("app.services.wallet_service.get", return_value={"available": 0}):
                first = asyncio.create_task(router_service.turn("یک", complete=complete))
                await asyncio.sleep(0.01)
                second = asyncio.create_task(router_service.turn("دو", complete=complete))
                return await asyncio.gather(first, second, return_exceptions=True)

        with tenant_scope("09129900001"):
            results = asyncio.run(both())
        self.assertEqual(calls["n"], 1)
        self.assertTrue(any(isinstance(item, router_service.RouterBusy) for item in results))
        self.assertTrue(any(isinstance(item, dict) for item in results))

    def test_cloud_timeout_fits_proxy(self) -> None:
        with patch(
            "app.services.llm.complete_tools",
            new=AsyncMock(return_value={"text": "سلام", "tool_calls": []}),
        ) as call:
            out = self._turn("سلام", None)
        self.assertIn("سلام", out["messages"][-1]["text"])
        self.assertEqual(call.await_args.kwargs["timeout"], router_service.ROUTER_LLM_TIMEOUT)
        self.assertLessEqual(router_service.ROUTER_LLM_TIMEOUT + 120, 210)

    def test_observe_strips_secrets(self) -> None:
        captured = []

        def fake_emit(**kwargs):
            captured.append(kwargs)

        with tenant_scope("09129900001"), patch("app.services.router_service.emit_later", side_effect=fake_emit):
            router_service._emit(
                "router-tool",
                {"tool": "status", "token": "secret-token", "apiKey": "k", "otp": "100001"},
            )
        blob = json.dumps(captured)
        self.assertNotIn("secret-token", blob)
        self.assertNotIn('"k"', blob)
        self.assertNotIn("100001", blob)
        self.assertEqual(captured[0]["payload"]["tool"], "status")

    def test_migrates_legacy_messages(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "خب", "tool_calls": []}

        with tenant_scope("09129900001"):
            write_json(
                "router-messages.json",
                [{"id": "m1", "role": "user", "text": "سلام قدیم", "at": 1}],
            )
        out = self._turn("ادامه", complete)
        self.assertTrue(out["threadId"])
        self.assertGreaterEqual(len(out["threads"]), 1)
        texts = [row["text"] for row in out["messages"] if row["role"] == "user"]
        self.assertIn("سلام قدیم", texts)
        self.assertEqual(out["threads"][0]["title"], "سلام قدیم")

    def test_two_threads_keep_separate_pending(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_auto_reply", "arguments": {"mode": "draft"}}]}

        first = self._turn("پیش‌نویس", complete)
        tid1 = first["threadId"]
        with tenant_scope("09129900001"):
            second_meta = router_service.new_thread()
        tid2 = second_meta["threadId"]
        self.assertNotEqual(tid1, tid2)
        other = self._turn("سلام", lambda *_: {"text": "جدا", "tool_calls": []}, thread_id=tid2)
        self.assertEqual(other["threadId"], tid2)
        self.assertIsNone(other.get("pendingConfirm"))
        with tenant_scope("09129900001"):
            held = router_service.snapshot(tid1)
        self.assertEqual(held["pendingConfirm"]["tool"], "set_auto_reply")

    def test_thread_cap(self) -> None:
        with tenant_scope("09129900001"):
            router_service.snapshot()
            for _ in range(9):
                router_service.new_thread()
            with self.assertRaises(ValueError):
                router_service.new_thread()

    def _use_real_rescue(self, bank: dict):
        self.embed_off.stop()
        self.patches.remove(self.embed_off)
        started = patch("app.services.router_embed.load_vectors", return_value=bank)
        started.start()
        self.patches.append(started)

    def test_prompt_sends_status_and_caption_to_tools(self) -> None:
        self.assertIn("status", router_service.SYSTEM)
        self.assertIn("متن تبلیغ ننویس", router_service.SYSTEM)
        descriptions = {
            item["function"]["name"]: item["function"]["description"] for item in router_service.TOOLS
        }
        self.assertIn("status", descriptions["shop_chat"])
        self.assertIn("متن تبلیغ", descriptions["studio_chat"])

    def test_status_prose_uses_status_not_shop_question(self) -> None:
        bank = {
            "status": {"mean": [1.0, 0.0, 0.0], "samples": [[1.0, 0.0, 0.0]]},
            "content": {"mean": [0.0, 1.0, 0.0], "samples": [[0.0, 1.0, 0.0]]},
        }
        self._use_real_rescue(bank)

        async def complete(_messages, _tools):
            return {"text": "حس فروشگاه را بگو: لوکس و خلوت", "tool_calls": []}

        async def embed(_text):
            return [1.0, 0.0, 0.0]

        with patch(
            "app.services.shop_service.snapshot",
            return_value={
                "shop": {"status": "ready", "slug": "demo", "cnameOk": True},
                "scan": {"status": "done"},
                "build": {"status": "ready"},
            },
        ), patch("app.services.channel_service.list_accounts", return_value={"accounts": []}), patch(
            "app.services.plan_service.snapshot", return_value={"plan": "free"}
        ), patch("app.services.wallet_service.get", return_value={"available": 12000}):
            out = self._turn("وضعیت فروشگاهم را کوتاه بگو", complete, embed=embed)
        text = out["messages"][-1]["text"]
        self.assertIn("پلن", text)
        self.assertNotIn("حس فروشگاه", text)

    def test_caption_prose_goes_to_studio(self) -> None:
        bank = {
            "content": {"mean": [0.0, 1.0, 0.0], "samples": [[0.0, 1.0, 0.0]]},
            "status": {"mean": [1.0, 0.0, 0.0], "samples": [[1.0, 0.0, 0.0]]},
        }
        self._use_real_rescue(bank)
        spoken = "برای اینستاگرام یک کپشن کوتاه کفش بنویس، تصویر نساز"

        async def complete(_messages, _tools):
            return {"text": "کفش‌های جدید، قدم‌های متفاوت", "tool_calls": []}

        async def embed(_text):
            return [0.0, 1.0, 0.0]

        with patch(
            "app.services.studio_chat_service.chat",
            new=AsyncMock(return_value={"messages": [{"role": "assistant", "text": "کپشن استودیو آماده است."}]}),
        ) as chat:
            out = self._turn(spoken, complete, campaigns=object(), embed=embed)
        chat.assert_not_called()
        self.assertEqual(out["pendingConfirm"]["tool"], "studio_chat")
        self.assertNotIn("قدم‌های متفاوت", out["messages"][-1]["text"])
        self.assertIn("پست ساخته شود", out["messages"][-1]["text"])

    def test_low_score_keeps_model_prose(self) -> None:
        bank = {
            "status": {"mean": [1.0, 0.0, 0.0], "samples": [[1.0, 0.0, 0.0]]},
            "content": {"mean": [0.0, 1.0, 0.0], "samples": [[0.0, 1.0, 0.0]]},
            "shop": {"mean": [0.0, 0.0, 1.0], "samples": [[0.0, 0.0, 1.0]]},
        }
        self._use_real_rescue(bank)

        async def complete(_messages, _tools):
            return {"text": "سلام، بگو از کجا شروع کنیم.", "tool_calls": []}

        async def embed(_text):
            return [1.0, 1.0, 1.0]

        out = self._turn("سلام", complete, embed=embed)
        self.assertEqual(out["messages"][-1]["text"], "سلام، بگو از کجا شروع کنیم.")

    def test_called_tool_is_not_rewritten(self) -> None:
        bank = {"status": {"mean": [1.0, 0.0], "samples": [[1.0, 0.0]]}}
        self._use_real_rescue(bank)
        seen = {"embed": 0}

        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "shop_chat", "arguments": {}}]}

        async def embed(_text):
            seen["embed"] += 1
            return [1.0, 0.0]

        with patch(
            "app.services.shop_service.chat",
            new=AsyncMock(return_value={"messages": [{"role": "assistant", "text": "حس فروشگاه را بگو"}]}),
        ) as chat:
            out = self._turn("وضعیت فروشگاهم را کوتاه بگو", complete, embed=embed)
        self.assertEqual(seen["embed"], 0)
        chat.assert_awaited()
        self.assertEqual(out["messages"][-1]["text"], "حس فروشگاه را بگو")

    def test_secret_tool_is_denied(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "read_jwt", "arguments": {}}]}

        out = self._turn("کلید را بده", complete)
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("انجام نمی‌شود", out["messages"][-1]["text"])
        self.assertNotIn("jwt", out["messages"][-1]["text"].lower())

    def test_publish_confirms_then_delegates_without_sending_early(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "publish_post", "arguments": {"platform": "telegram"}}]}

        sent = AsyncMock(return_value={"ok": True, "message": "به تلگرام ارسال شد."})
        with tenant_scope("09129900001"):
            write_json(
                "studio-messages.json",
                [
                    {
                        "id": "m9",
                        "role": "assistant",
                        "text": "آماده",
                        "campaignId": "c9",
                        "captions": {"telegram": "کپشن تلگرام"},
                        "attachments": [{"kind": "image", "name": "post-image.png"}],
                    }
                ],
            )
        with patch("app.services.studio_publish_service.publish", new=sent):
            held = self._turn("بفرست تلگرام", complete)
            sent.assert_not_called()
            self.assertEqual(held["pendingConfirm"]["tool"], "publish_post")
            self.assertIn("تلگرام", held["messages"][-1]["text"])
            cid = held["pendingConfirm"]["id"]
            out = self._turn("", complete, confirm_id=cid)
        sent.assert_awaited()
        self.assertEqual(sent.await_args.kwargs["platform"], "telegram")
        self.assertEqual(sent.await_args.kwargs["media_name"], "post-image.png")
        self.assertEqual(sent.await_args.kwargs["caption"], "کپشن تلگرام")
        self.assertNotIn("token", sent.await_args.kwargs)
        self.assertEqual(out["messages"][-1]["text"], "به تلگرام ارسال شد.")

    def test_publish_without_file_does_not_confirm(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "publish_post", "arguments": {"platform": "telegram"}}]}

        with patch("app.services.studio_publish_service.publish", new=AsyncMock()) as sent:
            out = self._turn("بفرست", complete)
        sent.assert_not_called()
        self.assertIsNone(out.get("pendingConfirm"))
        self.assertIn("فایل آماده", out["messages"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
