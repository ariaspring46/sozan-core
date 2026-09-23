from __future__ import annotations

import tempfile
import threading
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
                idempotency_service.put("shop-chat", "k1", {"ok": True}, stamp="status")
                self.assertEqual(idempotency_service.get("shop-chat", "k1", "status"), {"ok": True})
                with self.assertRaises(idempotency_service.Mismatch):
                    idempotency_service.get("shop-chat", "k1", "hello")
                self.assertIsNone(idempotency_service.get("shop-chat", ""))

    def test_concurrent_puts_keep_both_keys(self) -> None:
        workers = 6
        steps = 15
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                errors: list[BaseException] = []
                barrier = threading.Barrier(workers)

                def worker(ident: int) -> None:
                    try:
                        with tenant_scope("09123456789"):
                            barrier.wait()
                            for step in range(steps):
                                idempotency_service.put("shop-chat", f"{ident}-{step}", {"n": ident})
                    except BaseException as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=worker, args=(ident,)) for ident in range(workers)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                missing = [
                    f"{ident}-{step}"
                    for ident in range(workers)
                    for step in range(steps)
                    if idempotency_service.get("shop-chat", f"{ident}-{step}") != {"n": ident}
                ]
        self.assertEqual(errors, [])
        self.assertEqual(missing, [])
