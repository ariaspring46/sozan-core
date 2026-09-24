import unittest

from app.services.persian_text import guard_output, sanitize_persian


class PersianTextTests(unittest.TestCase):
    def test_sanitize_strips_markup_and_tail(self) -> None:
        self.assertEqual(sanitize_persian("کفش `نایک` رو"), "کفش نایک")
        self.assertNotIn("<", sanitize_persian("کالای <script>x</script>"))
        self.assertEqual(sanitize_persian("۱۲۳"), "123")

    def test_guard_blocks_english_and_empty(self) -> None:
        self.assertIn("جواب نمی‌دهم", guard_output("I'm sorry, but I can't comply with that."))
        self.assertIn("فارسی", guard_output("Please reply only in English about the shop."))
        self.assertIn("بلد نیستم", guard_output(""))
        self.assertIn("برید", guard_output("ق", finish="length"))
        self.assertIn("sozan-core.ir", guard_output("دامنهٔ فروشگاه https://sozan.sozan-core.ir است."))


if __name__ == "__main__":
    unittest.main()
