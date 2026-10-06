import tempfile
import time
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

    def test_boxapi_webhook_without_token_stores_bound_posts_only(self) -> None:
        payload = {
            "event_type": "list_posts",
            "account_id": "acc-1",
            "data": {"posts": [{"id": "p1", "caption": "انگشتر طلا", "media_url": "https://cdn.example/a.jpg"}]},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"sendboxAccountId":"acc-1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw):
                res = self._anon().post("/channels/boxapi/webhook", json=payload)
                missing = self._anon().post(
                    "/channels/boxapi/webhook",
                    json={**payload, "account_id": "acc-other"},
                )
                dm = self._anon().post(
                    "/channels/boxapi/webhook",
                    json={"event_type": "messaging", "account_id": "acc-1", "data": {"messaging": []}},
                )
                with tenant_scope("09135409482"):
                    posts = sendbox_service.take_list_posts("acc-1")
                    other = sendbox_service.take_list_posts("acc-other")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("posts"), 1)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.json().get("posts"), 0)
        self.assertEqual(dm.status_code, 401)
        self.assertEqual(len(posts), 1)
        self.assertEqual(other, [])

    def test_boxapi_webhook_path_stores_posts(self) -> None:
        payload = {
            "event_type": "list_posts",
            "account_id": "acc-1",
            "data": {"posts": [{"id": "p1", "caption": "انگشتر", "media_url": "https://cdn.example/a.jpg"}]},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"sendboxAccountId":"acc-1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), patch.object(settings, "jwt_secret", "test-secret"):
                token = sendbox_service.webhook_secret()
                res = self._anon().post(f"/channels/boxapi/webhook?token={token}", json=payload)
                with tenant_scope("09135409482"):
                    posts = sendbox_service.take_list_posts("acc-1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(posts), 1)

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

    def _return(self, raw: str, phone: str, query: dict, remote: list[dict]):
        with patch.object(settings, "state_dir", raw), patch.object(
            sendbox_service, "_kick_scan", lambda **kwargs: None
        ), patch.object(sendbox_service, "_schedule_activate", lambda account_id: None), patch.object(
            sendbox_service, "list_remote_accounts", new=AsyncMock(return_value=remote)
        ):
            return self._auth(phone).post("/channels/sendbox/return", json={"query": query})

    def test_return_binds_fresh_connect_without_state(self) -> None:
        remote = [{"id": "acc-9", "username": "sozan_core", "active": False}]
        with tempfile.TemporaryDirectory() as raw, self.assertLogs("sozan.sendbox", level="INFO") as captured:
            with patch.object(settings, "state_dir", raw):
                sendbox_service.mark_connect_started("09135409482")
            res = self._return(raw, "09135409482", {"account_id": "acc-9", "username": "sozan_core"}, remote)
        self.assertEqual(res.status_code, 200, res.text)
        account = res.json().get("account") or {}
        self.assertEqual(account.get("handle"), "sozan_core")
        self.assertTrue(account.get("connected"))
        logged = "\n".join(captured.output)
        self.assertIn("account_id", logged)
        self.assertNotIn("acc-9", logged)
        self.assertNotIn("sozan_core", logged)

    def test_return_refuses_stale_connect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pending = Path(raw) / "sendbox-pending.json"
            pending.write_text(
                '{"09135409482": {"t": %s, "n": "abcd"}}' % (time.time() - 4000),
                encoding="utf-8",
            )
            res = self._return(
                raw,
                "09135409482",
                {"account_id": "acc-9"},
                [{"id": "acc-9", "username": "sozan_core", "active": True}],
            )
        self.assertEqual(res.status_code, 400)
        self.assertIn("منقضی", res.json()["detail"])

    def test_return_refuses_account_owned_by_another_shop(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(
                sendbox_service, "_kick_scan", lambda **kwargs: None
            ), patch.object(sendbox_service, "_schedule_activate", lambda account_id: None):
                sendbox_service.bind_instagram(account_id="acc-9", phone="09111111111", handle="sozan_core")
                sendbox_service.mark_connect_started("09135409482")
            res = self._return(
                raw,
                "09135409482",
                {"account_id": "acc-9", "username": "sozan_core"},
                [{"id": "acc-9", "username": "sozan_core", "active": True}],
            )
        self.assertEqual(res.status_code, 400)
        self.assertIn("فروشندهٔ دیگری", res.json()["detail"])

    def test_return_refuses_account_missing_from_sendbox(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                sendbox_service.mark_connect_started("09135409482")
            res = self._return(raw, "09135409482", {"account_id": "acc-missing"}, [])
        self.assertEqual(res.status_code, 400)
        self.assertIn("در Sendbox نیست", res.json()["detail"])
