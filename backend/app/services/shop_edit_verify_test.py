import json
import json
import tempfile
import unittest
from pathlib import Path

from app.services.shop_edit_verify import verify_action


class ShopEditVerifyTests(unittest.TestCase):
    def test_color_ok_requires_brand_export_and_css_not_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lib").mkdir()
            (root / "app").mkdir()
            (root / "lib" / "brand.ts").write_text(
                "export const designTokens = { colors: { primary: '#15803D', accent: '#15803D' } }\n"
                "export const brand = { primary: '#C45C26', accent: '#C9A227' }\n",
                encoding="utf-8",
            )
            (root / "app" / "brand-vars.css").write_text(
                ":root { --brand-primary: #C45C26; --brand-accent: #C9A227; }\n",
                encoding="utf-8",
            )
            action = {"type": "set_colors", "colors": {"primary": "#15803D", "accent": "#15803D"}}
            failed = verify_action(action=action, root=root)
            self.assertFalse(failed["ok"])
            (root / "lib" / "brand.ts").write_text(
                "export const designTokens = { colors: { primary: '#111111', accent: '#222222' } }\n"
                "export const brand = { primary: '#15803D', accent: '#15803D' }\n",
                encoding="utf-8",
            )
            (root / "app" / "brand-vars.css").write_text(
                ":root { --brand-primary: #15803D; --brand-accent: #15803D; }\n",
                encoding="utf-8",
            )
            live = {
                "html": "",
                "css": ":root { --brand-primary: #15803D; --brand-accent: #15803D; }",
                "flags": "",
            }
            passed = verify_action(action=action, root=root, runtime=live)
            self.assertTrue(passed["ok"])
            missed = verify_action(
                action=action,
                root=root,
                runtime={"html": "", "css": ":root { --brand-primary: #C45C26; }", "flags": ""},
            )
            self.assertFalse(missed["ok"])
            tokens = (root / "lib" / "brand.ts").read_text(encoding="utf-8")
            self.assertIn("primary: '#111111'", tokens)

    def test_hide_prices_and_header_need_live_html(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lib").mkdir()
            (root / "lib" / "nav.ts").write_text(
                "export const nav = { logoFa: 'عسل زاگرس', links: [] }\n",
                encoding="utf-8",
            )
            hide = verify_action(
                action={"type": "hide_prices"},
                root=root,
                shop={"hidePrices": True},
                runtime={"html": "<html></html>", "css": "", "flags": '{"hidePrices": true}'},
            )
            self.assertFalse(hide["ok"])
            hide_ok = verify_action(
                action={"type": "hide_prices"},
                root=root,
                shop={"hidePrices": True},
                runtime={"html": '<html data-hide-prices="1"></html>', "css": "", "flags": '{"hidePrices": true}'},
            )
            self.assertTrue(hide_ok["ok"])
            header = verify_action(
                action={"type": "set_header", "logoFa": "عسل زاگرس"},
                root=root,
                runtime={"html": "<html><span>فروشگاه</span></html>", "css": "", "flags": ""},
            )
            self.assertFalse(header["ok"])
            header_ok = verify_action(
                action={"type": "set_header", "logoFa": "عسل زاگرس"},
                root=root,
                runtime={"html": '<html><span data-logo-fa="عسل زاگرس">عسل زاگرس</span></html>', "css": "", "flags": ""},
            )
            self.assertTrue(header_ok["ok"])

    def test_add_product_verify_reads_live_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "public").mkdir()
            (root / "public" / "catalog.json").write_text(
                json.dumps({"products": [{"id": "1", "title": "زعفران سوپر نگین"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            action = {"type": "add_product", "title": "زعفران سوپر نگین"}
            live = {
                "html": "<html></html>",
                "css": "",
                "flags": "",
                "catalog": json.dumps({"products": [{"title": "زعفران سوپر نگین"}]}, ensure_ascii=False),
                "products_html": "<article>زعفران سوپر نگین</article>",
                "page_html": "",
            }
            out = verify_action(
                action=action,
                root=root,
                products=[{"title": "زعفران سوپر نگین"}],
                runtime=live,
            )
            self.assertTrue(out["ok"])
            missed = verify_action(
                action=action,
                root=root,
                products=[{"title": "زعفران سوپر نگین"}],
                runtime={"html": "", "css": "", "flags": "", "catalog": '{"products":[]}', "products_html": "", "page_html": ""},
            )
            self.assertFalse(missed["ok"])

    def test_create_page_accepts_disk_before_the_menu_is_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app" / "about").mkdir(parents=True)
            (root / "public" / "pages").mkdir(parents=True)
            (root / "app" / "about" / "page.tsx").write_text("export default function About() { return null }\n", encoding="utf-8")
            (root / "public" / "pages" / "about.json").write_text(
                json.dumps({"enabled": True, "title": "درباره ما"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "public" / "storefront-flags.json").write_text(
                json.dumps({"links": [{"label": "درباره ما", "href": "/about"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            created = verify_action(
                action={"type": "create_page", "kind": "about", "label": "درباره ما"},
                root=root,
                runtime={"html": "<html></html>", "css": "", "flags": "", "page_html": ""},
                require_live=True,
            )
            self.assertTrue(created["ok"])
            linked = verify_action(
                action={"type": "add_nav_link", "href": "/about", "label": "درباره ما"},
                root=root,
                runtime={"html": "<html></html>", "css": "", "flags": (root / "public" / "storefront-flags.json").read_text(encoding="utf-8")},
                require_live=True,
            )
            self.assertTrue(linked["ok"])


if __name__ == "__main__":
    unittest.main()
