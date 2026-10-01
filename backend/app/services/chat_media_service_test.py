import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import chat_media_service
from app.state_store import reset_tenant, set_tenant, tenant_dir

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63000100000005000100a5f645400000000049454e44ae426082"
)


class SweepKeepsReferencedMedia(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(settings, "state_dir", self._tmp.name)
        self._patch.start()
        self._token = set_tenant("09121110000")

    def tearDown(self) -> None:
        reset_tenant(self._token)
        self._patch.stop()
        self._tmp.cleanup()

    def _age(self, name: str, hours: int = 25) -> None:
        path = chat_media_service.media_dir() / name
        old = time.time() - hours * 3600
        os.utime(path, (old, old))

    def test_receipt_image_survives_a_day(self) -> None:
        saved = chat_media_service.save("receipt.png", PNG, "image/png")
        (tenant_dir() / "pay-orders.json").write_text(
            json.dumps([{"id": "o1", "status": "awaiting_receipt", "receipt": saved["name"]}])
        )
        self._age(saved["name"])
        chat_media_service.save("other.png", PNG, "image/png")
        self.assertTrue((chat_media_service.media_dir() / saved["name"]).is_file())

    def test_ticket_inbox_and_shop_chat_media_survive(self) -> None:
        names = {}
        for key, file in (
            ("ticket", "support-tickets.json"),
            ("inbox", "inbox.json"),
            ("shop", "shop-messages.json"),
        ):
            saved = chat_media_service.save(f"{key}.png", PNG, "image/png")
            names[key] = saved["name"]
            (tenant_dir() / file).write_text(json.dumps([{"image": saved["name"]}]))
            self._age(saved["name"])
        chat_media_service.save("trigger.png", PNG, "image/png")
        for name in names.values():
            self.assertTrue((chat_media_service.media_dir() / name).is_file(), name)

    def test_unreferenced_old_file_is_still_swept(self) -> None:
        saved = chat_media_service.save("lost.png", PNG, "image/png")
        self._age(saved["name"])
        chat_media_service.save("trigger.png", PNG, "image/png")
        self.assertFalse((chat_media_service.media_dir() / saved["name"]).is_file())


if __name__ == "__main__":
    unittest.main()
