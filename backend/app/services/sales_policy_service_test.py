import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services.sales_policy_service import battery_policy, fixed_reply, parse
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


if __name__ == "__main__":
    unittest.main()


class PolicyParseTests(unittest.TestCase):
    def test_the_plan_example_sentence_parses_shipping(self) -> None:
        out = parse("ارسال با پست به همه شهرها، ۳ تا ۵ روز، ۶۰ هزار تومان")
        self.assertEqual(
            out["patch"],
            {
                "shippingMethod": "پست",
                "shippingCities": "همهٔ شهرها",
                "shippingDays": "۳ تا ۵ روز",
                "shippingCost": 60000,
            },
        )
        self.assertEqual(out["card"]["shippingCost"]["value"], 60000)
        self.assertEqual(out["card"]["shippingCost"]["state"], "parsed")
        self.assertEqual(out["card"]["returnDays"]["state"], "missing")

    def test_every_core_field_is_parsed(self) -> None:
        patch = parse("پست پیشتاز ۶۵ هزار تومان، ۲ تا ۴ روز کاری، همهٔ شهرها")["patch"]
        self.assertEqual(patch["shippingMethod"], "پست پیشتاز")
        self.assertEqual(patch["shippingCost"], 65000)
        self.assertEqual(patch["shippingDays"], "۲ تا ۴ روز")

        self.assertEqual(parse("ارسال رایگان بالای ۲ میلیون")["patch"]["freeShippingFrom"], 2000000)
        self.assertEqual(parse("مرجوعی ۷ روزه، هزینهٔ برگشت با مشتری")["patch"]["returnDays"], 7)
        self.assertEqual(parse("هزینهٔ برگشت با فروشنده است")["patch"]["returnPayer"], "فروشنده")
        self.assertEqual(parse("از ۱۰ صبح تا ۶ عصر باز هستیم")["patch"]["hours"], "۱۰ تا ۱۸")
        self.assertEqual(parse("ساعت کار ۱۰ تا ۱۸")["patch"]["hours"], "۱۰ تا ۱۸")
        self.assertEqual(parse("حداقل خرید ۵۰۰ هزار تومان")["patch"]["minOrder"], 500000)
        self.assertEqual(parse("پرداخت در محل داریم")["patch"]["cod"], "داریم")
        self.assertEqual(parse("پرداخت در محل نداریم")["patch"]["cod"], "نداریم")
        self.assertEqual(parse("فاکتور فروش می‌دهیم")["patch"]["invoice"], "بله، فاکتور فروش می‌دهیم")
        self.assertEqual(parse("ارسال مجانی است")["patch"]["shippingCost"], 0)

    def test_card_transfer_details_are_structured(self) -> None:
        patch = parse(
            "کارت به کارت ۶۰37-9911-2233-4455 به نام علی رضایی، شبا IR120340000000001234567890"
        )["patch"]
        self.assertEqual(patch["cardNumber"], "6037991122334455")
        self.assertEqual(patch["sheba"], "IR120340000000001234567890")
        self.assertEqual(patch["accountHolder"], "علی رضایی")

    def test_nothing_is_guessed_for_an_unrelated_sentence(self) -> None:
        out = parse("سلام، امروز هوا خوب است")
        self.assertEqual(out["patch"], {})
        self.assertEqual(out["card"]["shippingCost"]["state"], "missing")
        self.assertEqual(parse("")["patch"], {})

    def test_small_unitless_numbers_never_become_amounts(self) -> None:
        out = parse("ارسال ۳ تا ۵ روز")
        self.assertNotIn("shippingCost", out["patch"])
        self.assertEqual(out["patch"]["shippingDays"], "۳ تا ۵ روز")

    def test_card_rows_cover_the_known_field_order(self) -> None:
        out = parse("ارسال با پیک است")
        self.assertIn("shippingMethod", out["card"])
        self.assertIn("accountHolder", out["card"])
        self.assertEqual(
            list(out["card"].keys()),
            list(
                (
                "shippingMethod",
                "shippingCost",
                "shippingDays",
                "shippingCities",
                "freeShippingFrom",
                "returnDays",
                "returnPayer",
                "hours",
                "minOrder",
                "invoice",
                "cod",
                "cardNumber",
                "sheba",
                "accountHolder",
                )
            ),
        )
