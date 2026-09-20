import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import channel_service
from app.state_store import tenant_scope


class ChannelConnectFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_hub_telegram_handle_becomes_post_target(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch.object(
            settings, "telegram_bot_token", "hub-token"
        ):
            out = channel_service.add_account(platform="telegram", handle="myshop", skip_limit=True)
        row = out["account"]
        self.assertEqual(row["postTarget"], "@myshop")
        self.assertTrue(row["connected"])

    def test_whatsapp_handle_becomes_post_target(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name):
            out = channel_service.add_account(
                platform="whatsapp",
                handle="98912000000",
                credentials={"phoneNumberId": "pn1", "accessToken": "tok"},
                skip_limit=True,
            )
        self.assertEqual(out["account"]["postTarget"], "98912000000")


if __name__ == "__main__":
    unittest.main()
