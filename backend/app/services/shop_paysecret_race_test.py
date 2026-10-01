import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.state_store import tenant_scope, write_json
from app.services import shop_service


class PaySecretPreservationTests(unittest.TestCase):
    def test_stale_save_does_not_wipe_pay_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09121111111"):
                write_json("shop.json", {"slug": "galri", "port": 1, "paySecret": "sec-keep-me"})
                # دیکشنری کهنه‌ای که قبل از ensure_pay_secret خوانده شده بود
                shop_service._save_shop({"slug": "galri", "port": 2, "status": "queued"})
                data = __import__("json").load(open(Path(raw) / "tenants" / "09121111111" / "shop.json"))
        self.assertEqual(data.get("paySecret"), "sec-keep-me")
        self.assertEqual(data.get("status"), "queued")


if __name__ == "__main__":
    unittest.main()
