"""CI only: a hung test run prints every thread's stack and fails after WATCHDOG_SECONDS instead of hanging for the
runner's six hours. Discovery imports this module with the tests; it holds no tests itself.

2026-10-09: the feat/harness-v2 suite hung on GitHub's Python 3.11 after router_embed_test (it passes in 60 s on the
hub's 3.12), and the dot-only log could not say where.
"""

import faulthandler
import os
import sys

WATCHDOG_SECONDS = 600

if os.environ.get("CI") == "true":
    faulthandler.dump_traceback_later(WATCHDOG_SECONDS, exit=True, file=sys.stderr)
