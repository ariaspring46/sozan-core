from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.config import settings
from app.services import chat_media_service, public_media_service
from app.state_store import tenant_scope

PHONE = "09135409482"
JPG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


class PublicMediaLinkTests(unittest.TestCase):
    """A public media link must not carry the seller's phone number, and must still resolve to the right file."""

    def test_link_does_not_show_the_phone_and_still_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw):
            with tenant_scope(PHONE):
                saved = chat_media_service.save("pic.jpg", JPG, "image/jpeg", sweep=False)
                token = public_media_service.mint(name=saved["name"], ttl=600)
            decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
            self.assertNotIn(PHONE, decoded)
            path = public_media_service.resolve_token(token)
            self.assertEqual(path.name, saved["name"])
            self.assertEqual(Path(path).read_bytes(), JPG)

    def test_a_changed_link_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw):
            with tenant_scope(PHONE):
                saved = chat_media_service.save("pic.jpg", JPG, "image/jpeg", sweep=False)
                token = public_media_service.mint(name=saved["name"], ttl=600)
            flipped = ("A" if token[5] != "A" else "B") + token[6:]
            with self.assertRaises(HTTPException) as ctx:
                public_media_service.resolve_token(flipped)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
