import asyncio
import unittest
from unittest.mock import AsyncMock

from app.services import claims_guard


class ClaimsGuardTests(unittest.TestCase):
    def test_empty_text_skips_the_model(self) -> None:
        complete = AsyncMock()
        out = asyncio.run(claims_guard.check("  ", "انگشتر نقره", complete=complete))
        self.assertEqual(out, [])
        complete.assert_not_called()

    def test_check_returns_claims_outside_facts(self) -> None:
        complete = AsyncMock(return_value={"claims": ["اصیل", " "]})
        out = asyncio.run(claims_guard.check("این کیف چرمی اصیل است.", "کیف چرمی", complete=complete))
        self.assertEqual(out, ["اصیل"])
        self.assertIn("کیف چرمی", complete.await_args.args[1])

    def test_what_the_seller_said_is_never_an_outside_claim(self) -> None:
        facts = "برای ساعت مچی پست بساز و بگو ضدآب است و ده سال گارانتی دارد"
        complete = AsyncMock(
            return_value={"claims": ["ضدآب است", "ضدآب بودن", "ده سال گارانتی دارد", "ضدآب با ده سال گارانتی", "بادوام", "ارسال رایگان"]}
        )
        out = asyncio.run(claims_guard.check("متن", facts, complete=complete))
        self.assertEqual(out, ["بادوام", "ارسال رایگان"])
        self.assertEqual(
            asyncio.run(claims_guard.check("متن", "ارسال به تهران", complete=AsyncMock(return_value={"claims": ["ارسال رایگان"]}))),
            ["ارسال رایگان"],
        )

    def test_missing_claims_key_deletes_nothing(self) -> None:
        complete = AsyncMock(return_value={"reply": "کپشن"})
        out = asyncio.run(claims_guard.check("انگشتر نقره.", "انگشتر نقره", complete=complete))
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
