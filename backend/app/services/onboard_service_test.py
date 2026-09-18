import asyncio
import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import channel_service, onboard_service, profile_service
from app.state_store import tenant_scope


def _complete(**kwargs):
    payload = {
        "phone": "09123456789",
        "first_name": "علی",
        "last_name": "",
        "brand_name": "کیف کوچولو",
        "brand_work": "کیف چرم",
        "tone_id": "warm",
        "channels": [],
        "logo": None,
        "logo_name": "",
    }
    payload.update(kwargs)
    return asyncio.run(onboard_service.complete(**payload))


class OnboardServiceTests(unittest.TestCase):
    def test_draft_keeps_form_without_onboarded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                snap = onboard_service.save_draft(
                    "09123456789",
                    first_name="علی",
                    last_name="محمدی",
                    brand_name="کیف کوچولو",
                    brand_work="کیف چرم",
                    tone_id="warm",
                )
                profile = profile_service.get_profile("09123456789")
        self.assertFalse(profile["onboarded"])
        self.assertEqual(profile["firstName"], "علی")
        self.assertEqual(profile["brandName"], "کیف کوچولو")
        self.assertIn("accounts", snap)

    def test_complete_scans_typed_instagram_handle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                with patch(
                    "app.services.channel_scan_service.start_scan", return_value={"status": "running"}
                ) as scan, patch("app.services.onboard_service.shop_service.reset_for_brand"), patch(
                    "app.services.onboard_service.channel_service.add_account"
                ) as add, patch("app.services.onboard_service._brand_svc") as brand:
                    brand.return_value.update.return_value = None
                    out = _complete(channels=[{"platform": "instagram", "handle": "kifkocholo"}])
        scan.assert_called_once()
        add.assert_not_called()
        rows = scan.call_args[0][0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "instagram")
        self.assertEqual(rows[0]["handle"], "kifkocholo")
        self.assertEqual(out["channels"][0]["handle"], "kifkocholo")
        self.assertTrue(out["ok"])

    def test_complete_keeps_one_catalog_channel(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                with patch(
                    "app.services.channel_scan_service.start_scan", return_value={"status": "running"}
                ) as scan, patch("app.services.onboard_service.shop_service.reset_for_brand"), patch(
                    "app.services.onboard_service.channel_service.add_account"
                ) as add, patch("app.services.onboard_service._brand_svc") as brand:
                    brand.return_value.update.return_value = None
                    _complete(
                        channels=[
                            {"platform": "instagram", "handle": "kifkocholo"},
                            {"platform": "telegram", "handle": "kifshop"},
                            {"platform": "whatsapp", "handle": "09120000000"},
                        ]
                    )
        add.assert_not_called()
        rows = scan.call_args[0][0]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "instagram")
        self.assertEqual(rows[0]["handle"], "kifkocholo")

    def test_complete_attaches_matching_sendbox(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                channel_service.upsert_instagram(
                    handle="kifkocholo",
                    user_id="acc-1",
                    credentials={"sendboxAccountId": "acc-1"},
                    display="kifkocholo",
                )
                channel_service.apply_verify(
                    str(list(channel_service.iter_accounts())[0]["id"]),
                    {"ok": True, "connected": True, "handle": "kifkocholo", "display": "kifkocholo", "error": ""},
                )
                with patch(
                    "app.services.channel_scan_service.start_scan", return_value={"status": "running"}
                ) as scan, patch("app.services.onboard_service.shop_service.reset_for_brand"), patch(
                    "app.services.onboard_service._brand_svc"
                ) as brand:
                    brand.return_value.update.return_value = None
                    _complete(channels=[{"platform": "instagram", "handle": "kifkocholo"}])
        rows = scan.call_args[0][0]
        self.assertEqual(rows[0]["sendboxAccountId"], "acc-1")

    def test_complete_skips_scan_without_typed_handle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                channel_service.upsert_instagram(
                    handle="kifkocholo",
                    user_id="acc-1",
                    credentials={"sendboxAccountId": "acc-1"},
                    display="kifkocholo",
                )
                with patch(
                    "app.services.channel_scan_service.start_scan", return_value={"status": "running"}
                ) as scan, patch("app.services.onboard_service.shop_service.reset_for_brand"), patch(
                    "app.services.onboard_service._brand_svc"
                ) as brand:
                    brand.return_value.update.return_value = None
                    _complete(channels=[{"platform": "instagram", "handle": ""}])
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
