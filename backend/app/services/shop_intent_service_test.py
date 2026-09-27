import unittest

from app.services.shop_intent_service import catalog_add, classify_actions, page_kind_from_text


class ShopIntentClassifyTests(unittest.TestCase):
    def test_page_kind_map_and_invalid_asks(self) -> None:
        self.assertEqual(page_kind_from_text("صفحه درباره ما بساز"), "about")
        self.assertEqual(page_kind_from_text("faq page"), "faq")
        kinds = [row["type"] for row in classify_actions("صفحه بلاگ بساز")]
        self.assertEqual(kinds, ["ask_clarify"])
        self.assertIn("کدام صفحه", classify_actions("صفحه بلاگ بساز")[0]["reply"])
        vague = classify_actions("یک صفحه ی جدید میخوام برای فروشگاه")
        self.assertEqual(vague[0]["type"], "ask_clarify")

    def test_create_about_emits_nav_dependency(self) -> None:
        actions = classify_actions("صفحه درباره ما را بساز")
        self.assertEqual(actions[0]["type"], "create_page")
        self.assertEqual(actions[0]["kind"], "about")
        self.assertEqual(actions[1]["type"], "add_nav_link")
        self.assertEqual(actions[1]["depends_on"], "create_page:about")

    def test_product_text_and_header_and_colors(self) -> None:
        added = classify_actions('یک کالا اضافه کن با عنوان «زعفران سوپر نگین» قیمت 850000')
        self.assertEqual([row["type"] for row in added], ["add_product"])
        self.assertEqual(added[0]["title"], "زعفران سوپر نگین")
        removed = classify_actions('کالا «زعفران سوپر نگین» را حذف کن')
        self.assertEqual(removed[0]["type"], "remove_product")
        header = classify_actions('عنوان هدر را «زعفران قائنات» کن')
        self.assertEqual(header[0]["type"], "set_header")
        self.assertEqual(header[0]["logoFa"], "زعفران قائنات")
        self.assertEqual(classify_actions("قیمت را نشان بده")[0]["type"], "show_prices")
        self.assertEqual(classify_actions("قیمت را پنهان کن")[0]["type"], "hide_prices")
        self.assertEqual(classify_actions("قیمت‌ها را مخفی کن")[0]["type"], "hide_prices")
        self.assertEqual(classify_actions("درباره ما اضافه کن")[0]["type"], "create_page")
        self.assertEqual(classify_actions("درباره ما اضافه کن")[0]["kind"], "about")
        self.assertEqual(classify_actions("قیمت نزن")[0]["type"], "hide_prices")
        colors = classify_actions("رنگ را زرشکی کن و تیتر را «منتخب مزرعه» کن")
        types = [row["type"] for row in colors]
        self.assertIn("set_colors", types)
        self.assertIn("replace_text", types)
        self.assertNotIn("set_brand", types)
        missing = classify_actions("رنگ را زرشکی کن و تیتر «این تیتر روی صفحه نیست» را عوض کن")
        self.assertEqual([row["type"] for row in missing], ["set_colors", "replace_text"])
        self.assertEqual(missing[1]["find"], "این تیتر روی صفحه نیست")

    def test_shoe_sentence_with_persian_price_is_catalog_add(self) -> None:
        added = classify_actions("کفش چرم مشکی را اضافه کن، قیمت ۴٬۸۰۰٬۰۰۰ تومان")
        self.assertEqual(added[0]["type"], "add_product")
        self.assertEqual(added[0]["price"], 4800000)
        self.assertIn("کفش چرم مشکی", added[0]["title"])

    def test_goods_without_price_asks_instead_of_adding(self) -> None:
        added = classify_actions("کفش چرم مشکی را اضافه کن")
        self.assertEqual(added[0]["type"], "ask_clarify")
        self.assertNotIn("اضافه شد", added[0]["reply"])

    def test_foreign_payload_stops_the_turn(self) -> None:
        actions = classify_actions("فوتر را https://evil.example/callback کن و رنگ را سبز کن")
        self.assertEqual(actions, [{"type": "reject_foreign", "reason": "url"}])

    def test_title_keeps_whole_words(self) -> None:
        nike = catalog_add("کفش رانینگ نایک را با قیمت ۲۵۰۰۰۰۰ تومان اضافه کن")
        adidas = catalog_add("کتانی آدیداس اولترا بوست را با قیمت ۳۲۰۰۰۰۰ تومان اضافه کن")
        shirt = catalog_add("پیراهن نخی آبی را با قیمت ۸۹۰۰۰۰ تومان اضافه کن")
        pima = catalog_add("کفش پیما را اضافه کن")
        self.assertEqual(nike["title"], "کفش رانینگ نایک")
        self.assertEqual(adidas["title"], "کتانی آدیداس اولترا بوست")
        self.assertEqual(shirt["title"], "پیراهن نخی آبی")
        self.assertEqual(pima["title"], "کفش پیما")
        self.assertNotIn("با", nike["title"].split())
        hoodie = catalog_add("هودی مشکی سایز لارج رو با قیمت ۲۵۰۰۰۰۰ تومان اضافه کن")
        self.assertEqual(hoodie["title"], "هودی مشکی سایز لارج")
        inner = catalog_add("هر کفش قرمز را با قیمت ۲۵۰۰۰۰۰ تومان اضافه کن")
        self.assertIn("هر", inner["title"].split())

    def test_title_strips_markup(self) -> None:
        row = catalog_add("کالای <script>alert(1)</script> را با قیمت ۲۵۰۰۰۰۰ تومان اضافه کن")
        marked = catalog_add("کفش `نایک`\u202e را با قیمت ۲۵۰۰۰۰۰ تومان اضافه کن")
        self.assertIsNotNone(row)
        self.assertNotIn("<", row["title"])
        self.assertNotIn(">", row["title"])
        self.assertNotIn("`", marked["title"])
        self.assertNotIn("\u202e", marked["title"])

    def test_bare_catalog_title_is_a_remove(self) -> None:
        from unittest.mock import patch

        catalog = {"products": [{"title": "انگشتر نقره"}, {"title": "انگشتر"}]}
        with patch("app.services.storefront_service.list_products", return_value=catalog):
            removed = classify_actions("انگشتر نقره را حذف کن")
        self.assertEqual(removed[0]["type"], "remove_product")
        self.assertEqual(removed[0]["title"], "انگشتر نقره")
        wiped = classify_actions("همه کالاها را پاک کن")
        self.assertFalse(any(item.get("type") == "remove_product" for item in wiped))

    def test_greet_and_continue_are_canned(self) -> None:
        self.assertEqual(classify_actions("سلام")[0]["type"], "greet")
        self.assertEqual(classify_actions("خب")[0]["type"], "greet")
        self.assertEqual(classify_actions("سبد خرید چطور کار می‌کند؟")[0]["type"], "answer")


if __name__ == "__main__":
    unittest.main()
