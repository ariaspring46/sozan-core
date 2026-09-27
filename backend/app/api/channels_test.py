import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import channels as channels_api
from app.config import settings
from app.database import get_session
from app.security import get_current_user
from app.services import inbox_service, sendbox_service
from app.state_store import set_tenant, tenant_scope


class ChannelsWebhookTests(unittest.TestCase):
    def _anon(self) -> TestClient:
        app = FastAPI()
        app.include_router(channels_api.router)
        return TestClient(app)

    def _auth(self, phone: str = "09135409482") -> TestClient:
        app = FastAPI()
        app.include_router(channels_api.router)

        async def fake_user():
            set_tenant(phone)
            return SimpleNamespace(phone=phone, role="admin", is_active=True)

        async def fake_session():
            yield MagicMock()

        app.dependency_overrides[get_current_user] = fake_user
        app.dependency_overrides[get_session] = fake_session
        return TestClient(app)

    def test_webhook_rejects_empty_token(self) -> None:
        res = self._anon().post("/channels/sendbox/webhook", json={})
        self.assertEqual(res.status_code, 401)

    def test_webhook_imports_dm(self) -> None:
        payload = {
            "event_type": "messaging",
            "account_id": "acc-1",
            "data": {
                "messaging": [
                    {
                        "sender": {"id": "cust1"},
                        "recipient": {"id": "page1"},
                        "message": {"mid": "m-api-1", "text": "سلام قیمت؟"},
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"sendboxAccountId":"acc-1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), patch.object(
                settings, "jwt_secret", "test-secret"
            ), patch(
                "app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}
            ), patch("app.services.inbox_service.reply", new=AsyncMock()):
                token = sendbox_service.webhook_secret()
                res = self._anon().post(f"/channels/sendbox/webhook?token={token}", json=payload)
                with tenant_scope("09135409482"):
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("imported"), 1)
        self.assertEqual(len(threads), 1)

    def test_connect_requires_sendbox(self) -> None:
        with patch("app.api.channels.sendbox_service.configured", return_value=False):
            res = self._auth().get("/channels/instagram/connect")
        self.assertEqual(res.status_code, 400)
        self.assertIn("اتصال اینستاگرام", res.json()["detail"])
