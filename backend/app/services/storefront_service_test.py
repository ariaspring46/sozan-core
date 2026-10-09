import tempfile
import time
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import storefront_service
from app.services.channel_scan_service import _scan_dir
from app.state_store import tenant_scope, write_json


class StorefrontServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name

    def tearDown(self) -> None:
        self.dir.cleanup()

    def _photo(self, name: str = "a.jpg") -> str:
        path = _scan_dir() / name
        path.write_bytes(b"jpg")
        return name

    def test_update_all_fields_and_sku(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            photo = self._photo()
            created = storefront_service.add_product(title="کیف", price=100, stock=1, sku="old")
            pid = created["product"]["id"]
            out = storefront_service.update_product(
                pid,
                {
                    "title": "کیف دوشی",
                    "price": 250000,
                    "stock": 4,
                    "sku": "bag-1",
                    "description": "چرم طبیعی",
                    "category": "کیف",
                    "subcategory": "دوشی",
                    "colors": ["قهوه‌ای", "کرم"],
                    "sizes": "متوسط",
                    "discount": 10,
                    "priceNote": "",
                    "image": photo,
                    "images": [photo],
                },
            )
        product = out["product"]
        self.assertEqual(product["sku"], "bag-1")
        self.assertEqual(product["category"], "کیف")
        self.assertEqual(product["subcategory"], "دوشی")
        self.assertEqual(product["discount"], 10)
        self.assertEqual(product["finalPrice"], 225000)
        self.assertEqual(product["image"], photo)
        self.assertEqual(product["images"][0], photo)

    def test_discount_bounds(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            created = storefront_service.add_product(title="عسل", price=10, stock=1, sku="")
            with self.assertRaises(ValueError):
                storefront_service.update_product(created["product"]["id"], {"discount": 91})
            with self.assertRaises(ValueError):
                storefront_service.add_product(title="چای", price=1, stock=1, sku="", discount=-1)

    def test_price_note_enum(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            with self.assertRaises(ValueError):
                storefront_service.add_product(title="کیف", price=1, stock=1, sku="", priceNote="واتساپ")
            row = storefront_service.add_product(title="کیف", price=1, stock=1, sku="", priceNote="دایرکت")
        self.assertEqual(row["product"]["priceLabel"], "دایرکت")

    def test_category_trim(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            row = storefront_service.add_product(title="کیف", price=1, stock=1, sku="", category="  کیف مجلسی  " + "x" * 80)
        self.assertEqual(len(row["product"]["category"]), 40)
        self.assertTrue(row["product"]["category"].startswith("کیف"))

    def test_image_must_exist(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            with self.assertRaises(ValueError):
                storefront_service.add_product(title="کیف", price=1, stock=1, sku="", image="missing.jpg")

    def test_images_reorder_keeps_main_first(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            a = self._photo("a.jpg")
            b = self._photo("b.jpg")
            created = storefront_service.add_product(title="کیف", price=1, stock=1, sku="", images=[a, b])
            pid = created["product"]["id"]
            self.assertEqual(created["product"]["image"], a)
            out = storefront_service.set_main_image(pid, b)
        self.assertEqual(out["product"]["image"], b)
        self.assertEqual(out["product"]["images"][:2], [b, a])

    def test_categories_merges_scan(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            storefront_service.add_product(title="کیف دوشی", price=1, stock=1, sku="", category="کیف", subcategory="دوشی")
            storefront_service.add_product(title="کیف مجلسی", price=1, stock=1, sku="", category="کیف", subcategory="مجلسی")
            write_json("channel-scan.json", {"categories": ["کیف", "کفش"]})
            cats = storefront_service.categories()
        titles = [row["title"] for row in cats]
        self.assertEqual(titles[0], "کیف")
        self.assertEqual(cats[0]["count"], 2)
        self.assertIn("دوشی", cats[0]["subcategories"])
        self.assertIn("کفش", titles)
        shoe = next(row for row in cats if row["title"] == "کفش")
        self.assertEqual(shoe["count"], 0)

    def test_update_product_logs_when_pending_build_fails(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            created = storefront_service.add_product(title="کیف", price=100, stock=1, sku="bag")
            pid = created["product"]["id"]
            with patch(
                "app.services.shop_service.bump_pending_build",
                side_effect=RuntimeError("lock"),
            ):
                with self.assertLogs("sozan.storefront", level="ERROR") as captured:
                    storefront_service.update_product(pid, {"price": 250})
        self.assertTrue(any("bump pending build failed" in line for line in captured.output))

    def test_manual_sale_defaults_source(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            out = storefront_service.add_sale(title="دستبند", amount=450000, customer="مشتری", channel="فروشگاه")
            row = out["sale"]
        self.assertEqual(row["source"], "manual")
        self.assertGreater(int(row["at"]), 0)

    def test_placeholder_catalog_rows(self) -> None:
        self.assertTrue(storefront_service.is_placeholder_catalog("سلام! 👋 این یک پست آزمایشی"))
        self.assertTrue(storefront_service.is_placeholder_catalog("Winter is coming…"))
        self.assertTrue(storefront_service.is_placeholder_catalog("آویز فیروزه بازبینی ۱"))
        self.assertTrue(storefront_service.is_placeholder_catalog("کالای تست بازبینی زنده"))
        self.assertFalse(storefront_service.is_placeholder_catalog("آویز فیروزه"))
        self.assertFalse(storefront_service.is_placeholder_catalog("عکس انگشتر فیروزه"))
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root):
            with self.assertRaises(ValueError):
                storefront_service.add_product(
                    title="آویز فیروزه بازبینی ۱",
                    price=0,
                    stock=0,
                    sku="",
                    description="کالای تست بازبینی زنده",
                )
            self.assertEqual(storefront_service.drop_placeholder_products(), [])


    def test_add_product_returns_while_catalog_sync_is_slow(self) -> None:
        def slow(*_args, **_kwargs) -> int:
            time.sleep(1.2)
            return 0

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.root), patch(
            "app.services.shop_memory_service.backfill_catalog", slow
        ):
            started = time.monotonic()
            storefront_service.add_product(title="انگشتر", price=850000, stock=1, sku="r1")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
