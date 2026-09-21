from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import router_service
from app.state_store import tenant_scope, write_json


class RouterServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(settings, "state_dir", self.tmp.name)]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def _turn(self, text: str, complete, confirm_id: str = "", cancel_id: str = "", campaigns=None, media=None):
        with tenant_scope("09129900001"):
            return asyncio.run(
                router_service.turn(
                    text,
                    confirm_id=confirm_id,
                    cancel_id=cancel_id,
                    complete=complete,
                    campaigns=campaigns,
                    media=media,
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
            new=AsyncMock(return_value={"messages": [{"role": "assistant", "text": "رنگ دکمه عوض شد."}]}),
        ) as chat:
            out = self._turn("دکمه را زرشکی کن", complete)
        chat.assert_awaited()
        self.assertEqual(chat.await_args.args[0], "دکمه را زرشکی کن")
        self.assertEqual(out["messages"][-1]["text"], "رنگ دکمه عوض شد.")

    def test_studio_passthrough(self) -> None:
        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "studio_chat", "arguments": {"text": "پوستر بساز"}}]}

        campaigns = object()
        with patch(
            "app.services.studio_chat_service.chat",
            new=AsyncMock(
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
            ),
        ) as chat:
            out = self._turn("پوستر بساز", complete, campaigns=campaigns)
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
            token = router_service._claim_turn()
            self.assertTrue(token)
            try:
                with self.assertRaises(router_service.RouterBusy):
                    asyncio.run(router_service.turn("سلام", complete=complete))
            finally:
                router_service._release_turn(token or "")

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


if __name__ == "__main__":
    unittest.main()
