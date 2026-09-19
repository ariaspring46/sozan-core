import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import studio as studio_api
from app.database import get_session
from app.security import get_current_user
from app.services import studio_chat_service
from app.state_store import tenant_scope


class StudioApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        app = FastAPI()
        app.include_router(studio_api.router)

        async def fake_user():
            return SimpleNamespace(phone="09120001111", role="admin", is_active=True)

        async def fake_session():
            yield MagicMock()

        app.dependency_overrides[get_current_user] = fake_user
        app.dependency_overrides[get_session] = fake_session
        self.client = TestClient(app)
        self.store: dict = {}

        def reader(name, default=None):
            return dict(self.store)

        def writer(name, payload):
            self.store.clear()
            if isinstance(payload, dict):
                self.store.update(payload)

        self.idem_read = patch("app.services.idempotency_service.read_json", side_effect=reader)
        self.idem_write = patch("app.services.idempotency_service.write_json", side_effect=writer)
        self.idem_read.start()
        self.idem_write.start()

    def tearDown(self) -> None:
        self.idem_read.stop()
        self.idem_write.stop()
        self.dir.cleanup()

    def test_chat_idempotent_replay(self) -> None:
        with tenant_scope("09120001111"), patch(
            "app.services.studio_chat_service.chat",
            new=AsyncMock(return_value={"messages": [{"id": "a", "text": "سلام"}], "campaignId": ""}),
        ) as chat:
            first = self.client.post("/studio/chat", json={"text": "سلام"}, headers={"Idempotency-Key": "k1"})
            second = self.client.post("/studio/chat", json={"text": "سلام دوباره"}, headers={"Idempotency-Key": "k1"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(chat.await_count, 1)

    def test_publish_idempotent_replay(self) -> None:
        with tenant_scope("09120001111"), patch(
            "app.services.studio_publish_service.publish",
            new=AsyncMock(return_value={"ok": True, "platform": "telegram", "message": "ارسال شد"}),
        ) as pub:
            body = {
                "platform": "telegram",
                "caption": "سلام",
                "mediaName": "x.png",
                "mediaKind": "image",
                "messageId": "m1",
            }
            first = self.client.post("/studio/publish", json=body, headers={"Idempotency-Key": "p1"})
            second = self.client.post("/studio/publish", json=body, headers={"Idempotency-Key": "p1"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json()["ok"], True)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(pub.await_count, 1)

    def test_caption_patch_clips_limits(self) -> None:
        long_ig = "ک" * 3000
        with tenant_scope("09120001111"), patch(
            "app.services.studio_chat_service.update_captions", wraps=studio_chat_service.update_captions
        ), patch("app.services.studio_chat_service._messages", return_value=[{"id": "m1", "captions": {}}]), patch(
            "app.services.studio_chat_service._save"
        ), patch("app.services.studio_chat_service.tenant_file_lock"):
            res = self.client.patch(
                "/studio/caption",
                json={"messageId": "m1", "captions": {"instagram": long_ig, "telegram": "تل", "whatsapp": "وا"}},
            )
        self.assertEqual(res.status_code, 200)
        captions = res.json()["captions"]
        self.assertEqual(len(captions["instagram"]), 2200)
        self.assertEqual(captions["telegram"], "تل")


if __name__ == "__main__":
    unittest.main()
