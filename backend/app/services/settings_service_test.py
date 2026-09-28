from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from pathlib import Path

from app.config import settings
from app.services import settings_service
from app.state_store import read_json, tenant_scope, write_json


class SettingsGuardTests(unittest.TestCase):
    def test_tenant_cannot_set_mock_sms(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                write_json("settings.json", {"mockSms": False, "otpTtlSeconds": 300}, shared=True)
                with self.assertRaises(PermissionError):
                    settings_service.save_settings({"mockSms": True}, hub_admin=False)
                stored = read_json("settings.json", {}, shared=True)
        self.assertEqual(stored.get("mockSms"), False)

    def test_hub_admin_can_set_mock_sms(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                write_json("settings.json", {"mockSms": False}, shared=True)
                settings_service.save_settings({"mockSms": True}, hub_admin=True)
                stored = read_json("settings.json", {}, shared=True)
        self.assertEqual(stored.get("mockSms"), True)

    def test_otp_ttl_out_of_range(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                with self.assertRaises(ValueError):
                    settings_service.save_settings({"otpTtlSeconds": 10}, hub_admin=True)
                with self.assertRaises(ValueError):
                    settings_service.save_settings({"otpTtlSeconds": 901}, hub_admin=True)

    def test_training_off_stores_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09120000991"):
            self.assertTrue(settings_service.allows_training())
            settings_service.save_training_choice(False)
            dest = Path(raw) / "samples.jsonl"
            self.assertFalse(settings_service.note_training_example({"task": "router"}, dest))
            self.assertFalse(dest.exists())
            settings_service.save_training_choice(True)
            self.assertTrue(settings_service.note_training_example({"task": "router"}, dest))
            self.assertTrue(dest.is_file())
            self.assertIn("router", dest.read_text())
