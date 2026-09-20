import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import channel_service, inbox_service, sendbox_service
from app.state_store import tenant_scope


class SendboxServiceTests(unittest.TestCase):
    def test_login_url_adds_seller_id(self) -> None:
        with patch.object(settings, "sendbox_api_key", "key"), patch.object(
            settings, "sendbox_oauth_url", "https://api.sendbox.chat/instagram-oauth?token=abc"
        ):
            url = sendbox_service.login_url(phone="09135409482")
            self.assertTrue(sendbox_service.configured())
        self.assertIn("id=09135409482", url)
        self.assertIn("token=abc", url)

    def test_start_instagram_returns_sendbox_url(self) -> None:
        with patch.object(settings, "sendbox_api_key", "key"), patch.object(
            settings, "sendbox_oauth_url", "https://api.sendbox.chat/instagram-oauth?token=abc"
        ), patch("app.services.sendbox_service.fetch_oauth_url", new=AsyncMock(return_value="")), patch(
            "app.services.sendbox_service.list_remote_accounts", new=AsyncMock(return_value=[])
        ):
            result = asyncio.run(sendbox_service.start_instagram(phone="09135409482"))
        self.assertEqual(result["provider"], "sendbox")
        self.assertIn("instagram-oauth", result["url"])
        self.assertIn("id=09135409482", result["url"])

    def test_start_instagram_prefers_live_oauth_url(self) -> None:
        with patch.object(settings, "sendbox_api_key", "key"), patch.object(
            settings, "sendbox_oauth_url", "https://api.sendbox.chat/instagram-oauth?token=abc"
        ), patch(
            "app.services.sendbox_service.fetch_oauth_url",
            new=AsyncMock(return_value="https://api.sendbox.chat/instagram-oauth?token=live"),
        ), patch("app.services.sendbox_service.list_remote_accounts", new=AsyncMock(return_value=[])):
            result = asyncio.run(sendbox_service.start_instagram(phone="09135409482"))
        self.assertIn("token=live", result["url"])
        self.assertIn("id=09135409482", result["url"])

    def test_finish_redirect_stores_account(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(
                settings, "panel_url", "https://app.sozan-core.ir"
            ):
                url = sendbox_service.finish_redirect(
                    status="success",
                    account_id="acc-1",
                    username="joahr",
                    seller_id="09135409482",
                )
                with tenant_scope("09135409482"):
                    row = channel_service.account_for_platform("instagram") or {}
        self.assertIn("instagram=ok", url)
        self.assertTrue(channel_service.is_connected(row))
        self.assertEqual(channel_service.sendbox_account_id(row), "acc-1")
        self.assertIn("account_id=acc-1", url)

    def test_accept_webhook_imports_dm(self) -> None:
        payload = {
            "event_type": "messaging",
            "account_id": "acc-1",
            "data": {
                "messaging": [
                    {
                        "sender": {"id": "cust1"},
                        "recipient": {"id": "page1"},
                        "message": {"mid": "m1", "text": "سلام قیمت؟"},
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
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}
            ), patch("app.services.inbox_service.reply", new=AsyncMock()):
                result = asyncio.run(sendbox_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(result.get("imported"), 1)
        self.assertEqual(len(threads), 1)

    def test_accept_webhook_marks_self(self) -> None:
        payload = {
            "event_type": "messaging",
            "account_id": "acc-1",
            "data": {
                "messaging": [
                    {
                        "sender": {"id": "page1"},
                        "recipient": {"id": "page1"},
                        "message": {"mid": "m-self", "text": "خودم"},
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
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}
            ):
                result = asyncio.run(sendbox_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    seen = sendbox_service._seen()
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(result.get("imported"), 0)
        self.assertIn("m-self", seen)
        self.assertEqual(threads, [])

    def test_sendbox_row_counts_as_connected(self) -> None:
        row = {"platform": "instagram", "credentials": {"sendboxAccountId": "acc-1"}}
        self.assertTrue(channel_service.is_connected(row))
        self.assertEqual(channel_service.sendbox_account_id(row), "acc-1")

    def test_start_instagram_returns_existing_accounts(self) -> None:
        with patch.object(settings, "sendbox_api_key", "key"), patch.object(
            settings, "sendbox_oauth_url", "https://api.sendbox.chat/instagram-oauth?token=abc"
        ), patch("app.services.sendbox_service.fetch_oauth_url", new=AsyncMock(return_value="")), patch(
            "app.services.sendbox_service.list_remote_accounts",
            new=AsyncMock(return_value=[{"id": "acc-9", "username": "kif", "active": True}]),
        ):
            result = asyncio.run(sendbox_service.start_instagram(phone="09135409482"))
        self.assertEqual(result["existing"][0]["id"], "acc-9")
        self.assertFalse(result["existing"][0]["bound"])

    def test_finish_redirect_without_account_id_keeps_onboard(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(
                settings, "panel_url", "https://app.sozan-core.ir"
            ):
                url = sendbox_service.finish_redirect(
                    status="error",
                    account_id="",
                    username="kif",
                    seller_id="09135409482",
                    error="already connected",
                )
        self.assertIn("/onboard?", url)
        self.assertIn("instagram=exists", url)

    def test_accept_webhook_stores_list_posts(self) -> None:
        payload = {
            "event_type": "list_posts",
            "account_id": "acc-1",
            "data": {
                "posts": [
                    {"id": "p1", "caption": "کیف چرم قهوه‌ای", "media_url": "https://cdn.example/a.jpg"},
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
            with patch.object(settings, "state_dir", raw):
                result = asyncio.run(sendbox_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    posts = sendbox_service.take_list_posts("acc-1")
        self.assertEqual(result.get("posts"), 1)
        self.assertEqual(posts[0]["caption"], "کیف چرم قهوه‌ای")

    def test_publish_targets_sendbox_only_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"sendboxAccountId":"acc-1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                targets = channel_service.publish_targets()
        ig = next(row for row in targets if row["platform"] == "instagram")
        self.assertTrue(ig["connected"])
        self.assertFalse(ig["ready"])
        self.assertIn("استودیو", ig["hint"])

    def test_publish_targets_unipile_ready(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"sendboxAccountId":"acc-1","unipileAccountId":"u1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                targets = channel_service.publish_targets()
        ig = next(row for row in targets if row["platform"] == "instagram")
        self.assertTrue(ig["connected"])
        self.assertFalse(ig["ready"])
        self.assertIn("استودیو", ig["hint"])

    def test_upsert_merges_unipile_onto_sendbox_row(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                channel_service.upsert_instagram(
                    handle="acc-1",
                    user_id="acc-1",
                    credentials={"sendboxAccountId": "acc-1"},
                    display="acc-1",
                )
                channel_service.upsert_instagram(
                    handle="kifkocholo",
                    user_id="ig-user",
                    credentials={"unipileAccountId": "u1", "userId": "ig-user"},
                    display="kifkocholo",
                )
                rows = list(channel_service.iter_accounts())
        self.assertEqual(len(rows), 1)
        self.assertEqual(channel_service.sendbox_account_id(rows[0]), "acc-1")
        self.assertEqual(channel_service.unipile_account_id(rows[0]), "u1")
        self.assertEqual(rows[0]["handle"], "kifkocholo")

    def test_sendbox_verify_skips_graph(self) -> None:
        from app.services import channel_connect_service

        with patch("app.services.channel_connect_service.async_client") as client:
            result = asyncio.run(
                channel_connect_service.verify_credentials(
                    platform="instagram",
                    handle="shop",
                    credentials={"sendboxAccountId": "acc-1"},
                )
            )
        client.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertTrue(result["connected"])

    def test_empty_webhook_token_is_rejected(self) -> None:
        self.assertFalse(sendbox_service.valid_webhook_token(""))
        self.assertFalse(sendbox_service.valid_webhook_token("nope"))

    def test_legacy_unipile_row_stays_with_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"unipileAccountId":"u1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                listed = channel_service.list_accounts()["accounts"]
                row = channel_service.secret_for("ig1") or {}
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0]["needsReconnect"])
        self.assertFalse(listed[0]["connected"])
        self.assertEqual(listed[0]["error"], channel_service.IG_RECONNECT)
        self.assertEqual(channel_service.unipile_account_id(row), "u1")

    def test_legacy_meta_token_row_stays_with_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"accessToken":"meta-tok"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                listed = channel_service.list_accounts()["accounts"]
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0]["needsReconnect"])
        self.assertFalse(listed[0]["connected"])
        self.assertEqual(listed[0]["error"], channel_service.IG_RECONNECT)

    def test_deliver_instagram_uses_sendbox_only(self) -> None:
        from app.services import channel_outbound_service

        send = AsyncMock()
        row = {"platform": "instagram", "credentials": {"sendboxAccountId": "acc-1", "unipileAccountId": "u1"}}
        with patch(
            "app.services.channel_outbound_service.channel_service.account_for_platform", return_value=row
        ), patch("app.services.channel_outbound_service.sendbox_service.send_message", send):
            asyncio.run(
                channel_outbound_service.deliver(
                    platform="instagram", sender_id="cust1", chat_id="cust1", text="سلام"
                )
            )
        send.assert_awaited_once_with(account_id="acc-1", recipient_id="cust1", text="سلام")

    def test_deliver_unipile_requires_reconnect(self) -> None:
        from app.services import channel_outbound_service

        row = {"platform": "instagram", "credentials": {"unipileAccountId": "u1"}}
        with patch(
            "app.services.channel_outbound_service.channel_service.account_for_platform", return_value=row
        ), patch("app.services.channel_outbound_service.sendbox_service.send_message", new=AsyncMock()) as send:
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(
                    channel_outbound_service.deliver(
                        platform="instagram", sender_id="cust1", chat_id="cust1", text="سلام"
                    )
                )
        send.assert_not_called()
        self.assertEqual(str(ctx.exception), channel_service.IG_RECONNECT)

    def test_legacy_unipile_verify_skips_graph(self) -> None:
        from app.services import channel_connect_service

        with patch("app.services.channel_connect_service.async_client") as client:
            result = asyncio.run(
                channel_connect_service.verify_credentials(
                    platform="instagram",
                    handle="shop",
                    credentials={"unipileAccountId": "u1", "accessToken": "meta"},
                )
            )
        client.assert_not_called()
        self.assertFalse(result["connected"])
        self.assertEqual(result["error"], channel_service.IG_RECONNECT)

    def test_set_account_active_puts_false(self) -> None:
        from types import SimpleNamespace

        fake = AsyncMock()
        fake.__aenter__.return_value = fake
        fake.__aexit__.return_value = False
        fake.put = AsyncMock(return_value=SimpleNamespace(status_code=200))
        with patch.object(settings, "sendbox_api_key", "key"), patch(
            "app.services.sendbox_service._client", return_value=fake
        ):
            asyncio.run(sendbox_service.set_account_active(account_id="acc-1", active=False))
        fake.put.assert_awaited_once()
        url = fake.put.await_args.args[0]
        self.assertIn("/service/accounts/acc-1", url)
        self.assertEqual(fake.put.await_args.kwargs["json"], {"is_active": False})

    def test_release_local_account_disables_sendbox(self) -> None:
        disable = AsyncMock()
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"sendboxAccountId":"acc-1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"), patch(
                "app.services.sendbox_service.set_account_active", disable
            ):
                listed = asyncio.run(sendbox_service.release_local_account("ig1"))
        disable.assert_awaited_once_with(account_id="acc-1", active=False)
        self.assertEqual(listed["accounts"], [])

    def test_sendbox_client_uses_socks5h(self) -> None:
        from app.services.channel_http import channel_proxy

        with patch.object(settings, "channel_proxy", "socks5://127.0.0.1:10888"):
            self.assertEqual(channel_proxy(), "socks5h://127.0.0.1:10888")
        with patch.object(settings, "channel_proxy", ""):
            client = sendbox_service._client()
        try:
            self.assertFalse(client.trust_env)
        finally:
            asyncio.run(client.aclose())
