from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import observe_client


class OutboxCapTests(unittest.TestCase):
    def setUp(self) -> None:
        # a daemon thread left by an earlier test (emit_later without a loop) may still be flushing the outbox and would
        # rewrite the file under this test; wait for such threads (bounded) so the cap is measured alone
        import threading

        for thread in threading.enumerate():
            if thread is not threading.main_thread() and thread.daemon and not thread.name.startswith("sozan-"):
                thread.join(timeout=8)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state = patch.object(settings, "state_dir", self._tmp.name)
        self._state.start()
        self.addCleanup(self._state.stop)
        enabled = patch.object(observe_client, "OUTBOX_ENABLED", True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def test_cap_two_thousand_rows(self) -> None:
        for i in range(2100):
            observe_client._append_outbox({"i": i})
        rows = observe_client.load_outbox()
        self.assertLessEqual(len(rows), observe_client._OUTBOX_MAX_ROWS + 1)
        # تازه‌ترین ردیف مانده باشد
        self.assertEqual(rows[-1].get("i"), 2099)
        self.assertGreater(int(rows[0].get("dropped") or 0), 0)

    def test_full_outbox_never_feeds_itself(self) -> None:
        import asyncio

        async def down(_row):
            return False

        async def run():
            observe_client.emit_later(kind="inbox", title="real")
            await asyncio.sleep(0.3)

        for i in range(observe_client._OUTBOX_MAX_ROWS):
            observe_client._append_outbox({"i": i})
        with patch.object(observe_client, "_post_event", new=down), patch.object(
            observe_client, "_flush_cooldown_until", 10**12
        ):
            asyncio.run(run())
        rows = observe_client.load_outbox()
        self.assertFalse(any(r.get("title") == "observe-outbox-dropped" for r in rows))
        self.assertEqual(rows[-1].get("title"), "real")
        self.assertGreaterEqual(int(rows[0].get("dropped") or 0), 1)
        self.assertLessEqual(len(rows), observe_client._OUTBOX_MAX_ROWS)

    def test_rows_appended_during_flush_survive(self) -> None:
        import asyncio

        async def slow_fail(_row):
            observe_client._append_outbox({"late": True})
            return False

        observe_client._append_outbox({"eventId": "a"})
        with patch.object(observe_client, "_post_event", new=slow_fail), patch.object(
            observe_client, "_flush_cooldown_until", 0
        ):
            asyncio.run(observe_client.flush_outbox(limit=5))
        rows = observe_client.load_outbox()
        self.assertEqual([r.get("eventId") for r in rows if "eventId" in r], ["a"])
        self.assertTrue(any(r.get("late") for r in rows))

    def test_thread_event_keeps_tenant(self) -> None:
        import threading
        from app.state_store import tenant_scope

        seen = []
        done = threading.Event()

        async def capture(body):
            seen.append(body.get("tenant"))
            done.set()
            return True

        with patch.object(observe_client, "_post_event", new=capture), tenant_scope("09120000001"):
            observe_client.emit_later(kind="studio", title="from-thread")
            done.wait(5)
        self.assertEqual(seen, ["09120000001"])

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
