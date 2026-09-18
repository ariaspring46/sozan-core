import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import channel_scan_service, shop_service
from app.state_store import tenant_scope


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
                    price=0,
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
                self.assertIn("--catalog", captured[0])
                catalog_path = Path(captured[0][captured[0].index("--catalog") + 1])
                payload = json.loads(catalog_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["items"][0]["title"], "کیف دوشی")
                self.assertEqual(payload["items"][0]["price"], 0)
                self.assertTrue(payload.get("lockItems"))
                self.assertNotIn("مانتو", json.dumps(payload, ensure_ascii=False))

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


if __name__ == "__main__":
    unittest.main()
