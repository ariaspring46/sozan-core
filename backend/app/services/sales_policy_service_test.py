import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import sales_policy_service
from app.state_store import tenant_scope


class SalesPolicyTests(unittest.TestCase):
    def test_blank_fields_are_omitted_and_numbers_stay_integers(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09120000991"):
            saved = sales_policy_service.save_policy(
                {
                    "shippingMethod": "پست پیشتاز",
                    "shippingCost": 60000,
                    "shippingDays": "۳ تا ۵ روز کاری",
                    "shippingCities": "همهٔ شهرها",
                    "returnNote": "اگر استفاده نشده باشد",
                    "cod": "",
                    "minOrder": "",
                }
            )
            again = sales_policy_service.public_policy()
        self.assertEqual(saved["shippingCost"], 60000)
        self.assertNotIn("cod", again)
        self.assertNotIn("minOrder", again)
        self.assertEqual(again["shippingCities"], "همهٔ شهرها")

    def test_negative_number_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09120000991"):
            with self.assertRaises(ValueError):
                sales_policy_service.save_policy({"shippingCost": -1})
