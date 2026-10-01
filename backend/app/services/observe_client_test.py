from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import observe_client


class OutboxCapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state = patch.object(settings, "state_dir", self._tmp.name)
        self._state.start()
        self.addCleanup(self._state.stop)

    def test_cap_two_thousand_rows(self) -> None:
        for i in range(2100):
            observe_client._append_outbox({"i": i})
        rows = observe_client.load_outbox()
        self.assertLessEqual(len(rows), observe_client._OUTBOX_MAX_ROWS + 1)
        # تازه‌ترین ردیف مانده باشد
        self.assertEqual(rows[-1].get("i"), 2099)

    def test_failure_sets_cooldown(self) -> None:
        import time as _t

        async def failing(row):
            return False

        observe_client._append_outbox({"x": 1})
        with patch.object(observe_client, "_post_event", new=failing), patch.object(
            observe_client, "_rewrite_outbox"
        ) as rw:
            import asyncio

            sent = asyncio.run(observe_client.flush_outbox(limit=5))
        self.assertEqual(sent, 0)
        self.assertGreater(observe_client._flush_cooldown_until, _t.time())


if __name__ == "__main__":
    unittest.main()
