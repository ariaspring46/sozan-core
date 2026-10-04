import unittest
from unittest.mock import patch

from app.services import admin_health_service as h


def _snap(**over):
    snap = {
        "services": {"sozan-api": "active", "sozan-worker": "active", "sozan-panel": "active", "nginx": "active"},
        "machine": {"diskFreeGb": 25.0, "diskUsedPct": 60, "memAvailableGb": 7.0, "load1": 0.5, "cpus": 4},
        "public": {"apiCode": 200, "apiMs": 300, "downSince": ""},
        "backups": {"lastAgeHours": 6.0},
        "logs": {"hour": {"requests": {"ok": 10}}, "day": {}, "recent": []},
        "ai": {"openrouterLeftUsd": 40.0},
        "shops": {"mapped": 9, "containersUp": 8},
    }
    snap.update(over)
    return snap


class AdminHealthTests(unittest.TestCase):
    def test_healthy_hub_has_no_alerts(self) -> None:
        self.assertEqual(h._alerts(_snap()), [])

    def test_outage_sms_and_credit_are_red(self) -> None:
        alerts = h._alerts(
            _snap(
                public={"apiCode": 504, "apiMs": 15000, "downSince": ""},
                logs={"hour": {"smsFailed": 4, "requests": {"5xx": 6}}, "day": {}, "recent": []},
                ai={"openrouterLeftUsd": 0.5},
                services={"sozan-api": "active", "sozan-worker": "failed", "sozan-panel": "active", "nginx": "active"},
            )
        )
        reds = [a["text"] for a in alerts if a["level"] == "red"]
        self.assertEqual(len(reds), 5)
        self.assertTrue(any("sozan-worker" in t for t in reds))

    def test_log_tally_and_phone_masking(self) -> None:
        lines = [
            '2026-10-04T14:30:38+0000 hub uvicorn[1]: INFO:     1.2.3.4:0 - "POST /auth/otp/send HTTP/1.1" 502 Bad Gateway',
            "2026-10-04T14:30:38+0000 hub uvicorn[1]: melipayamak pattern request failed: ConnectTimeout",
            "2026-10-04T14:31:00+0000 hub uvicorn[1]: llm router failed: ConnectTimeout for 09135409482",
        ]
        with patch.object(h, "_journal", return_value=lines), patch.object(h.time, "strftime", return_value="2026-10-04T14:00"):
            out = h.logs()
        self.assertEqual(out["hour"]["otpSend"], {"502": 1})
        self.assertEqual(out["hour"]["smsFailed"], 1)
        self.assertEqual(out["day"]["llmFailed"], 1)
        self.assertTrue(all("09135409482" not in line for line in out["recent"]))

    def test_a_broken_probe_does_not_break_the_page(self) -> None:
        with patch.object(h, "services", side_effect=RuntimeError("x")), patch.object(h, "public", return_value={"apiCode": 200}), patch.object(
            h, "ai", return_value={}
        ):
            snap = h.snapshot()
        self.assertEqual(snap["services"], {"error": "RuntimeError"})
        self.assertIn("alerts", snap)


if __name__ == "__main__":
    unittest.main()
