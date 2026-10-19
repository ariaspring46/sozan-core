"""deploy/wait-health.sh: a healthy restart that answers late must pass, a dead one must fail only after the full wait.

deploy-api.sh used to sleep 3 s and ask once; the API needs about 4 s to start, so the check read a healthy restart as
hung and the fallback killed the fresh process (seen on 2026-10-18 and 2026-10-19).
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SCRIPT = DEPLOY / "wait-health.sh"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve_after(port: int, delay: float, status: int = 200) -> threading.Thread:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args) -> None:
            return

    def run() -> None:
        time.sleep(delay)
        server = HTTPServer(("127.0.0.1", port), Handler)
        server.timeout = 0.5
        end = time.monotonic() + 20
        while time.monotonic() < end:
            server.handle_request()
        server.server_close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def wait(port: int, seconds: int) -> tuple[subprocess.CompletedProcess, float]:
    started = time.monotonic()
    done = subprocess.run(["bash", str(SCRIPT), f"http://127.0.0.1:{port}/health", str(seconds)], capture_output=True, text=True, timeout=60)
    return done, time.monotonic() - started


class WaitHealthTests(unittest.TestCase):
    def test_a_service_that_is_already_up_passes_at_once(self) -> None:
        port = free_port()
        serve_after(port, 0)
        time.sleep(0.3)
        done, took = wait(port, 10)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"ok":true}')
        self.assertLess(took, 4)

    def test_a_service_that_answers_after_four_seconds_passes(self) -> None:
        # the old check asked once after 3 s and called this hung
        port = free_port()
        serve_after(port, 4)
        done, took = wait(port, 15)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreaterEqual(took, 3.5)
        self.assertLess(took, 12)

    def test_a_service_that_never_answers_fails_only_after_the_whole_wait(self) -> None:
        port = free_port()
        done, took = wait(port, 3)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no health", done.stderr)
        self.assertGreaterEqual(took, 3)
        self.assertLess(took, 12)

    def test_an_unhealthy_answer_is_not_health(self) -> None:
        port = free_port()
        serve_after(port, 0, status=500)
        time.sleep(0.3)
        done, _ = wait(port, 2)
        self.assertEqual(done.returncode, 1)

    def test_a_missing_url_is_refused(self) -> None:
        done = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(done.returncode, 0)


# The hub gets only the files deploy-api.sh ships (wait-health.sh among them), not deploy-api.sh itself: these checks run in CI.
@unittest.skipUnless((DEPLOY / "deploy-api.sh").is_file(), "deploy-api.sh is not part of the files shipped to the hub")
class DeployScriptTests(unittest.TestCase):
    def test_the_scripts_parse(self) -> None:
        for name in ("deploy-api.sh", "wait-health.sh"):
            done = subprocess.run(["bash", "-n", str(DEPLOY / name)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f"{name}: {done.stderr}")

    def test_deploy_api_waits_for_health_instead_of_asking_once(self) -> None:
        text = (DEPLOY / "deploy-api.sh").read_text(encoding="utf-8")
        self.assertNotIn("sleep 3 && curl", text)
        self.assertNotIn("sleep 3; curl", text)
        # both the normal restart and the fallback restart wait; the helper travels with the other deploy files
        self.assertEqual(text.count("deploy/wait-health.sh http://127.0.0.1:8012/health"), 2)
        self.assertIn("deploy/wait-health.sh deploy/sozan-worker.service", text)

    def test_the_fallback_only_kills_the_api_process(self) -> None:
        text = (DEPLOY / "deploy-api.sh").read_text(encoding="utf-8")
        self.assertIn('grep -q "app.main:app"', text)
        self.assertIn("not sozan-api; not killed", text)


if __name__ == "__main__":
    unittest.main()
