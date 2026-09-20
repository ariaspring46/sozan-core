from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.config import settings
from app.state_store import read_json, shared_lock, write_json


class StateStoreGuardTests(unittest.TestCase):
    def test_corrupt_json_logs_and_returns_default(self) -> None:
        with TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                path = Path(raw) / "settings.json"
                path.write_text("{not-json", encoding="utf-8")
                with self.assertLogs("sozan.state", level="WARNING") as captured:
                    out = read_json("settings.json", {"ok": True}, shared=True)
        self.assertEqual(out, {"ok": True})
        self.assertTrue(any("corrupt json" in line for line in captured.output))

    def test_concurrent_shared_writes_keep_all_keys(self) -> None:
        workers = 8
        steps = 20
        with TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                errors: list[BaseException] = []

                def worker(ident: int) -> None:
                    try:
                        for step in range(steps):
                            with shared_lock():
                                data = read_json("pay-pending.json", {}, shared=True)
                                if not isinstance(data, dict):
                                    data = {}
                                data[f"{ident}-{step}"] = ident
                                write_json("pay-pending.json", data, shared=True)
                    except BaseException as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=worker, args=(ident,)) for ident in range(workers)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                stored = read_json("pay-pending.json", {}, shared=True)
        self.assertEqual(errors, [])
        self.assertIsInstance(stored, dict)
        self.assertEqual(len(stored), workers * steps)
