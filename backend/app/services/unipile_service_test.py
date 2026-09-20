import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import channel_service, inbox_service, unipile_service
from app.state_store import tenant_scope


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class UnipileServiceTests(unittest.TestCase):
    def test_instagram_handle_from_connection_params(self) -> None:
        handle, user_id = unipile_service.instagram_handle(
            {
                "id": "acc1",
                "name": "09120000000",
                "connection_params": {"im": {"id": "ig9", "username": "joahr"}},
            }
        )
        self.assertEqual(handle, "joahr")
        self.assertEqual(user_id, "ig9")

    def test_http_proxy_ignores_channel_proxy(self) -> None:
        with patch.object(settings, "unipile_proxy", "socks5h://127.0.0.1:10890"), patch.object(
            settings, "channel_proxy", "socks5h://127.0.0.1:10888"
        ):
            self.assertEqual(unipile_service.http_proxy(), "socks5h://127.0.0.1:10890")
        with patch.object(settings, "unipile_proxy", ""), patch.object(
            settings, "channel_proxy", "socks5h://127.0.0.1:10888"
        ):
            self.assertIsNone(unipile_service.http_proxy())

    def test_webhook_token_matches_secret(self) -> None:
        with patch.object(settings, "jwt_secret", "unit-secret"):
            token = unipile_service.webhook_secret()
            self.assertTrue(unipile_service.valid_webhook_token(token))
            self.assertFalse(unipile_service.valid_webhook_token("nope"))
            self.assertIn("/channels/unipile/webhook", unipile_service.webhook_url())

    def test_notify_token_matches_secret(self) -> None:
        with patch.object(settings, "jwt_secret", "unit-secret"):
            token = unipile_service.notify_secret()
            self.assertTrue(unipile_service.valid_notify_token(token))
            self.assertFalse(unipile_service.valid_notify_token("nope"))
            bound = unipile_service.notify_token_for("09135409482")
            self.assertTrue(unipile_service.valid_notify_token(bound, phone="09135409482"))
            self.assertFalse(unipile_service.valid_notify_token(bound, phone="09120000000"))
            self.assertFalse(unipile_service.valid_notify_token(token, phone="09135409482"))

    def test_start_instagram_returns_hosted_url(self) -> None:
        client = AsyncMock()
        client.post.return_value = _FakeResponse({"url": "https://account.unipile.com/abc"})
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with patch.object(settings, "unipile_dsn", "https://api66.unipile.com:19633"), patch.object(
            settings, "unipile_api_key", "key"
        ), patch.object(settings, "public_api_url", "https://api.sozan-core.ir"), patch.object(
            settings, "panel_url", "https://app.sozan-core.ir"
        ), patch.object(settings, "jwt_secret", "unit-secret"), patch(
            "app.services.unipile_service._client", return_value=client
        ):
            result = asyncio.run(unipile_service.start_instagram(phone="09135409482"))
        self.assertEqual(result["provider"], "unipile")
        self.assertEqual(result["url"], "https://account.unipile.com/abc")
        body = client.post.await_args.kwargs["json"]
        self.assertEqual(body["providers"], ["INSTAGRAM"])
        self.assertEqual(body["name"], "09135409482")
        self.assertIn("/channels/unipile/notify", body["notify_url"])
        self.assertIn("tenant=09135409482", body["notify_url"])

    def test_claim_account_uses_seller_phone_not_unipile_name(self) -> None:
        client = AsyncMock()
        client.get.return_value = _FakeResponse(
            {
                "id": "acc1",
                "name": "ig_handle",
                "connection_params": {"im": {"id": "ig9", "username": "joahr"}},
            }
        )
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(
                settings, "unipile_dsn", "https://api66.unipile.com:19633"
            ), patch.object(settings, "unipile_api_key", "key"), patch(
                "app.services.unipile_service._client", return_value=client
            ), patch(
                "app.services.unipile_service.ensure_messaging_webhook", new=AsyncMock(return_value={"ok": True})
            ):
                with tenant_scope("09135409482"):
                    result = asyncio.run(unipile_service.claim_account(account_id="acc1", phone="09135409482"))
                    row = channel_service.secret_for(str(result["account"]["id"])) or {}
                self.assertTrue(result["account"]["needsReconnect"])
                self.assertFalse(result["account"]["connected"])
                self.assertEqual(result["account"]["error"], channel_service.IG_RECONNECT)
                self.assertEqual(channel_service.unipile_account_id(row), "acc1")
                self.assertTrue((Path(raw) / "tenants" / "09135409482" / "channels.json").is_file())
                self.assertFalse((Path(raw) / "tenants" / "ig_handle" / "channels.json").exists())

    def test_accept_notify_stores_account(self) -> None:
        client = AsyncMock()
        client.get.return_value = _FakeResponse(
            {
                "id": "acc1",
                "name": "09120000000",
                "connection_params": {"im": {"id": "ig9", "username": "joahr"}},
            }
        )
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(
                settings, "unipile_dsn", "https://api66.unipile.com:19633"
            ), patch.object(settings, "unipile_api_key", "key"), patch(
                "app.services.unipile_service._client", return_value=client
            ), patch(
                "app.services.unipile_service.ensure_messaging_webhook", new=AsyncMock(return_value={"ok": True})
            ), tenant_scope("09120000000"):
                account = asyncio.run(
                    unipile_service.accept_notify(
                        {"status": "CREATION_SUCCESS", "account_id": "acc1", "name": "09120000000"}
                    )
                )
                row = channel_service.secret_for(str(account["id"])) or {}
        self.assertEqual(account["handle"], "joahr")
        self.assertTrue(account["needsReconnect"])
        self.assertFalse(account["connected"])
        self.assertEqual(channel_service.unipile_account_id(row), "acc1")

    def test_accept_webhook_imports_instagram_dm(self) -> None:
        payload = {
            "event": "message_received",
            "account_type": "INSTAGRAM",
            "account_id": "acc1",
            "chat_id": "chat1",
            "message_id": "msg1",
            "message": "سلام قیمت؟",
            "sender": {"attendee_name": "مشتری", "attendee_provider_id": "cust1"},
            "account_info": {"user_id": "shop1"},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"unipileAccountId":"acc1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}
            ), patch("app.services.inbox_service.reply", new=AsyncMock()):
                result = asyncio.run(unipile_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(result.get("imported"), 1)
        self.assertEqual(len(threads), 1)

    def test_accept_webhook_duplicate_message_id(self) -> None:
        payload = {
            "event": "message_received",
            "account_type": "INSTAGRAM",
            "account_id": "acc1",
            "chat_id": "chat1",
            "message_id": "msg-dup",
            "message": "سلام",
            "sender": {"attendee_name": "مشتری", "attendee_provider_id": "cust1"},
            "account_info": {"user_id": "shop1"},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"unipileAccountId":"acc1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.plan_service.current", return_value={"autoReply": "", "dmSync": True}
            ), patch("app.services.inbox_service.reply", new=AsyncMock()):
                first = asyncio.run(unipile_service.accept_webhook(payload))
                second = asyncio.run(unipile_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(first.get("imported"), 1)
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(len(threads), 1)

    def test_accept_webhook_skips_self_message(self) -> None:
        payload = {
            "event": "message_received",
            "account_type": "INSTAGRAM",
            "account_id": "acc1",
            "message_id": "msg2",
            "message": "خودم",
            "sender": {"attendee_provider_id": "shop1"},
            "account_info": {"user_id": "shop1"},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"unipileAccountId":"acc1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw):
                result = asyncio.run(unipile_service.accept_webhook(payload))
        self.assertEqual(result.get("ignored"), "self")

    def test_accept_webhook_skips_is_sender(self) -> None:
        payload = {
            "event": "message_received",
            "account_type": "INSTAGRAM",
            "account_id": "acc1",
            "message_id": "msg-self",
            "message": "پاسخ ما",
            "is_sender": True,
            "sender": {"attendee_name": "Sozan Core", "attendee_provider_id": "cust1"},
            "account_info": {"user_id": "shop1"},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"unipileAccountId":"acc1","userId":"shop1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.plan_service.current", return_value={"autoReply": "send", "dmSync": True}
            ), patch("app.services.inbox_service.reply", new=AsyncMock()):
                result = asyncio.run(unipile_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(result.get("ignored"), "self")
        self.assertEqual(threads, [])

    def test_accept_webhook_marks_plan_ignore(self) -> None:
        payload = {
            "event": "message_received",
            "account_type": "INSTAGRAM",
            "account_id": "acc1",
            "chat_id": "chat1",
            "message_id": "msg-plan",
            "message": "سلام",
            "sender": {"attendee_name": "مشتری", "attendee_provider_id": "cust1"},
            "account_info": {"user_id": "shop1"},
        }
        with tempfile.TemporaryDirectory() as raw:
            channels = Path(raw) / "tenants" / "09135409482" / "channels.json"
            channels.parent.mkdir(parents=True)
            channels.write_text(
                '[{"id":"ig1","platform":"instagram","handle":"shop","credentials":{"unipileAccountId":"acc1"}}]',
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), patch(
                "app.services.plan_service.current", return_value={"autoReply": "", "dmSync": False}
            ):
                result = asyncio.run(unipile_service.accept_webhook(payload))
                with tenant_scope("09135409482"):
                    seen = unipile_service._seen()
                    threads = inbox_service.list_threads()["threads"]
        self.assertEqual(result.get("ignored"), "plan")
        self.assertIn("msg-plan", seen)
        self.assertEqual(threads, [])

    def test_unipile_row_counts_as_connected(self) -> None:
        row = {"platform": "instagram", "credentials": {"unipileAccountId": "acc1"}}
        self.assertTrue(channel_service.is_connected(row))
        self.assertEqual(channel_service.unipile_account_id(row), "acc1")


class UnipilePublishTests(unittest.TestCase):
    def test_studio_instagram_does_not_use_unipile(self) -> None:
        from app.services import channel_service, studio_publish_service

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value={"id": "ig", "platform": "instagram", "credentials": {"unipileAccountId": "acc1"}},
            ), patch(
                "app.services.studio_publish_service.channel_service.is_connected",
                return_value=True,
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ):
                with self.assertRaises(ValueError) as ctx:
                    asyncio.run(
                        studio_publish_service.publish(
                            platform="instagram",
                            caption="کپشن اینستا",
                            media_name=path.name,
                            media_kind="image",
                        )
                    )
        self.assertEqual(str(ctx.exception), channel_service.IG_STUDIO_WAIT)


if __name__ == "__main__":
    unittest.main()
