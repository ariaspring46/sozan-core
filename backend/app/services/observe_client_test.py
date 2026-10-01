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


class OutboxBehaviourTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state = patch.object(settings, "state_dir", self._tmp.name)
        self._state.start()
        self.addCleanup(self._state.stop)
        self._token = None
        from app.state_store import reset_tenant, set_tenant

        self._token = set_tenant("09121110000")
        self.addCleanup(lambda: reset_tenant(self._token))
        observe_client._outbox_rows.clear()
        observe_client._dropped_pending = 0
        observe_client._flush_cooldown_until = 0.0

    def test_append_never_emits_an_event_itself(self) -> None:
        """A full outbox must not queue an event per drop (that was a runaway loop)."""
        with patch.object(observe_client, "emit_later") as spy:
            for i in range(observe_client._OUTBOX_MAX_ROWS + 500):
                observe_client._append_outbox({"i": i})
        spy.assert_not_called()

    def test_trim_is_amortised_not_per_event(self) -> None:
        path = observe_client.outbox_path()
        rewrites = {"n": 0}
        real = observe_client._write_lines

        def counting(p, lines):
            rewrites["n"] += 1
            return real(p, lines)

        with patch.object(observe_client, "_write_lines", counting):
            for i in range(observe_client._OUTBOX_MAX_ROWS + 800):
                observe_client._append_outbox({"i": i})
        self.assertLessEqual(rewrites["n"], 3)
        self.assertLessEqual(len(observe_client.load_outbox()), observe_client._OUTBOX_MAX_ROWS)
        self.assertEqual(observe_client.load_outbox()[-1]["i"], observe_client._OUTBOX_MAX_ROWS + 799)
        self.assertTrue(path.is_file())

    def test_no_marker_rows_are_written(self) -> None:
        for i in range(observe_client._OUTBOX_MAX_ROWS + 100):
            observe_client._append_outbox({"i": i})
        self.assertFalse(any("dropped" in row for row in observe_client.load_outbox()))

    def test_drop_count_is_reported_after_a_successful_flush(self) -> None:
        import asyncio

        for i in range(observe_client._OUTBOX_MAX_ROWS + 100):
            observe_client._append_outbox({"i": i})
        self.assertGreater(observe_client._dropped_pending, 0)
        posted = []

        async def ok(row):
            posted.append(row)
            return True

        with patch.object(observe_client, "_post_event", new=ok):
            asyncio.run(observe_client.flush_outbox(limit=5))
        self.assertTrue(any(r.get("title") == "observe-outbox-dropped" for r in posted))
        self.assertEqual(observe_client._dropped_pending, 0)

    def test_rows_appended_during_a_flush_survive(self) -> None:
        import asyncio

        observe_client._append_outbox({"n": 1})

        async def ok_then_append(row):
            observe_client._append_outbox({"n": 2})  # arrives while we are sending
            return True

        with patch.object(observe_client, "_post_event", new=ok_then_append):
            asyncio.run(observe_client.flush_outbox(limit=5))
        self.assertEqual([r["n"] for r in observe_client.load_outbox()], [2])


if __name__ == "__main__":
    unittest.main()
