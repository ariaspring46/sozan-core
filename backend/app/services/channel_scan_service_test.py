import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import channel_scan_service, shop_service
from app.state_store import tenant_scope


class PageHandleAndOutcomeTests(unittest.TestCase):
    def test_a_named_page_is_found_in_the_chat_but_a_plain_word_is_not(self) -> None:
        for text, handle in (
            ("pinkshop528_sirjan", "pinkshop528_sirjan"),
            ("@pinkshop528_sirjan", "pinkshop528_sirjan"),
            ("https://www.instagram.com/mahsoo__beauty/", "mahsoo__beauty"),
            ("پیج من pinkshop528_sirjan هست", "pinkshop528_sirjan"),
            ("اینستاگرام: shop.sirjan", "shop.sirjan"),
        ):
            self.assertEqual(channel_scan_service.handle_in_text(text), handle, text)
        for text in ("hello", "بساز", "yes build it", "قیمت ۸۵۰ هزار", "انگشتر نقره", ""):
            self.assertEqual(channel_scan_service.handle_in_text(text), "", text)

    def test_a_scan_killed_by_a_restart_does_not_stay_running_forever(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.state_store import write_json

                write_json("scan-status.json", {"status": "running", "handles": ["pinkshop528_sirjan"], "startedAt": time.time() - 60})
                self.assertEqual(channel_scan_service.scan_status()["status"], "running")
                write_json("scan-status.json", {"status": "running", "handles": ["pinkshop528_sirjan"], "startedAt": time.time() - 3 * 3600})
                stale = channel_scan_service.scan_status()
                self.assertEqual(stale["status"], "error")
                self.assertEqual(stale["error"], channel_scan_service.SCAN_STALE_FA)
                self.assertNotIn("در جریان", channel_scan_service.scan_outcome())
                # a row from before startedAt existed is judged by the file's age
                write_json("scan-status.json", {"status": "running", "handles": ["pinkshop528_sirjan"]})
                path = Path(raw) / "tenants" / "09123456789" / "scan-status.json"
                old = time.time() - 5 * 3600
                os.utime(path, (old, old))
                self.assertEqual(channel_scan_service.scan_status()["status"], "error")

    def test_an_empty_scan_is_told_as_it_is_and_never_as_a_source_of_prices(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.state_store import write_json

                self.assertIn("هیچ پیجی اسکن نشده", channel_scan_service.scan_outcome())
                write_json("scan-status.json", {"status": "done", "productCount": 0, "handles": ["mahsoo__beauty"], "rejected": 1})
                write_json("channel-scan.json", {"accounts": [{"platform": "instagram", "handle": "mahsoo__beauty", "fetched": False, "products": []}]})
                outcome = channel_scan_service.scan_outcome()
                self.assertIn("mahsoo__beauty", outcome)
                self.assertIn("نتیجه‌ای نداشت", outcome)
                self.assertIn("نمی‌شود از پیج برداشت", outcome)
                write_json("scan-status.json", {"status": "running", "productCount": 0, "handles": ["pinkshop528_sirjan"]})
                self.assertIn("pinkshop528_sirjan", channel_scan_service.scan_outcome())
                self.assertIn("در جریان", channel_scan_service.scan_outcome())
                write_json("scan-status.json", {"status": "done", "productCount": 0, "handles": ["mahsoo__beauty"], "rejected": 1})
                brief = channel_scan_service.brief_for_shop()
                self.assertIn("نتیجهٔ اسکن:", brief)
                self.assertIn("قول اسکن نده", brief)
                self.assertNotIn("نگو به پیج یا اینستاگرام دسترسی نداری", brief)


class ChannelScanTests(unittest.TestCase):
    def test_scan_sendbox_posts_without_graph(self) -> None:
        page = {
            "title": "shop",
            "description": "کیف",
            "images": ["https://cdn.example/a.jpg"],
            "captions": ["کیف چرم قهوه‌ای دستدوز"],
            "text": "کیف چرم قهوه‌ای دستدوز",
        }
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"), patch(
                "app.services.channel_scan_service._sendbox_page", new=AsyncMock(return_value=page)
            ), patch(
                "app.services.channel_scan_service._boxapi_page",
                new=AsyncMock(side_effect=AssertionError("boxapi")),
            ), patch(
                "app.services.channel_scan_service._instagram_page",
                new=AsyncMock(side_effect=AssertionError("graph")),
            ), patch(
                "app.services.channel_scan_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "about": "فروش کیف",
                        "colors": ["قهوه‌ای"],
                        "products": [{"title": "کیف اداری", "price": 0, "description": "چرم", "category": "کیف"}],
                        "categories": ["کیف"],
                    }
                ),
            ), patch(
                "app.services.channel_scan_service._download", new=AsyncMock(return_value="scan.jpg")
            ), patch("app.services.channel_scan_service.voice_service.learn", new=AsyncMock()):
                result = asyncio.run(
                    channel_scan_service.scan_account(
                        platform="instagram",
                        handle="shop",
                        brand="کیف",
                        work="چرم",
                        sendbox_id="acc-1",
                    )
                )
        self.assertTrue(result["fetched"])
        titles = {row["title"] for row in result["products"]}
        self.assertIn("کیف اداری", titles)
        self.assertEqual(result["categories"], ["کیف"])
        cats = {row.get("category") for row in result["products"]}
        self.assertIn("کیف", cats)

    def test_rebuild_skips_protected_shops(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_service._save_shop({**shop_service._shop(), "slug": "joahr-froshi", "status": "ready"})
                with patch.object(shop_service, "start_build") as build:
                    self.assertIsNone(shop_service.rebuild_from_channel_catalog())
                    build.assert_not_called()

    def test_rebuild_ready_kif_kocholo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_service._save_shop({**shop_service._shop(), "slug": "kif-kocholo", "status": "ready"})
                with patch.object(shop_service, "start_build", return_value={"ok": True}) as build:
                    out = shop_service.rebuild_from_channel_catalog()
        build.assert_not_called()
        self.assertIsNone(out)

    def test_factory_prompt_includes_channel_image(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service
                from app.services.channel_scan_service import _scan_dir

                (_scan_dir() / "scan.jpg").write_bytes(b"jpg")
                storefront_service.add_product(
                    title="کیف کوچک",
                    price=0,
                    stock=1,
                    sku="ig-shop",
                    image="scan.jpg",
                    source="instagram",
                    sourceHandle="shop",
                    description="چرم",
                    category="کیف",
                )
                prompt = shop_service._factory_prompt("بساز")
        self.assertIn("کیف کوچک", prompt)
        self.assertIn("scan.jpg", prompt)
        self.assertIn("دسته: کیف", prompt)
        self.assertIn("تصویر ساختگی نساز", prompt)

    def test_caption_products_sets_category(self) -> None:
        rows = channel_scan_service._caption_products({"captions": ["کیف چرم قهوه‌ای دستدوز"]})
        self.assertEqual(rows[0]["category"], "کیف")
        self.assertEqual(rows[0]["title"], "کیف چرم")
        self.assertIn("قهوه‌ای", rows[0]["colors"])

    def test_shahrekif_captions_extract_specs(self) -> None:
        page = {
            "captions": [
                "این کیف پرطرفدارمون در رنگبندی قهوه ای و کرم موجوده 👜🙂 قیمت =دایرکت #کیف_مجلسی",
                "کیف شیک و زیبا فول پک در دو رنگ پرطرفدار 🥰 ۳.۷۰۰ هزارتومان #کیف_دوشی",
                "صندل زیبای پ.ر.ا.د.ا فول پک و دارای سایز بندی 🥰 3.200هزلرتومان",
            ]
        }
        rows = channel_scan_service._caption_products(page)
        titles = {row["title"] for row in rows}
        self.assertTrue(any("کیف" in title and title != "کیف" for title in titles))
        self.assertNotIn("مانتو", " ".join(titles))
        self.assertNotIn("شلوار", " ".join(titles))
        direct = next(row for row in rows if row.get("priceNote") == "دایرکت")
        self.assertEqual(direct["price"], 0)
        self.assertIn("قهوه‌ای", direct["colors"])
        priced = next(row for row in rows if int(row.get("price") or 0) > 0)
        self.assertGreaterEqual(int(priced["price"]), 3200)

    def test_parse_seller_prices(self) -> None:
        self.assertEqual(channel_scan_service.parse_caption_price("۱/۴۲۸/۰۰۰")[0], 1_428_000)
        self.assertEqual(channel_scan_service.parse_caption_price("۰۰/۱/۴۲۸ تومان")[0], 1_428_000)
        self.assertEqual(channel_scan_service.parse_caption_price("۴.۷۰۰ هزارتومان")[0], 4_700_000)

    def test_enrich_keeps_caption_price_and_llm_price(self) -> None:
        caption_rows = channel_scan_service._caption_products(
            {"captions": ["کیف دوشی چرم قهوه‌ای ۳.۷۰۰ هزارتومان"]}
        )
        llm_rows = [{"title": "کیف دوشی", "price": 0, "description": "چرم", "category": "کیف"}]
        merged = channel_scan_service.enrich_scan_products(caption_rows, llm_rows)
        self.assertEqual(len(merged), 1)
        self.assertGreater(int(merged[0]["price"]), 0)
        caption_rows = [{"title": "کیف زنانه", "price": 0, "description": "کپشن", "category": "کیف", "colors": []}]
        llm_rows = [{"title": "کیف زنانه", "price": 3900, "description": "دو سایز", "category": "کیف"}]
        merged = channel_scan_service.enrich_scan_products(caption_rows, llm_rows)
        self.assertEqual(merged[0]["price"], 3900)

    def test_a_css_caption_is_not_a_product(self) -> None:
        from app.services.channel_scan_service import _product_from_caption

        css = ":root, .__ig-light-mode {--fds-black:#000000;--fds-black-alpha-05:rgba(0, 0, 0, 0.05);}"
        self.assertIsNone(_product_from_caption(css, brand="سوزان"))

    def test_factory_prompt_forbids_invented_clothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service
                from app.services.channel_scan_service import _scan_dir

                (_scan_dir() / "scan.jpg").write_bytes(b"jpg")
                storefront_service.add_product(
                    title="کیف مجلسی",
                    price=3700000,
                    stock=1,
                    sku="ig-shop",
                    image="scan.jpg",
                    source="instagram",
                    sourceHandle="@shahrekif.sirjan",
                    description="قهوه‌ای و کرم",
                    category="کیف",
                )
                prompt = shop_service._factory_prompt("بساز")
        self.assertIn("کیف مجلسی", prompt)
        self.assertIn("کالای ساختگی نساز", prompt)
        self.assertIn("public/products/scan.jpg", prompt)
        self.assertNotIn("fashion", prompt)

    def test_site_type_hint_is_bags_not_fashion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service
                from app.services.channel_scan_service import _scan_dir

                (_scan_dir() / "scan.jpg").write_bytes(b"jpg")
                storefront_service.add_product(
                    title="کیف دوشی",
                    price=850000,
                    stock=1,
                    sku="ig",
                    source="instagram",
                    category="کیف",
                )
                self.assertEqual(channel_scan_service.site_type_hint(), "bags")
                captured: list[list[str]] = []

                def factory(args: list[str]) -> dict:
                    captured.append(args)
                    return {"ok": True, "jobId": "j", "status": "running", "slug": "sahhr-kif"}

                shop_service._save_shop({**shop_service._shop(), "slug": "sahhr-kif", "status": "ready", "port": 12376})
                with (
                    patch.object(shop_service, "_run_factory", side_effect=factory),
                    patch.object(shop_service, "_publish_dns", side_effect=lambda shop: shop),
                    patch.object(shop_service, "_emit_build"),
                    patch("app.services.shop_service.get_settings", return_value={"storeName": "شهر کیف"}),
                    patch("app.services.shop_service.record_site"),
                    patch("app.services.shop_edit_service.fetch_image_png", return_value=b""),
                ):
                    shop_service.start_build(prompt="از نو بساز", rebuild=True)
                self.assertIn("--site-type-hint", captured[0])
                hint = captured[0][captured[0].index("--site-type-hint") + 1]
                self.assertEqual(hint, "bags")
                self.assertNotEqual(hint, "fashion")

    def test_jewelry_tagline_beats_bag_category(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                from app.state_store import write_json
                from app.services import storefront_service

                write_json("shop.json", {"brand": "سوزان", "tagline": "جواهر فروش و سنگ های گران قیمت"})
                storefront_service.add_product(
                    title="کیف دوشی",
                    price=850000,
                    stock=1,
                    sku="ig",
                    source="instagram",
                    category="کیف",
                )
                self.assertEqual(channel_scan_service.site_type_hint(), "jewelry")
                prompt = shop_service._factory_prompt("از نو بساز")
                self.assertIn("شعار فروشگاه: جواهر فروش و سنگ های گران قیمت", prompt)

    def test_site_type_hint_unknown_category_is_general_store(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service

                storefront_service.add_product(
                    title="جلد زیپی",
                    price=0,
                    stock=1,
                    sku="zip",
                    category="جلد زیپی",
                )
                self.assertEqual(channel_scan_service.site_type_hint(), "general-store")

    def test_site_type_hint_saffron_not_bags(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service
                from app.services.channel_scan_service import _scan_dir

                (_scan_dir() / "scan.jpg").write_bytes(b"jpg")
                storefront_service.add_product(
                    title="زعفران پوشال",
                    price=0,
                    stock=1,
                    sku="spice",
                    category="زعفران",
                )
                self.assertEqual(channel_scan_service.site_type_hint(), "saffron-spice")

    def test_scan_images_are_tenant_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                shared = Path(raw) / "scan-images"
                shared.mkdir()
                (shared / "gen-01.png").write_bytes(b"x" * 100)
                with tenant_scope("09120000001"):
                    a = channel_scan_service._scan_dir()
                    (a / "same.png").write_bytes(b"a")
                with tenant_scope("09120000002"):
                    b = channel_scan_service._scan_dir()
                    (b / "same.png").write_bytes(b"b")
                self.assertNotEqual(a, b)
                self.assertEqual((a / "same.png").read_bytes(), b"a")
                self.assertEqual((b / "same.png").read_bytes(), b"b")
                self.assertTrue((Path(raw) / "scan-images" / "_unattributed" / "gen-01.png").is_file())

    def test_direct_price_status(self) -> None:
        rows = channel_scan_service._caption_products(
            {"captions": ["این کیف پرطرفدارمون قیمت =دایرکت"]}
        )
        self.assertEqual(rows[0]["priceStatus"], "direct")

    def _scan_accounts(
        self,
        products: list[dict],
        *,
        fetched: bool = True,
        llm_error: str = "",
        previous: dict | None = None,
        import_catalog: bool = True,
    ):
        account = {
            "platform": "instagram",
            "handle": "optic_day",
            "fetched": fetched,
            "products": products,
            "about": "",
            "colors": [],
            "categories": [],
            "llmError": llm_error,
        }
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09111234567"),
                patch.object(channel_scan_service, "get_scan", return_value=dict(previous or {})),
                patch.object(channel_scan_service, "scan_account", new=AsyncMock(return_value=account)),
                patch.object(channel_scan_service, "emit_later"),
                patch("app.services.channel_scan_service.voice_service.merge_summary"),
                patch("app.services.channel_scan_service.storefront_service.remove_scanned_handle") as remove,
                patch("app.services.channel_scan_service.storefront_service.upsert_scanned_product") as upsert,
            ):
                out = asyncio.run(
                    channel_scan_service.scan_accounts(
                        [{"platform": "instagram", "handle": "optic_day"}],
                        import_catalog=import_catalog,
                    )
                )
            return out, upsert, remove

    def test_one_candidate_without_image_is_imported(self) -> None:
        out, upsert, remove = self._scan_accounts(
            [{"title": "جلد زیپی", "price": 0, "image": "", "stableKey": "k1", "sourceHandle": "optic_day"}]
        )
        upsert.assert_called_once()
        remove.assert_called_once_with("optic_day")
        self.assertFalse(out.get("needsReview"))
        self.assertEqual(out["quality"]["imported"], 1)
        self.assertEqual(out["productCount"], 1)

    def test_unnamed_rows_stay_out_of_the_catalog(self) -> None:
        out, upsert, remove = self._scan_accounts(
            [
                {"title": "کالای 1", "description": "", "stableKey": "a", "sourceHandle": "optic_day"},
                {"title": "کالای ۲", "stableKey": "b", "sourceHandle": "optic_day"},
            ]
        )
        upsert.assert_not_called()
        remove.assert_not_called()
        self.assertEqual(out["quality"]["imported"], 0)
        self.assertEqual(out["productCount"], 0)

    def test_a_named_product_is_imported_beside_unnamed_rows(self) -> None:
        _out, upsert, remove = self._scan_accounts(
            [
                {"title": "کالای 1", "stableKey": "a", "sourceHandle": "optic_day"},
                {"title": "انگشتر فیروزه", "price": 500000, "stableKey": "b", "sourceHandle": "optic_day"},
            ]
        )
        upsert.assert_called_once()
        self.assertEqual(upsert.call_args.kwargs["title"], "انگشتر فیروزه")
        remove.assert_called_once_with("optic_day")

    def test_a_review_keeps_the_catalog_even_when_the_page_has_a_named_product(self) -> None:
        out, upsert, remove = self._scan_accounts(
            [{"title": "انگشتر فیروزه", "stableKey": "b", "sourceHandle": "optic_day"}],
            import_catalog=False,
        )
        upsert.assert_not_called()
        remove.assert_not_called()
        self.assertEqual(out["quality"]["imported"], 0)
        self.assertEqual(out["accounts"][0]["products"][0]["title"], "انگشتر فیروزه")

    def test_zero_candidates_skips_upsert_and_needs_review(self) -> None:
        with patch("app.services.channel_scan_service.storefront_service.count_scanned_handle", return_value=1) as count:
            out, upsert, remove = self._scan_accounts([], fetched=True)
        upsert.assert_not_called()
        remove.assert_not_called()
        count.assert_called_once_with(["optic_day"])
        self.assertTrue(out.get("needsReview"))
        self.assertEqual(out["quality"]["imported"], 0)
        self.assertEqual(out["quality"]["kept"], 1)

    def test_large_low_image_scan_imports_with_soft_review(self) -> None:
        products = [{"title": f"کالا {i}", "price": 0, "image": "", "stableKey": f"k{i}"} for i in range(6)]
        out, upsert, remove = self._scan_accounts(products)
        self.assertEqual(upsert.call_count, 6)
        remove.assert_called_once()
        self.assertTrue(out.get("needsReview"))
        self.assertEqual(out["quality"]["imported"], 6)

    def test_model_outage_keeps_previous_scan_and_reports_error(self) -> None:
        previous = {
            "accounts": [{"platform": "instagram", "handle": "optic_day", "products": [{"title": "جلد زیپی"}]}],
            "productCount": 1,
            "quality": {"imported": 1},
        }
        out, upsert, remove = self._scan_accounts([], fetched=True, llm_error="llm_unreachable", previous=previous)
        upsert.assert_not_called()
        remove.assert_not_called()
        self.assertEqual(out["error"], channel_scan_service.SCAN_MODEL_ERROR)
        self.assertFalse(out.get("needsReview"))
        self.assertEqual(out["productCount"], 1)
        self.assertEqual(out["quality"]["imported"], 1)

    def test_model_outage_with_caption_candidates_still_imports(self) -> None:
        out, upsert, _ = self._scan_accounts(
            [{"title": "جلد زیپی", "price": 0, "image": "", "stableKey": "k1"}], llm_error="llm_unreachable"
        )
        upsert.assert_called_once()
        self.assertNotIn("error", out)
        self.assertEqual(out["quality"]["imported"], 1)

    def test_start_scan_model_outage_sets_error_status_and_keeps_counts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09111234567"),
                patch.object(channel_scan_service, "emit_later"),
                patch.object(
                    channel_scan_service,
                    "scan_accounts",
                    new=AsyncMock(return_value={"error": channel_scan_service.SCAN_MODEL_ERROR, "productCount": 1}),
                ),
                patch("app.services.shop_service.rebuild_from_channel_catalog") as rebuild,
            ):
                channel_scan_service._set_scan_status(
                    status="done", product_count=1, handles=["optic_day"], extra={"imported": 1, "noImage": 1}
                )

                async def run() -> dict:
                    channel_scan_service.start_scan([{"platform": "instagram", "handle": "optic_day"}])
                    await asyncio.sleep(0.05)
                    return channel_scan_service.scan_status()

                status = asyncio.run(run())
            rebuild.assert_not_called()
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["errorClass"], channel_scan_service.SCAN_MODEL_ERROR)
        self.assertIn("دوباره اسکن", status["error"])
        self.assertEqual(status["imported"], 1)
        self.assertEqual(status["productCount"], 1)
        self.assertFalse(status["needsReview"])


if __name__ == "__main__":
    unittest.main()
