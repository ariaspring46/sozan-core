from __future__ import annotations

import unittest
from pathlib import Path
import sys

_FACTORY_TOOLS = Path.home() / "local-ai/smoke-workspace/site-builder/tools"
if _FACTORY_TOOLS.is_dir():
    sys.path.insert(0, str(_FACTORY_TOOLS))

try:
    from sozan_factory_fastpath import classify_error
except ImportError:  # pragma: no cover
    classify_error = None


@unittest.skipUnless(classify_error, "factory script is not on this machine")
class FactoryErrorClassTests(unittest.TestCase):
    def test_classes(self) -> None:
        self.assertEqual(classify_error("watchdog: heartbeat stale"), "watchdog")
        self.assertEqual(classify_error("docker cp failed"), "docker")
        self.assertEqual(classify_error("gateway_down"), "cloud")
        self.assertEqual(classify_error("catalog empty"), "catalog")
        self.assertEqual(classify_error("unknown boom", default="build"), "build")
