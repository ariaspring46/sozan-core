from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.state_store import read_json, tenant_scope, write_json
from time import time


class RenewalReminderTests(unittest.TestCase):
    def test_reminds_only_at_3_and_1_days_once(self) -> None:
        from app.services import renewal_reminder_service as rr

        sent: list[str] = []

        async def fake_sms(phone: str, text: str) -> bool:
            sent.append(phone)
            return True

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json(
                    "plan.json",
                    {"plan": "pro", "at": int(time()), "paidUntil": int(time()) + 3 * 86400 + 600},
                )
                with patch.object(rr, "_send_sms", new=fake_sms), patch.object(
                    rr.settings, "sozan_sms_api_key", "k"
                ), patch.object(rr.settings, "sozan_sms_template", "1"):
                    out = asyncio.run(rr.run_once())
                    self.assertEqual(out["sent"], 1)
                    # دوباره: همان روزِ مانده تکرار نمی‌شود
                    out2 = asyncio.run(rr.run_once())
                self.assertEqual(out2["sent"], 0)
        self.assertEqual(sent, ["09135409482"])

    def test_no_reminder_far_from_expiry(self) -> None:
        from app.services import renewal_reminder_service as rr

        sent: list[str] = []

        async def fake_sms(phone: str, text: str) -> bool:
            sent.append(phone)
            return True

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json("plan.json", {"plan": "pro", "paidUntil": int(time()) + 12 * 86400})
                with patch.object(rr, "_send_sms", new=fake_sms):
                    out = asyncio.run(rr.run_once())
        self.assertEqual(out["sent"], 0)

    def test_silent_without_sms_key(self) -> None:
        from app.services import renewal_reminder_service as rr

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json("plan.json", {"plan": "pro", "paidUntil": int(time()) + 86400})
                with patch.object(rr.settings, "sozan_sms_api_key", ""):
                    out = asyncio.run(rr.run_once())
        self.assertEqual(out["sent"], 0)


if __name__ == "__main__":
    unittest.main()
