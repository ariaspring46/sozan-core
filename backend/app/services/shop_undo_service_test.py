import asyncio
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config import settings
from app.services import shop_image_service, shop_service, shop_undo_service, storefront_service
from app.services.shop_edit_service import HERO_REL, apply_live_edit
from app.services.shop_edit_service_test import _flow_root, _patch_runtime
from app.state_store import tenant_scope


def _png(color: tuple[int, int, int], size: tuple[int, int] = (64, 40)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def _edit(shop: dict, root: Path, text: str, target: str = "") -> dict:
    with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root), patch(
        "app.services.shop_edit_service.publish_shop_runtime"
    ):
        return asyncio.run(apply_live_edit(shop, text, "/", target))


class UndoStackTests(unittest.TestCase):
    def test_each_undo_takes_back_one_edit_and_the_pending_counter(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                first = _edit(shop, root, "بنویس خانه", "زعفران")
                second = _edit(shop, root, "رنگ را سبز کن")
                self.assertTrue(first["patched"] and second["patched"])
                self.assertEqual(shop_undo_service.depth(root), 2)
                # the text edit needs a build; the colour edit went live at once and needs none
                self.assertEqual(int(shop_service._shop()["pendingBuild"]), 1)

                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ):
                    one = shop_undo_service.undo_last(shop_service._shop())
                brand = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
                self.assertTrue(one["patched"])
                self.assertEqual(one["undoDepth"], 1)
                self.assertNotIn("#15803D", brand)
                self.assertIn("خانه", brand)
                self.assertEqual(int(shop_service._shop()["pendingBuild"]), 1)

                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ):
                    two = shop_undo_service.undo_last(shop_service._shop())
                    three = shop_undo_service.undo_last(shop_service._shop())
                brand = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
                self.assertTrue(two["patched"])
                self.assertEqual(two["undoDepth"], 0)
                self.assertNotIn("خانه", brand)
                self.assertEqual(int(shop_service._shop()["pendingBuild"]), 0)
                self.assertFalse(three["patched"])
                self.assertEqual(three["reply"], shop_undo_service.NOTHING_TO_UNDO)

    def test_a_finished_build_locks_everything_before_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                _edit(shop, root, "رنگ را سبز کن")
                self.assertEqual(shop_undo_service.depth(root), 1)
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root):
                    shop_undo_service.clear_for(shop)
                    self.assertEqual(shop_service._undo_depth(shop), 0)
                self.assertEqual(shop_undo_service.depth(root), 0)

    def test_stack_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(shop_undo_service.UNDO_CAP + 3):
                snap = root / f".sozan-turn-{index}"
                snap.mkdir()
                (snap / "a.txt").write_text(str(index), encoding="utf-8")
                shop_undo_service.push(root, snap, {"pending": index})
            self.assertEqual(shop_undo_service.depth(root), shop_undo_service.UNDO_CAP)
            number, meta = shop_undo_service.peek(root)
            self.assertEqual(meta["pending"], shop_undo_service.UNDO_CAP + 2)

    def test_undo_edit_waits_for_a_running_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_service._save_shop({**shop_service._shop(), "slug": "x", "status": "running"})
                with patch.object(shop_service, "_refresh_job", side_effect=lambda row: row), patch.object(
                    shop_undo_service, "undo_last"
                ) as undo, patch.object(shop_service, "snapshot", return_value={"shop": {}}):
                    out = shop_service.undo_edit()
                undo.assert_not_called()
                self.assertFalse(out["patched"])


class ImageSwapTests(unittest.TestCase):
    def test_which_picture_was_held(self) -> None:
        products = [{"id": "p1", "title": "انگشتر", "image": "a1.jpg", "images": ["a1.jpg", "a2.jpg"]}]
        classify = shop_image_service.classify
        self.assertEqual(classify("https://x.sozan-core.ir/images/hero.png?t=1", products)[:2], ("hero", "hero.png"))
        self.assertEqual(classify("/brand-logo.png", products)[0], "logo")
        self.assertEqual(classify("/_next/image?url=%2Fproducts%2Fa2.jpg&w=640&q=75", products)[0], "product")
        self.assertEqual(classify("/products/zzz.jpg", products)[0], "")
        self.assertEqual(classify("/images/placeholder.svg", products)[0], "")
        self.assertEqual(classify("/products/../../etc/passwd", products)[0], "")
        self.assertEqual(classify("", products)[0], "")

    def test_a_product_card_without_a_photo_gets_one_and_undo_takes_it_away(self) -> None:
        products = [{"id": "p1", "title": "کیف چرمی", "image": "", "images": []}]
        self.assertEqual(shop_image_service.classify("/images/placeholder.svg", products, "/products/p1")[0], "product")
        self.assertEqual(shop_image_service.classify("", products, "/products/p1")[0], "product")
        self.assertEqual(shop_image_service.classify("", products, "/products/other")[0], "")
        self.assertEqual(shop_image_service.classify("", products, "/cart")[0], "")
        self.assertEqual(shop_image_service.classify("/images/hero.png", products, "/products/p1")[0], "hero")  # an explicit picture wins
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                storefront_service.add_product(title="کیف چرمی", price=900000, stock=2, sku="B-1")
                row = storefront_service.list_products()["products"][0]
                self.assertFalse(row["image"])
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ), patch("app.services.shop_service.shop_is_live", return_value=True):
                    out = shop_image_service.replace_image(shop, _png((90, 40, 10)), "image/png", "n.png", "", f"/products/{row['id']}")
                    self.assertEqual(out["kind"], "product")
                    self.assertIn("گذاشته شد", out["reply"])
                    self.assertTrue(storefront_service.list_products()["products"][0]["image"])
                    undone = shop_undo_service.undo_last(shop_service._shop())
                self.assertTrue(undone["patched"])
                self.assertFalse(storefront_service.list_products()["products"][0]["image"])

    def test_hero_swap_is_one_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            hero = root / HERO_REL
            hero.parent.mkdir(parents=True)
            hero.write_bytes(_png((200, 10, 10)))
            before = hero.read_bytes()
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_service.publish_shop_hero"
                ):
                    out = shop_image_service.replace_image(shop, _png((10, 10, 200), (3000, 1200)), "image/png", "x.png", "/images/hero.png")
                    self.assertEqual(out["kind"], "hero")
                    self.assertNotEqual(hero.read_bytes(), before)
                    with Image.open(hero) as img:
                        self.assertLessEqual(max(img.size), shop_image_service.HERO_SIDE)
                    self.assertEqual(shop_undo_service.depth(root), 1)
                    self.assertGreaterEqual(int(shop_service._shop()["pendingBuild"]), 1)
                    undone = shop_undo_service.undo_last(shop_service._shop())
                self.assertTrue(undone["patched"])
                self.assertEqual(hero.read_bytes(), before)
                self.assertEqual(int(shop_service._shop()["pendingBuild"]), 0)

    def test_bad_uploads_and_unknown_pictures_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root):
                    with self.assertRaises(ValueError):
                        shop_image_service.replace_image(shop, _png((1, 2, 3)), "image/png", "x.png", "/images/unknown.png")
                    with self.assertRaises(ValueError):
                        shop_image_service.replace_image(shop, b"not an image", "image/png", "x.png", "/images/hero.png")
                    with self.assertRaises(ValueError):
                        shop_image_service.replace_image(shop, b"", "image/png", "x.png", "/images/hero.png")
                    with self.assertRaises(ValueError):
                        shop_image_service.replace_image(shop, b"%PDF-1.4", "application/pdf", "x.pdf", "/images/hero.png")
                    self.assertEqual(shop_undo_service.depth(root), 0)

    def test_product_photo_swap_goes_through_inventory_and_undo_puts_it_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                from app.services import channel_scan_service, product_image_service

                scan = channel_scan_service.scan_dir()
                scan.mkdir(parents=True, exist_ok=True)
                (scan / "old.jpg").write_bytes(_png((9, 9, 9)))
                storefront_service.add_product(title="انگشتر نقره", price=1200000, stock=3, sku="R-1", image="old.jpg")
                row = storefront_service.list_products()["products"][0]
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ), patch("app.services.shop_service.shop_is_live", return_value=True):
                    out = shop_image_service.replace_image(
                        shop, _png((90, 40, 10)), "image/png", "new.png", "/_next/image?url=%2Fproducts%2Fold.jpg&w=640"
                    )
                    self.assertEqual(out["kind"], "product")
                    now = storefront_service.list_products()["products"][0]
                    self.assertNotEqual(now["image"], "old.jpg")
                    self.assertTrue((scan / now["image"]).is_file())
                    self.assertTrue((root / "public" / "products" / now["image"]).is_file())
                    self.assertEqual(shop_undo_service.depth(root), 1)
                    undone = shop_undo_service.undo_last(shop_service._shop())
                self.assertTrue(undone["patched"])
                back = storefront_service.list_products()["products"][0]
                self.assertEqual(back["image"], "old.jpg")
                self.assertEqual(row["id"], back["id"])


if __name__ == "__main__":
    unittest.main()
