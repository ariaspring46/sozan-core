from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / "local-ai/smoke-workspace/site-builder/tools"))
from sozan_factory_fastpath import classify_error  # noqa: E402


class FactoryErrorClassTests(unittest.TestCase):
    def test_classes(self) -> None:
        self.assertEqual(classify_error("watchdog: heartbeat stale"), "watchdog")
        self.assertEqual(classify_error("docker cp failed"), "docker")
        self.assertEqual(classify_error("gateway_down"), "cloud")
        self.assertEqual(classify_error("catalog empty"), "catalog")
        self.assertEqual(classify_error("unknown boom", default="build"), "build")
