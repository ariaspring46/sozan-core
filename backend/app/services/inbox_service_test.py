import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.config import settings
from app.services import inbox_service, studio_compose_service
from app.state_store import tenant_scope


def _handle(**kwargs):
    async def run():
        out = await inbox_service.handle_inbound(**kwargs)
        await inbox_service.drain_auto_replies()
        tid = str((out.get("thread") or {}).get("id") or "")
        if not tid:
            return out
        snap = inbox_service.get_thread(tid)
        if out.get("duplicate"):
            snap["duplicate"] = True
        if out.get("echo"):
            snap["echo"] = True
        return snap

    return asyncio.run(run())


class InboxServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def _scope(self):
        return tenant_scope("09120001111"), patch("app.state_store.settings") 

    def test_duplicate_external_id_skips_second_inbound(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": ""}):
            first = inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:1"
            )
            second = inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:1"
            )
        self.assertFalse(first.get("duplicate"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(first["thread"]["count"], 1)

    def test_llm_error_does_not_send(self) -> None:
        reply = AsyncMock()
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ) as emit, patch("app.services.plan_service.current", return_value={"autoReply": "send"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value=None)
        ), patch("app.services.inbox_service.reply", new=reply):
            _handle(
                    platform="telegram", sender="علی", text="قیمت؟", sender_id="1", chat_id="9", external_id="9:2"
                )
        reply.assert_not_awaited()
        titles = [c.kwargs.get("title") for c in emit.call_args_list if c.kwargs]
        self.assertIn("auto-reply-failed", titles)

    def test_draft_mode_stores_draft(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": "draft"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="بله موجود است.")
        ), patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as deliver:
            result = _handle(
                    platform="telegram", sender="علی", text="موجوده؟", sender_id="1", chat_id="9", external_id="9:3"
                )
        deliver.assert_not_awaited()
        kinds = [msg.get("kind") for msg in result["messages"]]
        self.assertIn("draft", kinds)

    def test_delivery_fail_records_failed_outbound(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": "send"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="بله موجود است.")
        ), patch(
            "app.services.channel_outbound_service.deliver",
            new=AsyncMock(side_effect=ValueError("حساب این کانال وصل نیست")),
        ):
            result = _handle(
                    platform="telegram", sender="علی", text="موجوده؟", sender_id="1", chat_id="9", external_id="9:4"
                )
        kinds = [msg.get("kind") for msg in result["messages"]]
        self.assertIn("failed", kinds)

    def test_approve_draft_replaces_row(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": "draft"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="بله موجود است.")
        ), patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as deliver:
            created = _handle(
                    platform="telegram", sender="علی", text="موجوده؟", sender_id="1", chat_id="9", external_id="9:5"
                )
            draft_id = next(msg["id"] for msg in created["messages"] if msg.get("kind") == "draft")
            approved = asyncio.run(
                inbox_service.reply(created["thread"]["id"], "بله، موجود است.", deliver=True, draft_id=draft_id)
            )
        deliver.assert_awaited()
        kinds = [msg.get("kind") for msg in approved["messages"]]
        self.assertNotIn("draft", kinds)
        self.assertEqual(sum(1 for msg in approved["messages"] if msg.get("kind") == "outbound"), 1)

    def test_duplicate_retries_auto_reply_when_unanswered(self) -> None:
        reply = AsyncMock()
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": "send"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="سلام")
        ), patch("app.services.inbox_service.reply", new=reply):
            _handle(
                    platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:6"
                )
            _handle(
                    platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:6"
                )
        self.assertEqual(reply.await_count, 1)


class InboxModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def _plan(self, **kwargs):
        row = {"autoReply": "", "dmSync": True, "label": "رایگان"}
        row.update(kwargs)
        return row

    def test_ceiling_rejects_draft_on_free(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.plan_service.current", return_value=self._plan()
        ):
            with self.assertRaises(ValueError):
                inbox_service.save_auto_reply("draft")

    def test_choice_below_ceiling(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.plan_service.current", return_value=self._plan(autoReply="send", label="پرو مکس")
        ):
            out = inbox_service.save_auto_reply("draft")
        self.assertEqual(out["autoReply"], "draft")
        self.assertEqual(out["autoReplyMax"], "send")
        self.assertEqual(out["autoReplyChoice"], "draft")

    def test_paused_skips_auto_reply(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan(autoReply="draft", label="پرو")), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="بله")
        ), patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as deliver:
            first = _handle(
                    platform="telegram", sender="علی", text="موجوده؟", sender_id="1", chat_id="9", external_id="9:p1"
                )
            inbox_service.patch_thread(first["thread"]["id"], paused=True)
            second = _handle(
                    platform="telegram", sender="علی", text="قیمت؟", sender_id="1", chat_id="9", external_id="9:p2"
                )
        deliver.assert_not_awaited()
        drafts = [msg for msg in second["messages"] if msg.get("kind") == "draft"]
        self.assertEqual(len(drafts), 1)
        self.assertTrue(second["thread"]["paused"])

    def test_unread_clears_on_read(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan()):
            created = inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:u1"
            )
            self.assertEqual(inbox_service.unread_count()["count"], 1)
            self.assertEqual(created["thread"]["unread"], 1)
            opened = inbox_service.get_thread(created["thread"]["id"], mark_read=True)
        self.assertEqual(opened["thread"]["unread"], 0)
        self.assertEqual(inbox_service.unread_count()["count"], 0)

    def test_failed_retry_capped(self) -> None:
        deliver = AsyncMock(side_effect=ValueError("حساب این کانال وصل نیست"))
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch(
            "app.services.plan_service.current", return_value=self._plan(autoReply="send", label="پرو مکس")
        ), patch("app.services.voice_service.draft_reply", new=AsyncMock(return_value="بله موجود است.")), patch(
            "app.services.channel_outbound_service.deliver", new=deliver
        ):
            result = _handle(
                    platform="telegram", sender="علی", text="موجوده؟", sender_id="1", chat_id="9", external_id="9:f1"
                )
            thread = inbox_service._find_thread(inbox_service._state(), result["thread"]["id"])
        self.assertEqual(deliver.await_count, 2)
        self.assertEqual(int(thread.get("autoRetries") or 0), 2)
        self.assertIn("failed", [msg.get("kind") for msg in result["messages"]])

    def test_sending_status_during_deliver(self) -> None:
        seen = {"status": ""}

        async def deliver(**kwargs):
            data = inbox_service._state()
            for thread in data["threads"]:
                for msg in thread.get("messages") or []:
                    if msg.get("role") == "outbound":
                        seen["status"] = str(msg.get("status") or "")

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan()), patch(
            "app.services.channel_outbound_service.deliver", new=deliver
        ):
            created = inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:s1"
            )
            asyncio.run(inbox_service.reply(created["thread"]["id"], "سلام، بله."))
            opened = inbox_service.get_thread(created["thread"]["id"])
        self.assertEqual(seen["status"], "sending")
        outbound = [msg for msg in opened["messages"] if msg.get("kind") == "outbound"][0]
        self.assertEqual(outbound["status"], "sent")

    def test_expire_stale_sending(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan()):
            created = inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:stale"
            )
            data = inbox_service._state()
            data["threads"][0]["messages"].append(
                {
                    "id": "m-send",
                    "role": "outbound",
                    "kind": "outbound",
                    "status": "sending",
                    "text": "در راه",
                    "at": 1,
                }
            )
            inbox_service._save(data)
            n = inbox_service.expire_stale_sending(10)
            opened = inbox_service.get_thread(created["thread"]["id"])
        self.assertEqual(n, 1)
        failed = next(msg for msg in opened["messages"] if msg.get("id") == "m-send")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("قطع", failed["error"])

    def test_edit_draft_without_deliver_keeps_draft(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan()), patch(
            "app.services.channel_outbound_service.deliver", new=AsyncMock()
        ) as deliver:
            created = inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:ed1"
            )
            asyncio.run(inbox_service.reply(created["thread"]["id"], "پیش‌نویس اول", deliver=False, as_draft=True))
            opened = inbox_service.get_thread(created["thread"]["id"])
            draft = next(msg for msg in opened["messages"] if msg.get("kind") == "draft")
            asyncio.run(
                inbox_service.reply(
                    created["thread"]["id"],
                    "پیش‌نویس ویرایش‌شده",
                    deliver=False,
                    draft_id=str(draft["id"]),
                )
            )
            opened = inbox_service.get_thread(created["thread"]["id"])
            kept = next(msg for msg in opened["messages"] if msg.get("id") == draft["id"])
        self.assertEqual(kept["kind"], "draft")
        self.assertEqual(kept["status"], "draft")
        self.assertEqual(kept["text"], "پیش‌نویس ویرایش‌شده")
        self.assertEqual(deliver.await_count, 0)

    def test_media_empty_text_stores_caption(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan()):
            result = inbox_service.inbound(
                platform="telegram",
                sender="علی",
                text="",
                sender_id="1",
                chat_id="9",
                external_id="9:m1",
                media={"kind": "image", "name": "abc-image.png"},
            )
        last = result["messages"][-1]
        self.assertEqual(last["mediaKind"], "image")
        self.assertEqual(last["mediaName"], "abc-image.png")
        self.assertIn("تصویر", last["text"])

    def test_list_filter_unread(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value=self._plan()):
            inbox_service.inbound(
                platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:l1"
            )
            inbox_service.inbound(
                platform="instagram", sender="سارا", text="قیمت", sender_id="2", chat_id="2", external_id="ig:1"
            )
            unread = inbox_service.list_threads(status_filter="unread")
            ig = inbox_service.list_threads(platform="instagram")
            q = inbox_service.list_threads(q="سارا")
        self.assertEqual(len(unread["threads"]), 2)
        self.assertEqual(len(ig["threads"]), 1)
        self.assertEqual(q["threads"][0]["sender"], "سارا")
    def test_echo_of_recent_outbound_skips_auto_reply(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": "send", "dmSync": True, "label": "پرو مکس"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="سلام دوباره")
        ), patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as deliver:
            created = inbox_service.inbound(
                platform="instagram", sender="علی", text="سلام", sender_id="1", chat_id="c1", external_id="ig:a"
            )
            asyncio.run(inbox_service.reply(created["thread"]["id"], "قربون شما عزیزم.", deliver=True))
            echoed = inbox_service.inbound(
                platform="instagram",
                sender="علی",
                text="قربون شما عزیزم.",
                sender_id="1",
                chat_id="c1",
                external_id="ig:echo",
            )
            asyncio.run(inbox_service.maybe_auto_reply(created["thread"]["id"]))
        self.assertTrue(echoed.get("echo") or echoed.get("duplicate"))
        self.assertEqual(echoed["thread"]["count"], 2)
        self.assertEqual(deliver.await_count, 1)

    def test_auto_reply_cooldown_skips_second_send(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_service.emit_later"
        ), patch("app.services.plan_service.current", return_value={"autoReply": "send", "dmSync": True, "label": "پرو مکس"}), patch(
            "app.services.voice_service.draft_reply", new=AsyncMock(return_value="پاسخ تازه")
        ), patch("app.services.channel_outbound_service.deliver", new=AsyncMock()) as deliver:
            first = _handle(
                    platform="telegram", sender="علی", text="سلام", sender_id="1", chat_id="9", external_id="9:cd1"
                )
            _handle(
                    platform="telegram", sender="علی", text="قیمت؟", sender_id="1", chat_id="9", external_id="9:cd2"
                )
        self.assertEqual(deliver.await_count, 1)
        self.assertGreaterEqual(first["thread"]["count"], 1)
    def test_no_still_fetches_image(self) -> None:
        png = b"\x89PNG" + b"0" * 3000
        saved = {}

        class Fake:
            async def save_raw(self, campaign_id, filename, data):
                saved["raw"] = filename
                saved["bytes"] = data
                return SimpleNamespace(id=uuid4())

            async def compose(self, campaign_id):
                saved["composed"] = True
                return SimpleNamespace(id=campaign_id)

            async def preview_outputs(self, campaign_id):
                return []

        async def fake_run(**kwargs):
            return None

        with patch("app.services.studio_compose_service.generate_still", return_value=png), patch(
            "app.services.studio_chat_service.set_compose"
        ), patch("app.services.studio_chat_service.finish_compose") as finish, patch(
            "app.services.studio_chat_service.attach_still", new=AsyncMock(return_value=False)
        ), patch("app.services.studio_chat_service.fallback_attachment", return_value=[]), patch(
            "app.services.studio_chat_service.copy_outputs", return_value=[{"kind": "image", "name": "x.png"}]
        ), patch("app.services.studio_compose_service.SessionLocal") as session_cm, patch(
            "app.services.studio_compose_service._svc", return_value=Fake()
        ), patch("app.services.studio_compose_service.emit_later"):
            session_cm.return_value.__aenter__ = AsyncMock(return_value=object())
            session_cm.return_value.__aexit__ = AsyncMock(return_value=False)
            asyncio.run(
                studio_compose_service._run(
                    tenant="09120001111",
                    message_id="m1",
                    campaign_id=str(uuid4()),
                    media=None,
                    title="ویترین",
                    image_prompt="",
                    job_id="j1",
                    started=0,
                )
            )
        finish.assert_called()
        self.assertEqual(finish.call_args.kwargs["status"], "ready")

    def test_still_fail_marks_failed(self) -> None:
        with patch("app.services.studio_compose_service.generate_still", return_value=b""), patch(
            "app.services.studio_chat_service.set_compose"
        ), patch("app.services.studio_chat_service.finish_compose") as finish, patch(
            "app.services.studio_chat_service.attach_still", new=AsyncMock(return_value=False)
        ), patch("app.services.studio_chat_service.fallback_attachment", return_value=[]), patch(
            "app.services.studio_compose_service.SessionLocal"
        ) as session_cm, patch("app.services.studio_compose_service.emit_later"):
            session_cm.return_value.__aenter__ = AsyncMock(return_value=object())
            session_cm.return_value.__aexit__ = AsyncMock(return_value=False)
            asyncio.run(
                studio_compose_service._run(
                    tenant="09120001111",
                    message_id="m2",
                    campaign_id=str(uuid4()),
                    media=None,
                    title="ویترین",
                    image_prompt="",
                    job_id="j2",
                    started=0,
                )
            )
        self.assertEqual(finish.call_args.kwargs["status"], "failed")

    def test_watchdog_flips_stale_running(self) -> None:
        from app.services import studio_chat_service

        rows = [{"id": "m3", "compose": {"status": "running", "startedAt": 1}}]
        with patch("app.services.studio_chat_service._messages", return_value=rows), patch(
            "app.services.studio_chat_service._save"
        ) as save, patch("app.services.studio_chat_service.tenant_file_lock"), patch(
            "app.services.studio_chat_service.emit_later"
        ):
            studio_chat_service.expire_stale_compose(10)
        self.assertEqual(rows[0]["compose"]["status"], "failed")
        save.assert_called()

    def test_finish_compose_ignores_stale_job(self) -> None:
        from app.services import studio_chat_service

        rows = [{"id": "m1", "compose": {"status": "running", "jobId": "new", "startedAt": 1}}]
        with patch("app.services.studio_chat_service._messages", return_value=rows), patch(
            "app.services.studio_chat_service._save"
        ), patch("app.services.studio_chat_service.tenant_file_lock"):
            skipped = studio_chat_service.finish_compose(
                "m1", [{"kind": "image", "name": "x.png"}], status="ready", job_id="old"
            )
        self.assertFalse(skipped)
        self.assertEqual(rows[0]["compose"]["status"], "running")
        self.assertEqual(rows[0]["compose"]["jobId"], "new")


class RoutingTests(unittest.TestCase):
    def test_override_local_model(self) -> None:
        from app.services.llm import route_for_surface

        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get",
            return_value={"kind": "local", "model": "qwen3.5-4b"},
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
        self.assertEqual(route["model"], "qwen3.5-4b")
        self.assertEqual(route["source"], "override")

    def test_cloud_missing_key_falls_back(self) -> None:
        from app.services.llm import route_for_surface

        with patch("app.services.llm.settings") as settings, patch(
            "app.services.llm_routing_service.get",
            return_value={"kind": "cloud", "model": "x", "provider": "cloud-x"},
        ), patch(
            "app.services.llm_routing_service.provider",
            return_value={"id": "cloud-x", "base_url": "https://example.com/v1", "key_env": "MISSING_LLM_KEY"},
        ), patch.dict("os.environ", {"MISSING_LLM_KEY": ""}, clear=False):
            settings.local_llm_url = "http://127.0.0.1:9292/v1"
            settings.local_llm_model = "qwen3.8-27b"
            settings.local_llm_token = "sk-local"
            settings.chat_llm_model = "ornith-1.5-35b"
            settings.studio_llm_model = "qwen3.5-9b"
            settings.cloud_llm_url = "https://ollama.com/v1"
            settings.cloud_llm_model = "deepseek-v4.1-flash:cloud"
            settings.cloud_llm_token = ""
            settings.cloud_llm_proxy = ""
            settings.channel_proxy = ""
            route = route_for_surface("studio")
        self.assertEqual(route["source"], "default")
        self.assertEqual(route["model"], "qwen3.5-9b")


if __name__ == "__main__":
    unittest.main()
