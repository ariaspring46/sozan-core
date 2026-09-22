import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from app.config import settings
from app.services import shop_service, storefront_service, shop_workspace_service
from app.services.shop_edit_service import (
    apply_live_edit,
    build_dir_for,
    has_runtime_chrome,
    looks_like_foreign_payload,
    named_color_updates,
    patch_brand_file,
    patch_page_file,
    patch_selected_text,
    restore_edit_files,
    snapshot_edit_files,
    spoken_reply,
    sync_products_ts,
    wants_hero_image,
    wants_revert,
    write_intent,
    _catalog_product_image,
    _finish_edit,
)
from app.state_store import tenant_scope


class ShopEditPatchTests(unittest.TestCase):
    def test_selected_heading_patches_brand_and_page(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lib").mkdir()
            (root / "app").mkdir()
            (root / "lib" / "brand.ts").write_text(
                "export const brand = { name: 'جواهر فروشی', ctaLabelFa: 'مشاهده محصولات' }\n",
                encoding="utf-8",
            )
            (root / "app" / "page.tsx").write_text(
                "export default function Home() { return <h2>منتخب کارگاه</h2> }\n",
                encoding="utf-8",
            )
            self.assertTrue(patch_selected_text(root, "منتخب کارگاه", "منتخب آتلیه"))
            self.assertIn("منتخب آتلیه", (root / "app" / "page.tsx").read_text(encoding="utf-8"))
            self.assertTrue(patch_selected_text(root, "مشاهده محصولات", "ورود به ویترین"))
            self.assertIn("ورود به ویترین", (root / "lib" / "brand.ts").read_text(encoding="utf-8"))
            self.assertTrue(patch_page_file(root, "/", [{"find": "منتخب آتلیه", "replace": "منتخب گالری"}]))
            self.assertIn("منتخب گالری", (root / "app" / "page.tsx").read_text(encoding="utf-8"))
            self.assertTrue(patch_selected_text(root, "منتخب گالری", ""))
            page = (root / "app" / "page.tsx").read_text(encoding="utf-8")
            self.assertNotIn("منتخب گالری", page)
            self.assertNotRegex(page, r"<h2[^>]*>\s*</h2>")

    def test_sync_products_ts_survives_nested_image_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lib").mkdir()
            (root / "lib" / "products.ts").write_text(
                "export interface Product { images?: string[] }\n"
                "export const products: Product[] = [\n"
                "  { id: '1', title: 'کهنه', images: ['/a.png'] },\n"
                "  { id: '2', title: 'عسل کنار', images: ['/b.png'] },\n"
                "]\n"
                ",\n  },\n  { id: '3', title: 'باقیمانده کارخانه', images: ['/c.png'] },\n]\n"
                "export function getProductById(id: string) { return products[0] }\n",
                encoding="utf-8",
            )
            self.assertTrue(
                sync_products_ts(
                    root,
                    [
                        {"id": "1", "title": "عسل گون", "price": 1, "category": "عسل", "image": "/x.png"},
                        {"id": "2", "title": "عسل کنار", "price": 2, "category": "عسل", "image": "/y.png"},
                    ],
                )
            )
            text = (root / "lib" / "products.ts").read_text(encoding="utf-8")
            self.assertIn("عسل گون", text)
            self.assertIn("عسل کنار", text)
            self.assertNotIn("کهنه", text)
            self.assertNotIn("باقیمانده کارخانه", text)
            self.assertIn("getProductById", text)
            self.assertEqual(text.count("export const products"), 1)
            self.assertIsNone(re.search(r"\]\s*,\s*\{", text))
            catalog = json.loads((root / "public" / "catalog.json").read_text(encoding="utf-8"))
            titles = {row["title"] for row in catalog["products"]}
            self.assertEqual(titles, {"عسل گون", "عسل کنار"})

    def test_revert_restores_previous_brand_color(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lib").mkdir()
            brand = root / "lib" / "brand.ts"
            brand.write_text("export const brand = { primary: '#1E3A5F', accent: '#C9A227' }\n", encoding="utf-8")
            snapshot_edit_files(root)
            self.assertTrue(patch_brand_file(brand, {"primary": "#B42318", "accent": "#B42318"}))
            self.assertIn("#B42318", brand.read_text(encoding="utf-8"))
            self.assertTrue(restore_edit_files(root))
            self.assertIn("#1E3A5F", brand.read_text(encoding="utf-8"))
            self.assertNotIn("#B42318", brand.read_text(encoding="utf-8"))

    def test_named_red_and_write_intent(self) -> None:
        self.assertEqual(named_color_updates("میخواهم رنگ آن قرمز باشد")["primary"], "#B42318")
        self.assertEqual(named_color_updates("اکسنت را طلایی کن"), {"accent": "#C9A227"})
        self.assertEqual(named_color_updates("پس‌زمینه را کرم کن"), {"background": "#F3E6C8"})
        self.assertEqual(named_color_updates("رنگ را زرشکی کن")["primary"], "#7A1F2B")
        self.assertEqual(write_intent("بنویس خانه"), "خانه")
        self.assertTrue(wants_revert("اشتباه ویرایش کردی به حالت قبل برگردون"))
        self.assertTrue(wants_hero_image("یک تصویر بساز برای بک گراند"))
        self.assertTrue(wants_hero_image("میخوام یه عکس برای این انگشتر طراحی کنی"))
        self.assertFalse(wants_hero_image("میخواهم رنگ آن قرمز باشد"))
        self.assertTrue(looks_like_foreign_payload("https://api.sozan-core.ir/channels/instagram/callback"))
        self.assertTrue(looks_like_foreign_payload("deadbeefdeadbeefdeadbeefdeadbeef"))
        self.assertFalse(looks_like_foreign_payload("میخواهم رنگ آن قرمز باشد"))

    def test_catalog_image_skips_hero_placeholder(self) -> None:
        self.assertEqual(_catalog_product_image("کیف", "/images/hero.png", {}), "")
        self.assertEqual(_catalog_product_image("کیف", "", {"کیف": "/images/hero.png"}), "")
        self.assertEqual(_catalog_product_image("کیف", "/products/a.jpg", {}), "/products/a.jpg")
        self.assertEqual(
            spoken_reply("بنویس خانه", "خانه", True, "write", "خانه"),
            "متن به «خانه» تغییر کرد.",
        )
        self.assertIn("پیدا نشد", spoken_reply("بنویس خانه", "خانه", False, "write", "خانه"))
        self.assertIn(
            "پیدا نشد",
            spoken_reply("رنگ آبی", "برند و رنگ‌ها با موفقیت به‌روزرسانی شدند", False, "edit"),
        )

    def test_finish_edit_keeps_ready_and_skips_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop(
                    {**shop_service._shop(), "slug": "demo", "status": "ready", "jobId": "j1"}
                )
                with patch("app.services.shop_edit_service.spawn_rebuild") as spawn:
                    out = _finish_edit(shop, "رنگ عوض شد", True, {"colors": {"primary": "#B42318"}})
                spawn.assert_not_called()
                stored = shop_service._shop()
        self.assertTrue(out["patched"])
        self.assertEqual(out["pendingBuild"], 1)
        self.assertEqual(out["preview"]["colors"]["primary"], "#B42318")
        self.assertEqual(stored["status"], "ready")
        self.assertEqual(stored["pendingBuild"], 1)


def _flow_root(base: Path) -> Path:
    root = base / "site"
    (root / "lib").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "lib" / "brand.ts").write_text(
        "export const designTokens = { colors: { primary: '#111111', accent: '#222222' } }\n"
        "export const brand = { name: 'زعفران', primary: '#C45C26', accent: '#C9A227', "
        "ctaLabelFa: 'خرید', cartCtaFa: 'افزودن به دفتر سفارش' }\n",
        encoding="utf-8",
    )
    (root / "app" / "page.tsx").write_text(
        'export default function Home() { return <h2 className="x">منتخب کارگاه</h2> }\n',
        encoding="utf-8",
    )
    (root / "app" / "layout.tsx").write_text("import './globals.css'\nexport default function L({ children }) { return children }\n", encoding="utf-8")
    (root / "app" / "products").mkdir()
    (root / "app" / "products" / "page.tsx").write_text(
        "export default function Products() { return <h1>دفتر کالا</h1> }\n",
        encoding="utf-8",
    )
    (root / "lib" / "catalog.ts").write_text("export function readCatalog() { return [] }\n", encoding="utf-8")
    return root


def _patch_runtime(root: Path):
    def fake(shop=None, page_path=""):
        shop = shop or {}
        css_path = root / "public" / "brand-vars.css"
        flags_path = root / "public" / "storefront-flags.json"
        catalog_path = root / "public" / "catalog.json"
        css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
        flags = flags_path.read_text(encoding="utf-8") if flags_path.is_file() else ""
        catalog = catalog_path.read_text(encoding="utf-8") if catalog_path.is_file() else '{"products":[]}'
        hide = bool(shop.get("hidePrices"))
        logo = ""
        links = []
        if flags:
            try:
                data = json.loads(flags)
                hide = bool(data.get("hidePrices"))
                logo = str(data.get("logoFa") or "")
                if isinstance(data.get("links"), list):
                    links = data["links"]
            except json.JSONDecodeError:
                pass
        if not logo:
            nav_path = root / "lib" / "nav.ts"
            if nav_path.is_file():
                from app.services.shop_edit_verify import nav_logo

                logo = nav_logo(nav_path.read_text(encoding="utf-8"))
        titles = []
        try:
            rows = json.loads(catalog).get("products") or []
            titles = [str(row.get("title") or "") for row in rows if isinstance(row, dict)]
        except json.JSONDecodeError:
            titles = []
        nav_html = "".join(
            f'<a data-nav-href="{item.get("href")}">{item.get("label")}</a>'
            for item in links
            if isinstance(item, dict)
        )
        attr = "1" if hide else "0"
        html = (
            f'<html data-hide-prices="{attr}">'
            f'<span data-logo-fa="{logo}">{logo}</span>'
            f"{nav_html}"
            '<span data-price="final">10</span></html>'
        )
        products_html = "<div>" + "".join(f"<article>{title}</article>" for title in titles) + "</div>"
        page_html = ""
        kind = str(page_path or "").strip("/")
        page_json = root / "public" / "pages" / f"{kind}.json"
        if kind and page_json.is_file():
            try:
                data = json.loads(page_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict) and data.get("enabled"):
                page_html = f"<h1>{data.get('title') or ''}</h1><p>{data.get('body') or ''}</p>"
        return {
            "html": html,
            "css": css,
            "flags": flags,
            "catalog": catalog,
            "products_html": products_html,
            "page_html": page_html,
        }

    return patch("app.services.shop_edit_verify.fetch_shop_runtime", side_effect=fake)


class ShopEditFlowTests(unittest.TestCase):
    def test_color_patches_brand_export_not_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ) as pub:
                    out = asyncio.run(apply_live_edit(shop, "رنگ را سبز کن", "/", ""))
            brand = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
            css = (root / "app" / "brand-vars.css").read_text(encoding="utf-8")
            public_css = (root / "public" / "brand-vars.css").read_text(encoding="utf-8")
            self.assertTrue(out["patched"])
            self.assertIn("primary: '#15803D'", brand)
            self.assertIn("primary: '#111111'", brand)
            self.assertIn("--brand-primary: #15803D", css)
            self.assertIn("--brand-primary: #15803D", public_css)
            self.assertIn("رنگ", out["reply"])
            published = [rel for call in pub.call_args_list for rel in call.args[2]]
            self.assertIn("public/brand-vars.css", published)

    def test_color_live_miss_restores_disk(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_verify.fetch_shop_runtime",
                    return_value={"html": "", "css": "", "flags": ""},
                ), patch("app.services.shop_edit_service.publish_shop_runtime"):
                    out = asyncio.run(apply_live_edit(shop, "رنگ را سبز کن", "/", ""))
            brand = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
            self.assertFalse(out["patched"])
            self.assertIn("عوض نشد", out["reply"])
            self.assertIn("#C45C26", brand)
            self.assertNotIn("#15803D", brand)

    def test_color_without_overlay_stays_in_frame(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            (root / "lib" / "catalog.ts").unlink()
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ) as pub:
                    out = asyncio.run(apply_live_edit(shop, "رنگ را سبز کن", "/", ""))
            brand = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
            self.assertTrue(out["patched"])
            self.assertTrue(out.get("needsRebuild"))
            self.assertIn("کادر", out["reply"])
            self.assertIn("#15803D", brand)
            pub.assert_not_called()

    def test_add_and_remove_product_without_photo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root):
                    added = asyncio.run(
                        apply_live_edit(shop, 'یک کالا اضافه کن با عنوان «زعفران سوپر نگین» قیمت 850000', "/", "")
                    )
                    titles = {row["title"] for row in storefront_service.list_products()["products"]}
                    catalog = json.loads((root / "public" / "catalog.json").read_text(encoding="utf-8"))
                    self.assertTrue(added["patched"])
                    self.assertFalse(added.get("needsRebuild"))
                    self.assertEqual(int(shop_service._shop().get("pendingBuild") or 0), 0)
                    self.assertNotIn("بیلد", added["reply"])
                    self.assertIn("زعفران سوپر نگین", titles)
                    self.assertIn("زعفران سوپر نگین", json.dumps(catalog, ensure_ascii=False))
                    removed = asyncio.run(apply_live_edit(shop, 'کالا «زعفران سوپر نگین» را حذف کن', "/", ""))
                    titles = {row["title"] for row in storefront_service.list_products()["products"]}
                    catalog = json.loads((root / "public" / "catalog.json").read_text(encoding="utf-8"))
                    self.assertTrue(removed["patched"])
                    self.assertNotIn("زعفران سوپر نگین", titles)
                    self.assertNotIn("زعفران سوپر نگین", json.dumps(catalog, ensure_ascii=False))

    def test_create_about_and_invalid_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root):
                    created = asyncio.run(apply_live_edit(shop, "صفحه درباره ما را بساز", "/", ""))
                    missing = asyncio.run(apply_live_edit(shop, "صفحه بلاگ بساز", "/", ""))
            about = json.loads((root / "public" / "pages" / "about.json").read_text(encoding="utf-8"))
            flags = json.loads((root / "public" / "storefront-flags.json").read_text(encoding="utf-8"))
            self.assertTrue(created["patched"])
            self.assertTrue(created.get("needsRebuild"))
            self.assertIn("کادر", created["reply"])
            self.assertTrue(about.get("enabled"))
            self.assertIn("/about", json.dumps(flags, ensure_ascii=False))
            self.assertIn("باز است", created["reply"])
            self.assertFalse(missing["patched"])
            self.assertIn("کدام صفحه", missing["reply"])
            self.assertFalse((root / "app" / "blog" / "page.tsx").exists())
            self.assertEqual(created["preview"].get("viewPath"), "/about")
            self.assertNotIn("/blog", created["preview"].get("viewPath") or "")

    def test_header_mixed_fail_foreign_and_show_prices(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop(
                    {**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1", "hidePrices": True}
                )
                pending_before = int(shop.get("pendingBuild") or 0)
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ):
                    header = asyncio.run(apply_live_edit(shop, 'عنوان هدر را «زعفران قائنات» کن', "/", ""))
                    mixed = asyncio.run(
                        apply_live_edit(
                            shop,
                            'رنگ را زرشکی کن و تیتر را «محصول ویژه» کن',
                            "/",
                            "تیتر غایب",
                        )
                    )
                    foreign = asyncio.run(
                        apply_live_edit(shop, "فوتر را https://evil.example/callback کن", "/", "")
                    )
                    shown = asyncio.run(apply_live_edit(shop, "قیمت را نشان بده", "/", ""))
                traces = (shop_workspace_service.workspace_dir() / "trace.jsonl").read_text(encoding="utf-8")
                stored = shop_service._shop()
            self.assertTrue(header["patched"])
            self.assertIn("زعفران قائنات", (root / "lib" / "nav.ts").read_text(encoding="utf-8"))
            self.assertTrue(mixed.get("rolledBack"))
            self.assertFalse(mixed["patched"])
            self.assertNotIn("#7A1F2B", (root / "lib" / "brand.ts").read_text(encoding="utf-8"))
            self.assertFalse(foreign["patched"])
            self.assertEqual(foreign["reply"], "این پیام ویرایش فروشگاه نیست.")
            self.assertGreaterEqual(int(stored["pendingBuild"] or 0), pending_before)
            self.assertTrue(shown["patched"])
            self.assertFalse(stored["hidePrices"])
            self.assertIn('"type": "reject_foreign"', traces)
            self.assertIn('"ok": true', traces)

    def test_mixed_fail_republishes_restored_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            public_css = root / "public" / "brand-vars.css"
            public_css.parent.mkdir(parents=True, exist_ok=True)
            public_css.write_text(":root { --brand-primary: #C45C26; }\n", encoding="utf-8")
            container = Path(raw) / "container"
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop(
                    {**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"}
                )

                def fake_publish(_shop, _root, rels):
                    for rel in rels:
                        src = root / rel
                        if not src.is_file():
                            continue
                        dest = container / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(src.read_bytes())

                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime",
                    side_effect=fake_publish,
                ):
                    out = asyncio.run(
                        apply_live_edit(
                            shop,
                            "رنگ را زرشکی کن و تیتر را «محصول ویژه» کن",
                            "/",
                            "تیتر غایب",
                        )
                    )
            live = (container / "public" / "brand-vars.css").read_text(encoding="utf-8")
            disk = public_css.read_text(encoding="utf-8")
            self.assertTrue(out.get("rolledBack"))
            self.assertFalse(out["patched"])
            self.assertIn("#C45C26", disk)
            self.assertNotIn("#7A1F2B", disk)
            self.assertIn("#C45C26", live)
            self.assertNotIn("#7A1F2B", live)

    def test_revert_undoes_last_success_not_whole_turn(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _flow_root(Path(raw))
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop({**shop_service._shop(), "slug": "zafran-test", "status": "ready", "jobId": "j1"})
                with patch("app.services.shop_edit_service.build_dir_for", return_value=root), _patch_runtime(root), patch(
                    "app.services.shop_edit_service.publish_shop_runtime"
                ):
                    asyncio.run(apply_live_edit(shop, 'بنویس خانه', "/", "زعفران"))
                    asyncio.run(apply_live_edit(shop, "رنگ را سبز کن", "/", ""))
                    out = asyncio.run(apply_live_edit(shop, "به حالت قبل برگرد", "/", ""))
            brand = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
            self.assertTrue(out["patched"])
            self.assertIn("#C45C26", brand)
            self.assertNotIn("#15803D", brand)
            self.assertIn("خانه", brand)

    def test_brand_file_count_does_not_hit_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "brand.ts"
            path.write_text(
                "export const designTokens = { colors: { primary: '#111111' } }\n"
                "export const brand = { primary: '#C45C26' }\n",
                encoding="utf-8",
            )
            self.assertTrue(patch_brand_file(path, {"primary": "#15803D"}))
            text = path.read_text(encoding="utf-8")
            self.assertIn("primary: '#111111'", text)
            self.assertIn("primary: '#15803D'", text)

    def test_runtime_chrome_needs_layout_and_header_markers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app").mkdir()
            (root / "components" / "layout").mkdir(parents=True)
            (root / "lib").mkdir()
            (root / "lib" / "catalog.ts").write_text("export function readCatalog() { return [] }\n", encoding="utf-8")
            (root / "app" / "layout.tsx").write_text("export default function Root() { return <html></html> }\n", encoding="utf-8")
            (root / "components" / "layout" / "Header.tsx").write_text("export default function Header() { return null }\n", encoding="utf-8")
            self.assertFalse(has_runtime_chrome(root))
            (root / "app" / "layout.tsx").write_text(
                'export default function Root() { return <html data-hide-prices={flags.hidePrices ? "1" : "0"}></html> }\n',
                encoding="utf-8",
            )
            (root / "components" / "layout" / "Header.tsx").write_text(
                'export default function Header() { return <a data-nav-href="/about">درباره</a> }\n',
                encoding="utf-8",
            )
            self.assertTrue(has_runtime_chrome(root))

    def test_empty_shop_is_not_the_process_folder(self) -> None:
        self.assertIsNone(build_dir_for({"slug": "", "jobId": ""}))


if __name__ == "__main__":
    unittest.main()
