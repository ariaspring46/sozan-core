import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services.sales_policy_service import fixed_reply
from app.state_store import tenant_scope, write_json


class SalesPolicyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
