import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.config import settings
from app.repositories.brand_repository import BrandRepository
from app.services import chat_media_service
from app.services.brand_service import BrandService
from app.state_store import tenant_scope


class UploadLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(settings, "state_dir", self.tmp.name)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_media_cap_and_abandoned_files(self) -> None:
        with tenant_scope("09120000000"):
            root = chat_media_service.media_dir()
            stale = root / "old.png"
            stale.write_bytes(b"x")
            old = time.time() - chat_media_service.ORPHAN_SEC - 10
            os.utime(stale, (old, old))
            nest = root / "leftover"
            nest.mkdir()
            gone = nest / "gone.png"
            gone.write_bytes(b"y")
            os.utime(gone, (old, old))
            kept = root / "kept.png"
            kept.write_bytes(b"z")
            (root.parent / "router-a-messages.json").write_text('{"name": "kept.png"}', encoding="utf-8")
            os.utime(kept, (old, old))
            chat_media_service.sweep_abandoned()
            self.assertFalse(stale.exists())
            self.assertFalse(nest.exists())
            self.assertTrue(kept.is_file())
            with self.assertRaises(HTTPException):
                chat_media_service.save("big.png", b"a" * (chat_media_service.MEDIA_MAX + 1), "image/png")

    def test_logo_cap_is_five_megabytes(self) -> None:
        brand = BrandRepository(Path(self.tmp.name) / "brand", Path(self.tmp.name) / "fonts")
        service = BrandService(brand)
        with self.assertRaises(HTTPException):
            service.save_logo("logo.png", b"a" * (5 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
