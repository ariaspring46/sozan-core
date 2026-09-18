from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import observe_client, pipeline_release
from app.state_store import tenant_scope


class PipelineReleaseTests(unittest.TestCase):
    def test_release_id_is_stable_for_same_files(self) -> None:
        first = pipeline_release.hub_release_id()
        second = pipeline_release.hub_release_id()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)

    def test_envelope_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                body = pipeline_release.envelope(
                    kind="chat",
                    title="shop-user",
                    surface="shop",
                    turn_id="t1",
                    job_id="j1",
                )
        self.assertEqual(body["eventVersion"], 1)
        self.assertEqual(body["tenant"], "09123456789")
        self.assertEqual(body["turnId"], "t1")
        self.assertEqual(body["jobId"], "j1")
        self.assertTrue(body["releaseId"])
        self.assertEqual(body["behaviorVersion"], pipeline_release.BEHAVIOR_VERSION)


class ObserveOutboxTests(unittest.TestCase):
    def test_failed_emit_lands_in_outbox(self) -> None:
        import asyncio

        async def fail(_body):
            return False

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                with patch.object(observe_client, "_post_event", side_effect=fail):
                    asyncio.run(observe_client.emit(kind="chat", title="missed", surface="shop"))
                rows = observe_client.load_outbox()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "missed")
        self.assertEqual(rows[0]["kind"], "chat")
