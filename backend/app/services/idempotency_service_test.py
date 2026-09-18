from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import idempotency_service
from app.state_store import tenant_scope


class IdempotencyTests(unittest.TestCase):
    def test_same_key_returns_stored_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                self.assertIsNone(idempotency_service.get("shop-chat", "k1"))
                idempotency_service.put("shop-chat", "k1", {"ok": True})
                self.assertEqual(idempotency_service.get("shop-chat", "k1"), {"ok": True})
                self.assertIsNone(idempotency_service.get("shop-chat", ""))
