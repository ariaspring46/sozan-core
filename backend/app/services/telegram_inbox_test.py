import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import inbox_service, inbound_media_service, telegram_service
from app.state_store import tenant_scope


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class TelegramInboxTests(unittest.TestCase):
    def test_photo_update_imports_media(self) -> None:
        stored = {"kind": "image", "name": "abc-image.png"}
        client = AsyncMock()
        client.post.side_effect = [
            _Resp({"ok": True}),
            _Resp(
                {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 12,
                            "message": {
                                "message_id": 5,
                                "photo": [{"file_id": "small"}, {"file_id": "big"}],
                                "chat": {"id": 90},
                                "from": {"id": 7, "first_name": "علی"},
                            },
                        }
                    ],
                }
            ),
        ]
        client.get.return_value = _Resp({"ok": True, "result": {"id": 9}})
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.telegram_service._client", return_value=client
            ), patch(
                "app.services.telegram_service._download_file", new=AsyncMock(return_value=stored)
            ), patch("app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}), patch(
                "app.services.inbox_service.emit_later"
            ), tenant_scope("09120001111"):
                result = asyncio.run(telegram_service.pull_updates(token="tok"))
                threads = inbox_service.list_threads()["threads"]
                opened = inbox_service.get_thread(threads[0]["id"])
        self.assertEqual(result.get("imported"), 1)
        self.assertEqual(opened["messages"][-1]["mediaKind"], "image")
        self.assertEqual(opened["messages"][-1]["mediaName"], "abc-image.png")
        self.assertIn("تصویر", opened["messages"][-1]["text"])

    def test_group_messages_are_skipped_and_offset_advances(self) -> None:
        client = AsyncMock()
        client.post.side_effect = [
            _Resp({"ok": True}),
            _Resp(
                {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 20,
                            "message": {
                                "message_id": 1,
                                "text": "در گروه",
                                "chat": {"id": -100, "type": "supergroup"},
                                "from": {"id": 8, "first_name": "علی"},
                            },
                        },
                        {
                            "update_id": 21,
                            "message": {
                                "message_id": 2,
                                "text": "خصوصی",
                                "chat": {"id": 90, "type": "private"},
                                "from": {"id": 7, "first_name": "علی"},
                            },
                        },
                    ],
                }
            ),
        ]
        client.get.return_value = _Resp({"ok": True, "result": {"id": 9}})
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.telegram_service._client", return_value=client
            ), patch("app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}), patch(
                "app.services.inbox_service.emit_later"
            ), tenant_scope("09120001111"):
                result = asyncio.run(telegram_service.pull_updates(token="tok"))
                threads = inbox_service.list_threads()["threads"]
                opened = inbox_service.get_thread(threads[0]["id"])
                offset = telegram_service._offset_state()
        self.assertEqual(result.get("imported"), 1)
        self.assertEqual(len(threads), 1)
        self.assertEqual(opened["messages"][-1]["text"], "خصوصی")
        self.assertEqual(int(offset.get("offset") or 0), 22)

    def test_getupdates_conflict_is_not_a_bad_token(self) -> None:
        client = AsyncMock()
        client.post.side_effect = [
            _Resp({"ok": True}),
            _Resp(
                {"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"},
                status_code=409,
            ),
        ]
        client.get.return_value = _Resp({"ok": True, "result": {"id": 9}})
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.telegram_service._client", return_value=client
            ), tenant_scope("09120001111"):
                result = asyncio.run(telegram_service.pull_updates(token="tok"))
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("imported"), 0)
        self.assertIn("جای دیگری", str(result.get("error") or ""))
        self.assertNotIn("BotFather", str(result.get("error") or ""))


class InboundMediaTests(unittest.TestCase):
    def test_rejects_non_http(self) -> None:
        self.assertIsNone(asyncio.run(inbound_media_service.fetch_and_store("ftp://x")))
        self.assertIsNone(asyncio.run(inbound_media_service.fetch_and_store("")))
