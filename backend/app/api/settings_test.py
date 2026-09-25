import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import settings as settings_api
from app.config import settings
from app.database import get_session
from app.security import get_current_user
from app.state_store import read_json, write_json


class SettingsApiGuardTests(unittest.TestCase):
    def _client(self, phone: str) -> TestClient:
        app = FastAPI()
        app.include_router(settings_api.router)

        async def fake_user():
            return SimpleNamespace(phone=phone, role="admin", is_active=True)

        async def fake_session():
            yield MagicMock()

        app.dependency_overrides[get_current_user] = fake_user
        app.dependency_overrides[get_session] = fake_session
        return TestClient(app)

    def test_tenant_patch_mock_sms_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(settings, "admin_phone", "09135409482"):
                write_json("settings.json", {"mockSms": False, "otpTtlSeconds": 300}, shared=True)
                client = self._client("09121111111")
                res = client.patch("/settings", json={"mockSms": True})
                stored = read_json("settings.json", {}, shared=True)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(stored.get("mockSms"), False)

    def test_admin_patch_mock_sms_ok(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(settings, "admin_phone", "09135409482"):
                write_json("settings.json", {"mockSms": False}, shared=True)
                client = self._client("09135409482")
                res = client.patch("/settings", json={"mockSms": True})
                stored = read_json("settings.json", {}, shared=True)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(stored.get("mockSms"), True)
