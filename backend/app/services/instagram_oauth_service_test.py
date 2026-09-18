import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import channel_service, instagram_oauth_service
from app.state_store import tenant_scope


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class InstagramOauthTests(unittest.TestCase):
    def test_short_token_reads_top_level_and_data_list(self) -> None:
        token, user_id = instagram_oauth_service.short_token_from(
            {"access_token": "IGQVJshort", "user_id": "1784"}
        )
        self.assertEqual(token, "IGQVJshort")
        self.assertEqual(user_id, "1784")
        nested, nested_id = instagram_oauth_service.short_token_from(
            {"data": [{"access_token": "IGQVJnest", "user_id": "99"}]}
        )
        self.assertEqual(nested, "IGQVJnest")
        self.assertEqual(nested_id, "99")
        self.assertEqual(instagram_oauth_service.strip_auth_code("abc#_"), "abc")

    def test_authorize_url_binds_tenant_state(self) -> None:
        store: dict[str, str] = {}

        async def setex(key: str, _ttl: int, value: str) -> None:
            store[key] = value

        with patch.object(settings, "instagram_app_id", "9906"), patch.object(
            settings, "instagram_app_secret", "s3cret"
        ), patch.object(settings, "instagram_redirect_uri", ""), patch.object(
            settings, "public_api_url", "https://api.sozan-core.ir"
        ), patch.object(
            instagram_oauth_service, "redis_client", SimpleNamespace(setex=setex)
        ):
            result = asyncio.run(instagram_oauth_service.start_login(phone="09135409482"))
        self.assertTrue(result["configured"])
        url = result["url"]
        self.assertIn("https://www.instagram.com/oauth/authorize?", url)
        self.assertIn("client_id=9906", url)
        self.assertIn("instagram_business_basic", url)
        self.assertIn("instagram_business_content_publish", url)
        self.assertIn("instagram_business_manage_messages", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fapi.sozan-core.ir%2Fchannels%2Finstagram%2Fcallback", url)
        self.assertIn("enable_fb_login=0", url)
        self.assertNotIn("force_reauth", url)
        self.assertEqual(len(store), 1)
        key = next(iter(store))
        self.assertIn("09135409482", store[key])
        self.assertIn(key.split("ig-oauth:", 1)[-1], url)

    def test_missing_app_credentials_fail_closed(self) -> None:
        with patch.object(settings, "instagram_app_id", ""), patch.object(settings, "instagram_app_secret", ""):
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(instagram_oauth_service.start_login(phone="09120000000"))
        self.assertIn("تنظیم نشده", str(ctx.exception))

    def test_callback_denied_and_expired_go_to_panel(self) -> None:
        with patch.object(settings, "panel_url", "https://app.sozan-core.ir"), patch.object(
            settings, "instagram_app_id", "1"
        ), patch.object(settings, "instagram_app_secret", "s"):
            denied = asyncio.run(
                instagram_oauth_service.finish_redirect(code="", state="x", error="access_denied")
            )
            expired = asyncio.run(instagram_oauth_service.finish_redirect(code="c", state="", error=""))
        self.assertEqual(denied, "https://app.sozan-core.ir/more/channels?instagram=denied")
        self.assertEqual(expired, "https://app.sozan-core.ir/more/channels?instagram=expired")

    def test_complete_login_stores_long_lived_token(self) -> None:
        client = AsyncMock()
        client.post.return_value = _FakeResponse({"access_token": "short", "user_id": "ig1"})
        client.get.side_effect = [
            _FakeResponse({"access_token": "long", "expires_in": 5184000, "token_type": "bearer"}),
            _FakeResponse({"id": "ig1", "username": "joahr"}),
        ]
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), patch.object(
                settings, "instagram_app_id", "9906"
            ), patch.object(settings, "instagram_app_secret", "s3cret"), patch(
                "app.services.instagram_oauth_service.async_client", return_value=client
            ), tenant_scope("09120000000"):
                account = asyncio.run(instagram_oauth_service.complete_login(phone="09120000000", code="abc#_"))
                row = channel_service.secret_for(str(account["id"])) or {}
                creds = channel_service.credentials_for(row)
        self.assertEqual(account["handle"], "joahr")
        self.assertTrue(account["verified"])
        self.assertEqual(creds["accessToken"], "long")
        self.assertEqual(creds["userId"], "ig1")
        self.assertTrue(int(creds["tokenExpiresAt"]) > 0)
        client.post.assert_awaited()

    def test_upsert_replaces_same_instagram_user(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09120000000"):
                first = channel_service.upsert_instagram(
                    handle="shop",
                    user_id="ig1",
                    credentials={"accessToken": "old", "userId": "ig1"},
                )
                second = channel_service.upsert_instagram(
                    handle="shop",
                    user_id="ig1",
                    credentials={"accessToken": "new", "userId": "ig1"},
                )
                rows = channel_service.iter_accounts()
                self.assertEqual(len(rows), 1)
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(channel_service.token_for(rows[0]), "new")

    def test_should_refresh_near_expiry(self) -> None:
        now = 1_700_000_000
        row = {
            "platform": "instagram",
            "credentials": {
                "accessToken": "tok",
                "tokenExpiresAt": str(now + 3600),
                "tokenIssuedAt": str(now - 2 * 24 * 3600),
            },
        }
        self.assertTrue(instagram_oauth_service.should_refresh(row, now=now))
        fresh = {
            "platform": "instagram",
            "credentials": {
                "accessToken": "tok",
                "tokenExpiresAt": str(now + 40 * 24 * 3600),
                "tokenIssuedAt": str(now - 2 * 24 * 3600),
            },
        }
        self.assertFalse(instagram_oauth_service.should_refresh(fresh, now=now))


if __name__ == "__main__":
    unittest.main()
