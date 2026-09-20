import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import catalog_sync_service, shop_service, storefront_service
from app.services.channel_scan_service import _scan_dir
from app.state_store import tenant_scope, write_json


class CatalogSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.build = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.dir.cleanup()
        self.build.cleanup()

    def _live_shop(self, slug: str = "demo-shop") -> None:
        write_json(
            "shop.json",
            {
                **shop_service.DEFAULT_SHOP,
                "slug": slug,
                "status": "ready",
                "url": "https://demo-shop.sozan-core.ir",
                "publicHost": "demo-shop.sozan-core.ir",
            },
        )

    def _overlay(self, root: Path) -> None:
        (root / "lib").mkdir(exist_ok=True)
        (root / "lib" / "catalog.ts").write_text("export function readCatalog() { return [] }\n", encoding="utf-8")

    def test_writes_catalog_paths_and_reuses_slug(self) -> None:
        root = Path(self.build.name)
        (root / "public").mkdir()
        self._overlay(root)
        (root / "public" / "catalog.json").write_text(
            json.dumps(
                {
                    "products": [
                        {
                            "title": "کهنه",
                            "category": "bags",
                            "categoryFa": "کیف",
                            "subcategory": "shoulder",
                            "subcategoryFa": "دوشی",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=root
        ), patch("app.services.shop_edit_service.publish_shop_runtime") as publish, patch(
            "app.services.catalog_sync_service.emit_later"
        ):
            self._live_shop()
            photo = _scan_dir() / "p.jpg"
            photo.write_bytes(b"jpg")
            storefront_service.add_product(
                title="کیف دوشی",
                price=1000,
                stock=1,
                sku="",
                category="کیف",
                subcategory="دوشی",
                discount=20,
                image="p.jpg",
            )
            out = catalog_sync_service.sync_live(changed_images=["p.jpg"])
        self.assertTrue(out["live"])
        catalog = json.loads((root / "public" / "catalog.json").read_text(encoding="utf-8"))
        row = catalog["products"][0]
        self.assertEqual(row["category"], "bags")
        self.assertEqual(row["categoryFa"], "کیف")
        self.assertEqual(row["subcategoryFa"], "دوشی")
        self.assertEqual(row["discount"], 20)
        self.assertEqual(row["image"], "/products/p.jpg")
        self.assertIn("/products/p.jpg", row["images"])
        self.assertTrue((root / "public" / "products" / "p.jpg").is_file())
        publish.assert_called()
        rels = publish.call_args[0][2]
        self.assertIn("public/catalog.json", rels)
        self.assertIn("public/products/p.jpg", rels)

    def test_new_category_bumps_pending(self) -> None:
        root = Path(self.build.name)
        (root / "public").mkdir()
        self._overlay(root)
        (root / "public" / "catalog.json").write_text(
            json.dumps({"products": [{"title": "قدیمی", "category": "bags", "categoryFa": "کیف"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=root
        ), patch("app.services.shop_edit_service.publish_shop_runtime"), patch("app.services.catalog_sync_service.emit_later"):
            self._live_shop()
            storefront_service.add_product(title="عسل کنار", price=2, stock=1, sku="", category="عسل")
            out = catalog_sync_service.sync_live()
            shop = shop_service._shop()
        self.assertTrue(out["pendingMenu"])
        self.assertIn("بیلد", out["hint"])
        self.assertEqual(int(shop.get("pendingBuild") or 0), 1)

    def test_skips_protected_and_idle(self) -> None:
        root = Path(self.build.name)
        (root / "public").mkdir()
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=root
        ), patch("app.services.shop_edit_service.publish_shop_runtime") as publish, patch(
            "app.services.catalog_sync_service.emit_later"
        ):
            write_json("shop.json", {**shop_service.DEFAULT_SHOP, "slug": "joahr-froshi", "status": "ready"})
            storefront_service.add_product(title="قدیمی", price=1, stock=1, sku="")
            protected = catalog_sync_service.sync_live()
            write_json("shop.json", {**shop_service.DEFAULT_SHOP, "slug": "demo-shop", "status": "idle"})
            idle = catalog_sync_service.sync_live()
        self.assertFalse(protected["live"])
        self.assertEqual(protected.get("reason"), "protected")
        self.assertFalse(idle["live"])
        publish.assert_not_called()

    def test_copies_only_changed_images(self) -> None:
        root = Path(self.build.name)
        (root / "public" / "products").mkdir(parents=True)
        self._overlay(root)
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=root
        ), patch("app.services.shop_edit_service.publish_shop_runtime"), patch("app.services.catalog_sync_service.emit_later"):
            self._live_shop()
            scan = _scan_dir()
            (scan / "old.jpg").write_bytes(b"old")
            (scan / "new.jpg").write_bytes(b"new")
            storefront_service.add_product(title="یکی", price=1, stock=1, sku="", images=["old.jpg", "new.jpg"])
            catalog_sync_service.sync_live(changed_images=["new.jpg"])
        self.assertTrue((root / "public" / "products" / "new.jpg").is_file())
        self.assertFalse((root / "public" / "products" / "old.jpg").is_file())

    def test_missing_runtime_overlay_is_not_live(self) -> None:
        root = Path(self.build.name)
        (root / "public").mkdir()
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=root
        ), patch("app.services.shop_edit_service.publish_shop_runtime") as publish, patch(
            "app.services.catalog_sync_service.emit_later"
        ):
            self._live_shop()
            storefront_service.add_product(title="یکی", price=1, stock=1, sku="")
            out = catalog_sync_service.sync_live()
            shop = shop_service._shop()
        self.assertFalse(out["live"])
        self.assertEqual(out.get("reason"), "no-runtime")
        self.assertIn("بیلد", out.get("hint") or "")
        self.assertGreaterEqual(int(shop.get("pendingBuild") or 0), 1)
        publish.assert_not_called()

    def test_missing_product_image_is_not_hero(self) -> None:
        root = Path(self.build.name)
        (root / "public").mkdir()
        self._overlay(root)
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.shop_edit_service.build_dir_for", return_value=root
        ), patch("app.services.shop_edit_service.publish_shop_runtime"), patch("app.services.catalog_sync_service.emit_later"):
            self._live_shop()
            storefront_service.add_product(title="بی‌عکس", price=1000, stock=1, sku="")
            out = catalog_sync_service.sync_live()
        catalog = json.loads((root / "public" / "catalog.json").read_text(encoding="utf-8"))
        row = catalog["products"][0]
        self.assertTrue(out["live"])
        self.assertNotIn("hero.png", str(row.get("image") or ""))
        self.assertEqual(row.get("image") or "", "")


if __name__ == "__main__":
    unittest.main()
