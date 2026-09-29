import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import inbox as inbox_api
from app.config import settings
from app.database import get_session
from app.security import get_current_user


class InboxDryReplyTests(unittest.TestCase):
    def _client(self, user: SimpleNamespace | None) -> TestClient:
        app = FastAPI()
        app.include_router(inbox_api.router)

        async def fake_session():
            yield None

        app.dependency_overrides[get_session] = fake_session
        if user is not None:
            async def fake_user():
                return user

            app.dependency_overrides[get_current_user] = fake_user
        return TestClient(app)

    def _admin(self) -> SimpleNamespace:
        return SimpleNamespace(phone="09120001111", role="admin", is_active=True)

    def test_dry_reply_requires_the_inbox_permission(self) -> None:
        missing = self._client(None).post("/inbox/dry-reply", json={"text": "سلام"})
        self.assertEqual(missing.status_code, 401)
        self.assertTrue(missing.json().get("detail"))
        stranger = self._client(SimpleNamespace(phone="09120001111", role="viewer", is_active=True))
        denied = stranger.post("/inbox/dry-reply", json={"text": "سلام"})
        self.assertEqual(denied.status_code, 403)
        self.assertIn("دسترسی", denied.json().get("detail") or "")

    def test_dry_reply_is_forbidden_unless_the_edge_is_dry(self) -> None:
        with patch.dict(os.environ, {"SOZAN_EDGE_DRY": ""}):
            res = self._client(self._admin()).post("/inbox/dry-reply", json={"text": "سلام"})
        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.json().get("detail"))
        self.assertNotIn("text", res.json())

    def test_dry_reply_returns_the_agent_and_does_not_deliver(self) -> None:
        async def fake_answer(text, thread=None, source=""):
            self.assertEqual(text, "قیمت؟")
            self.assertEqual((thread or {}).get("sender"), "آزمون")
            self.assertEqual(source, "battery")
            return "دو عدد موجود است."

        with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, {"SOZAN_EDGE_DRY": "1"}), patch.object(
            settings, "state_dir", raw
        ), patch("app.services.inbox_agent_service.answer", new=fake_answer), patch(
            "app.services.inbox_service.reply"
        ) as deliver:
            res = self._client(self._admin()).post("/inbox/dry-reply", json={"text": "قیمت؟"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["text"], "دو عدد موجود است.")
        deliver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
