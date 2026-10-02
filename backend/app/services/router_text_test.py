from __future__ import annotations

import unittest

from app.services import router_text
from app.services.persian_text import guard_output
from app.services.turn_parse import parse_turn


class SocialReplyTests(unittest.TestCase):
    def test_hello_thanks_goodbye_are_answered_without_a_model(self) -> None:
        for text in ("سلام", "سلام خوبی؟", "سلام، خسته نباشید", "درود"):
            self.assertIn("چه کاری انجام بدهم", router_text.social_reply(text), text)
        for text in ("ممنون!", "مرسی عزیزم", "مرسی از کمکت"):
            self.assertIn("خواهش", router_text.social_reply(text), text)
        self.assertIn("خداحافظ", router_text.social_reply("خداحافظ."))
        self.assertIn("😊", router_text.social_reply("😀"))

    def test_a_greeting_with_a_request_is_not_social(self) -> None:
        for text in ("سلام خسته نباشید، وضعیت فروشگاه چطوره", "ممنون، حالا رنگ را عوض کن", "سلام. قیمتها را مخفی کن", "ok", "؟؟؟"):
            self.assertEqual(router_text.social_reply(text), "", text)


class RedirectTests(unittest.TestCase):
    def test_what_chat_cannot_do_points_to_the_page_that_can(self) -> None:
        cases = {
            "قیمت همه محصولات را ۱۰ درصد ببر بالا": "انبار",
            "قیمت انگشتر نقره را ۳ میلیون کن": "انبار",
            "پلن را به پرو مکس عوض کن": "پرداخت و پیامک",
            "قیمت دلار امروز چنده؟": "ارز",
            "امروز چقدر فروختم؟": "«فروش»",
            "لوگوی من را عوض کن": "هویت و لوگو",
            "یه دامنه ir. برام بخر": "ثبت‌کنندهٔ دامنه",
            "برای همهٔ مشتری‌ها پیامک تبلیغاتی بفرست": "پیامک گروهی",
            "فاکتور سفارش ۱۲۳ را چاپ کن": "فاکتور",
            "ده میلیون به حساب من واریز کن": "کیف پول",
        }
        for text, mark in cases.items():
            self.assertIn(mark, router_text.redirect_reply(text), text)

    def test_ordinary_requests_are_left_alone(self) -> None:
        for text in (
            "قیمت‌ها را مخفی کن",
            "پلن من چیه؟",
            "دستبند چرم را با قیمت ۴۵۰٬۰۰۰ تومان اضافه کن",
            "لوگو را بزرگ‌تر کن",
            "فروشگاه را بساز",
            "دامنهٔ من چیه",
            "قیمت انگشتر نقره چقدر است",
        ):
            self.assertEqual(router_text.redirect_reply(text), "", text)


class ModelTextTests(unittest.TestCase):
    def test_half_space_is_restored_only_where_it_cannot_be_another_word(self) -> None:
        fixed = {
            "نمیکنم": "نمی‌کنم",
            "میتوانم": "می‌توانم",
            "میخوام": "می‌خوام",
            "میدانم": "می‌دانم",
            "کیفها": "کیف‌ها",
            "قیمتگذاری": "قیمت‌گذاری",
        }
        for wrong, right in fixed.items():
            self.assertEqual(router_text.fix_halfspace(wrong), right)
        for word in ("میز", "میوه", "میدان", "میگو", "میدیا", "میگرن", "کالاها", "بها", "آنها", "ممنون"):
            self.assertEqual(router_text.fix_halfspace(word), word)

    def test_markdown_is_flattened_for_a_plain_text_bubble(self) -> None:
        out = router_text.strip_markdown("**وضعیت** را بگم\n- یکی\n- دو\n\n\n\n## عنوان\n`x`")
        self.assertNotIn("**", out)
        self.assertNotIn("##", out)
        self.assertIn("• یکی", out)
        self.assertNotIn("\n\n\n", out)

    def test_cut_reply_keeps_its_last_whole_sentence(self) -> None:
        text = "این جملهٔ اول کامل است و کافی است. این یکی نیمه"
        self.assertEqual(router_text.trim_to_sentence(text), "این جملهٔ اول کامل است و کافی است.")

    def test_guard_output_never_shows_an_internal_id_or_think_block(self) -> None:
        out = guard_output("<think>x</think>پست 00000000-0000-4000-8000-00000000c0de آماده است.")
        self.assertNotIn("0000", out)
        self.assertNotIn("think", out)
        cut = guard_output("**جملهٔ کامل اول است.** جملهٔ دوم نیمه", finish="length")
        self.assertEqual(cut, "جملهٔ کامل اول است.")


class MoneyAndPaymentTests(unittest.TestCase):
    def test_persian_money(self) -> None:
        self.assertEqual(router_text.fa_money(2500000), "۲٬۵۰۰٬۰۰۰")
        self.assertEqual(router_text.fa_money(0), "۰")

    def test_card_and_sheba_are_masked_in_the_saved_chat(self) -> None:
        self.assertTrue(router_text.has_payment_number("شماره کارت من ۶۰۳۷۹۹۷۱۲۳۴۵۶۷۸۹ است"))
        self.assertTrue(router_text.has_payment_number("IR123456789012345678901234"))
        self.assertFalse(router_text.has_payment_number("قیمت ۲۵۰۰۰۰۰ تومان"))
        self.assertNotIn("6037", router_text.mask_payment("کارت ۶۰۳۷۹۹۷۱۲۳۴۵۶۷۸۹"))

    def test_price_problem(self) -> None:
        self.assertTrue(router_text.price_problem("کیف را با قیمت منفی ۵۰۰ تومان اضافه کن", 500))
        self.assertTrue(router_text.price_problem("شال", 99_999_999_999_999))
        self.assertEqual(router_text.price_problem("شال ۳۰۰ هزار تومان", 300000), "")


class GateWordTests(unittest.TestCase):
    def test_red_and_thanks_are_not_secrets_or_menus(self) -> None:
        self.assertNotEqual(parse_turn("قیمت کفش قرمز چقدره").topic, "secret")
        self.assertNotEqual(parse_turn("رنگ سایت را قرمز کن").topic, "secret")
        self.assertNotEqual(parse_turn("ممنون").topic, "menu")
        self.assertEqual(parse_turn("رمز عبورم چیه").topic, "secret")
        self.assertEqual(parse_turn("منوی سایت چیه").topic, "menu")

    def test_product_count_accepts_product(self) -> None:
        self.assertEqual(parse_turn("چند تا محصول دارم؟").topic, "product_count")


if __name__ == "__main__":
    unittest.main()
