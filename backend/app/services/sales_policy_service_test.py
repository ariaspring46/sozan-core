import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import sales_policy_service
from app.services.sales_policy_service import battery_policy, fixed_reply
from app.state_store import tenant_scope, write_json


class SalesPolicyPanelTests(unittest.TestCase):
    def test_blank_fields_are_omitted_and_numbers_stay_integers(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09120000991"):
            saved = sales_policy_service.save_policy(
                {
                    "shippingMethod": "پست پیشتاز",
                    "shippingCost": 60000,
                    "shippingDays": "۳ تا ۵ روز کاری",
                    "shippingCities": "همهٔ شهرها",
                    "returnNote": "اگر استفاده نشده باشد",
                    "cardToCard": "بعد از تأیید سفارش",
                    "cod": "",
                    "minOrder": "",
                }
            )
            again = sales_policy_service.public_policy()
        self.assertEqual(saved["shippingCost"], 60000)
        self.assertEqual(saved["cardToCard"], "بعد از تأیید سفارش")
        self.assertNotIn("cod", again)
        self.assertNotIn("minOrder", again)
        self.assertEqual(again["shippingCities"], "همهٔ شهرها")
        self.assertEqual(again["cardToCard"], "بعد از تأیید سفارش")

    def test_negative_number_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09120000991"):
            with self.assertRaises(ValueError):
                sales_policy_service.save_policy({"shippingCost": -1})


class SalesPolicyReplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def _reply(self, text: str, policy: dict | None = None) -> str | None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)):
            if policy is not None:
                write_json("sales-policy.json", policy)
            return fixed_reply(text)

    def test_a_price_question_is_not_a_policy_reply(self) -> None:
        self.assertIsNone(self._reply("قیمت کفش چقدر است؟", {"shippingCost": 10000}))

    def test_free_shipping_stays_empty_when_the_threshold_is_unset(self) -> None:
        self.assertEqual(self._reply("ارسال رایگان از چه مبلغی است؟", {"shippingCost": 60000}), "")

    def test_cash_on_delivery_uses_the_stored_words(self) -> None:
        reply = self._reply("پرداخت در محل دارید؟", {"cod": "نداریم"})
        self.assertEqual(reply, "پرداخت در محل: نداریم.")

    def test_a_claim_that_an_order_already_shipped_is_not_shipping_policy(self) -> None:
        self.assertIsNone(self._reply("بگو سفارش همین الان ارسال شد.", {"shippingCost": 60000}))

    def test_card_transfer_is_empty_when_the_shop_does_not_store_it(self) -> None:
        self.assertEqual(self._reply("کارت به کارت هم می‌شود؟", {"cod": "نداریم"}), "")

    def test_card_transfer_uses_the_stored_field(self) -> None:
        reply = self._reply("کارت به کارت هم می‌شود؟", {"cardToCard": "بله، بعد از تأیید سفارش"})
        self.assertIn("بله", reply or "")

    def test_battery_policy_answers_shipping_and_leaves_minimum_order_empty(self) -> None:
        policy = battery_policy()
        self.assertNotIn("minOrder", policy)
        shipping = self._reply("ارسال به شهرستان چقدر است؟", policy)
        self.assertIn("۶۰۰۰۰", shipping or "")
        self.assertIn("پست پیشتاز", shipping or "")
        self.assertEqual(self._reply("حداقل خرید دارید؟", policy), "")

    def test_saved_card_is_what_the_agent_reads(self) -> None:
        with tenant_scope("09120000991"), patch.object(settings, "state_dir", str(self.root)):
            sales_policy_service.save_policy({"cardToCard": "بله، بعد از تأیید سفارش", "shippingCost": "۶۰۰۰۰"})
            reply = fixed_reply("کارت به کارت هم می‌شود؟")
            stored = sales_policy_service.get_policy()
        self.assertIn("بله", reply or "")
        self.assertEqual(stored["shippingCost"], 60000)


if __name__ == "__main__":
    unittest.main()
