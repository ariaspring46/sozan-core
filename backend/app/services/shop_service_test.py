import asyncio
import json
import subprocess
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import shop_service, shop_workspace_service
from app.state_store import tenant_scope, write_json

LIVE_SHOP = {
    "brand": "چرم‌سرای پارس",
    "slug": "cahrm-srai-pars",
    "port": 12371,
    "domain": "",
    "jobId": "fp-test",
    "status": "ready",
    "url": "https://cahrm-srai-pars.sozan-core.ir",
}
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 2100


@contextmanager
def _live_shop_chat(*, login_root: Path | None = None):
    edit = AsyncMock(return_value={"patched": False, "ok": True, "reply": "EDIT"})
    answer = AsyncMock(return_value="ANSWER")
    login_patch = patch(
        "app.services.shop_edit_service.build_dir_for",
        return_value=login_root,
    )
    tmp = tempfile.TemporaryDirectory()
    raw = tmp.name
    try:
        with (
            patch.object(settings, "state_dir", raw),
            tenant_scope("09123456789"),
            patch.object(shop_service, "_shop", return_value=dict(LIVE_SHOP)),
            patch.object(shop_service, "_refresh_job", side_effect=lambda shop: shop),
            patch.object(
                shop_service,
                "_factory_status",
                return_value={"status": "ready", "url": LIVE_SHOP["url"], "stepLabel": "", "urlOk": True},
            ),
            patch.object(shop_service, "_messages", return_value=[]),
            patch.object(shop_service, "_save_messages"),
            patch("app.services.shop_service.emit_later"),
            patch("app.services.onboard_service.get_brief", return_value={}),
            patch("app.services.onboard_service.brief_block", return_value=""),
            patch("app.services.channel_scan_service.scan_status", return_value={}),
            patch("app.services.channel_scan_service.brief_for_shop", return_value=""),
            patch("app.services.shop_edit_service.apply_live_edit", new=edit),
            patch("app.services.shop_service.complete_chat", new=answer),
            login_patch,
        ):
            yield edit, answer
    finally:
        tmp.cleanup()


class LiveShopChatRouteTests(unittest.TestCase):
    def test_homepage_advice_question_answers_instead_of_editing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "app").mkdir()
            (root / "app" / "page.tsx").write_text(
                "export default function Home() { return <h1>ویترین چرم پارس</h1> }\n",
                encoding="utf-8",
            )
            with _live_shop_chat(login_root=root) as (edit, answer):
                result = asyncio.run(shop_service.chat("صفحه ی اصلی سایت رو ببین چه بهبودی پیشنهاد میدی؟"))
        self.assertEqual(result["assistant"]["text"], "ANSWER")
        answer.assert_awaited_once()
        edit.assert_not_called()
        system = answer.await_args.kwargs["system"]
        self.assertIn("ویترین چرم پارس", system)
        self.assertNotIn("export default", system)

    def test_continue_ack_answers_instead_of_editing(self) -> None:
        with _live_shop_chat() as (edit, answer):
            edit.return_value = {"patched": False, "ok": True, "reply": "فروشگاه زنده‌ست. صفحه را همین‌جا ببین و بگو چه عوض شود."}
            result = asyncio.run(shop_service.chat("خب"))
        self.assertIn("فروشگاه زنده‌ست", result["assistant"]["text"])
        edit.assert_awaited_once()
        answer.assert_not_called()

    def test_login_question_answers_with_storefront_otp_fact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            login = root / "app" / "login"
            login.mkdir(parents=True)
            (login / "page.tsx").write_text(
                "await fetch('/api/sozan/otp/send')\n"
                "await fetch('/api/sozan/otp/verify')\n"
                "router.push('/')\n",
                encoding="utf-8",
            )
            with _live_shop_chat(login_root=root) as (edit, answer):
                result = asyncio.run(shop_service.chat("سیستم ورود سایت من به چه شکل است؟"))
        self.assertEqual(result["assistant"]["text"], "ANSWER")
        edit.assert_not_called()
        system = answer.await_args.kwargs["system"]
        self.assertIn("/api/sozan/otp/send", system)
        self.assertIn("/login", system)
        self.assertIn("کد یک‌بارمصرف", system)

    def test_cart_question_sees_real_button(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lib").mkdir()
            (root / "lib" / "brand.ts").write_text(
                "export const brand = { cartCtaFa: 'افزودن به دفتر سفارش' }\n",
                encoding="utf-8",
            )
            with _live_shop_chat(login_root=root) as (edit, answer):
                result = asyncio.run(shop_service.chat("سبد خرید چطور کار می‌کند؟"))
        self.assertEqual(result["assistant"]["text"], "ANSWER")
        edit.assert_not_called()
        system = answer.await_args.kwargs["system"]
        self.assertIn("افزودن به دفتر سفارش", system)
        self.assertIn("سبد سفارش", system)

    def test_named_color_still_edits(self) -> None:
        with _live_shop_chat() as (edit, answer):
            result = asyncio.run(shop_service.chat("میخواهم رنگ آن قرمز باشد"))
        self.assertEqual(result["assistant"]["text"], "EDIT")
        edit.assert_awaited_once()
        answer.assert_not_called()

    def test_patched_edit_asks_for_manual_build(self) -> None:
        with _live_shop_chat() as (edit, answer):
            edit.return_value = {
                "patched": True,
                "ok": True,
                "reply": "رنگ عوض شد",
                "preview": {"colors": {"primary": "#B42318"}},
            }
            result = asyncio.run(shop_service.chat("میخواهم رنگ آن قرمز باشد"))
        self.assertIn("انتشار تغییرات", result["assistant"]["text"])
        self.assertEqual(result["preview"]["colors"]["primary"], "#B42318")
        self.assertTrue(result["patched"])
        answer.assert_not_called()

    def test_start_build_clears_pending_and_skips_protected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service

                storefront_service.add_product(title="کیف", price=850000, stock=1, sku="k", category="کیف")
                shop_service._save_shop(
                    {
                        **shop_service._shop(),
                        "slug": "demo-shop",
                        "status": "ready",
                        "pendingBuild": 4,
                        "port": 12410,
                        "jobId": "j1",
                    }
                )
                with (
                    patch("app.services.shop_edit_service.spawn_rebuild") as spawn,
                    patch.object(shop_service, "_read_job_file", return_value={"buildDir": raw}),
                    patch("app.services.shop_edit_service.build_dir_for", return_value=Path(raw)),
                    patch.object(
                        shop_service,
                        "_run_factory",
                        return_value={"ok": True, "jobId": "j2", "status": "running", "slug": "demo-shop"},
                    ) as factory,
                    patch.object(shop_service, "_factory_prompt", return_value="p"),
                    patch.object(shop_service, "_publish_dns", side_effect=lambda shop: shop),
                    patch.object(shop_service, "_emit_build"),
                    patch("app.services.shop_service.get_settings", return_value={"storeName": "دمو"}),
                    patch("app.services.shop_service.record_site"),
                ):
                    shop_service.start_build(prompt="x", rebuild=True)
                    spawn.assert_called_once()
                    factory.assert_not_called()
                    self.assertEqual(shop_service._shop()["pendingBuild"], 4)
                    shop_service._save_shop(
                        {**shop_service._shop(), "status": "ready", "pendingBuild": 2, "jobId": "j1"}
                    )
                    shop_service.start_build(prompt="از نو بساز", rebuild=True)
                    factory.assert_called_once()

                shop_service._save_shop({**shop_service._shop(), "slug": "joahr-froshi", "status": "ready"})
                with patch.object(shop_service, "_run_factory") as blocked:
                    out = shop_service.start_build(prompt="x", rebuild=True)
                blocked.assert_not_called()
                self.assertFalse(out["ok"])

    def test_full_rebuild_phrases_cover_natural_persian(self) -> None:
        for text in ("از نو بساز", "از دیزاینش خوشم نمیاد میخوام از نو ساخته شه", "ازنو درستش کن", "از اول بسازش", "بساز از صفر"):
            self.assertTrue(shop_service._wants_full_rebuild(text), text)
        for text in ("دوباره بساز", "رنگ را آبی کن", "قیمت را عوض کن"):
            self.assertFalse(shop_service._wants_full_rebuild(text), text)

    def test_rebuild_with_missing_job_falls_back_to_fresh_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service

                storefront_service.add_product(title="کیف", price=850000, stock=1, sku="k", category="کیف")
                shop_service._save_shop(
                    {**shop_service._shop(), "slug": "demo-shop", "status": "failed", "port": 12410, "jobId": "gone"}
                )
                with (
                    patch("app.services.shop_edit_service.spawn_rebuild") as spawn,
                    patch.object(shop_service, "_read_job_file", return_value=None),
                    patch.object(
                        shop_service,
                        "_run_factory",
                        return_value={"ok": True, "jobId": "j9", "status": "running", "slug": "demo-shop"},
                    ) as factory,
                    patch.object(shop_service, "_factory_prompt", return_value="p"),
                    patch.object(shop_service, "_publish_dns", side_effect=lambda shop: shop),
                    patch.object(shop_service, "_emit_build"),
                    patch("app.services.shop_service.get_settings", return_value={"storeName": "دمو"}),
                    patch("app.services.shop_service.record_site"),
                ):
                    out = shop_service.start_build(prompt="دوباره بساز", rebuild=True)
                spawn.assert_not_called()
                factory.assert_called_once()
                self.assertTrue(out["ok"])
                self.assertTrue(out["freshBuild"])
                self.assertEqual(shop_service._shop()["error"], "")

    def test_from_page_uses_catalog_instead_of_edit(self) -> None:
        with _live_shop_chat() as (edit, answer):
            edit.return_value = {
                "patched": True,
                "ok": True,
                "reply": "۱ مدل از پیج در کاتالوگ است: کیف مجلسی. روی سایت نمی‌آیند تا بیلد بزنی.",
            }
            result = asyncio.run(shop_service.chat("از داخل پیجم مدل کیف ها رو بزار"))
            self.assertIn("کاتالوگ", result["assistant"]["text"])
            self.assertIn("کیف مجلسی", result["assistant"]["text"])
            self.assertIn("از پیج", shop_workspace_service.instructions_block())
            edit.assert_awaited_once()
            answer.assert_not_called()

    def test_hide_prices_skips_edit(self) -> None:
        with _live_shop_chat() as (edit, answer):
            edit.return_value = {
                "patched": True,
                "ok": True,
                "reply": "قیمت روی سایت نشان داده نمی‌شود. بیلد بزن تا اعمال شود.",
            }
            result = asyncio.run(shop_service.chat("هنوز حذف نشدن و قیمت نزن فعلا برای محصولات"))
            self.assertIn("قیمت", result["assistant"]["text"])
            edit.assert_awaited_once()
            answer.assert_not_called()
            self.assertIn("قیمت روی کارت کالا نشان داده نشود", shop_workspace_service.instructions_block())

    def test_selected_element_question_still_edits(self) -> None:
        with _live_shop_chat() as (edit, answer):
            result = asyncio.run(
                shop_service.chat("این را بهتر کن؟", view_target="خرید کنید"),
            )
        self.assertEqual(result["assistant"]["text"], "EDIT")
        edit.assert_awaited_once()
        answer.assert_not_called()

    def test_saffron_catalog_is_not_bags_and_gets_generated_photos(self) -> None:
        from app.services import storefront_service

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                storefront_service.add_product(
                    title="زعفران نگین قائنات",
                    price=0,
                    stock=1,
                    sku="spice",
                    category="زعفران",
                    description="رشته‌های سرخ",
                )
                self.assertEqual(shop_service._factory_category_slug("زعفران"), "saffron")
                with patch("app.services.shop_edit_service.fetch_image_png", return_value=FAKE_PNG):
                    payload = shop_service._factory_catalog_payload()
                self.assertEqual(payload["categorySlug"], "saffron")
                self.assertEqual(payload["categoryFa"], "زعفران")
                self.assertNotEqual(payload["categorySlug"], "bags")
                self.assertNotIn("کیف", json.dumps(payload, ensure_ascii=False))
                self.assertNotIn("leather handbags", payload["heroPrompt"])
                self.assertNotIn("single bag", payload["items"][0]["prompt"])
                self.assertFalse(Path(str(payload["items"][0].get("sourceImage") or "")).is_file())
                with patch("app.services.shop_edit_service.fetch_image_png") as fetch:
                    again = shop_service._factory_catalog_payload()
                fetch.assert_not_called()
                self.assertEqual(again["items"][0].get("sourceImage"), payload["items"][0].get("sourceImage"))

    def test_run_factory_timeout_persian(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "fastpath.py"
            script.write_text("print(1)\n", encoding="utf-8")
            with patch.object(shop_service, "_factory_env", return_value={}), patch(
                "app.services.shop_service.subprocess.run",
                side_effect=subprocess.TimeoutExpired("x", 40),
            ), patch("app.services.shop_service.settings") as mocked:
                mocked.factory_script = script
                out = shop_service._run_factory(["status"])
        self.assertFalse(out["ok"])
        self.assertIn("دیر", out["error"])

    def test_refresh_job_clears_pending_when_ready_with_host(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop = shop_service._save_shop(
                    {
                        **shop_service.DEFAULT_SHOP,
                        "slug": "demo-shop",
                        "status": "running",
                        "pendingBuild": 3,
                        "jobId": "j1",
                        "publicHost": "demo.sozan-core.ir",
                        "port": 12377,
                    }
                )
                with patch.object(shop_service, "_bind_live_job", side_effect=lambda row: row), patch.object(
                    shop_service, "_factory_status", return_value={"status": "ready", "urlOk": False, "jobId": "j1"}
                ), patch.object(shop_service, "_publish_catalog_images"), patch.object(
                    shop_service, "_publish_dns", side_effect=lambda row: row
                ):
                    saved = shop_service._refresh_job(shop)
                self.assertEqual(int(saved.get("pendingBuild") or 0), 0)

    def test_set_domain_custom_starts_partial_setup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            map_path = Path(raw) / "shop-upstreams.map"
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json(
                    "shop.json",
                    {
                        **shop_service.DEFAULT_SHOP,
                        "slug": "sozan",
                        "port": 12377,
                        "publicHost": "sozan.sozan-core.ir",
                        "cnameTarget": "sozan.sozan-core.ir.",
                        "status": "ready",
                    },
                )
                with (
                    patch.object(shop_service, "_shop_map_path", return_value=map_path),
                    patch.object(shop_service, "_reload_edge"),
                    patch.object(shop_service, "_publish_dns", side_effect=lambda shop: shop),
                    patch(
                        "app.services.arvan_dns_service.check_cname",
                        return_value={"ok": False, "status": "waiting", "detail": "wait"},
                    ),
                    patch(
                        "app.services.arvan_dns_service.start_cname_setup",
                        return_value={"ok": True, "host": "shop.example.com"},
                    ) as setup,
                    patch("app.services.channel_scan_service.scan_status", return_value={}),
                    patch.object(shop_service, "_factory_status", return_value={}),
                    patch.object(shop_service, "_refresh_job", side_effect=lambda shop: shop),
                ):
                    shop_service.set_domain("https://shop.example.com/x")
                setup.assert_called_once_with("shop.example.com", "sozan")
                saved = shop_service._shop()
                self.assertEqual(saved["domain"], "shop.example.com")
                self.assertFalse(saved["cnameOk"])
                self.assertEqual(saved["cnameSetup"]["host"], "shop.example.com")

    def test_set_domain_rejects_host_claimed_by_another_shop(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw):
                with tenant_scope("09135409482"):
                    write_json("shop.json", {**shop_service.DEFAULT_SHOP, "slug": "a", "domain": "mine.example.com"})
                with tenant_scope("09121112222"):
                    write_json("shop.json", {**shop_service.DEFAULT_SHOP, "slug": "b", "port": 12380})
                    with self.assertRaises(ValueError) as ctx:
                        shop_service.set_domain("https://Mine.Example.com/")
                    self.assertIn("دیگری", str(ctx.exception))
                    self.assertNotEqual(shop_service._shop().get("domain"), "mine.example.com")
                with tenant_scope("09135409482"):
                    self.assertEqual(shop_service.domain_owner("mine.example.com"), "09135409482")

    def test_set_domain_sozan_host_skips_cname_setup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                write_json(
                    "shop.json",
                    {
                        **shop_service.DEFAULT_SHOP,
                        "slug": "sozan",
                        "port": 12377,
                        "publicHost": "sozan.sozan-core.ir",
                        "status": "ready",
                    },
                )
                with (
                    patch.object(shop_service, "_write_shop_upstream"),
                    patch.object(shop_service, "_publish_dns", side_effect=lambda shop: shop),
                    patch("app.services.arvan_dns_service.start_cname_setup") as setup,
                    patch("app.services.channel_scan_service.scan_status", return_value={}),
                    patch.object(shop_service, "_factory_status", return_value={}),
                    patch.object(shop_service, "_refresh_job", side_effect=lambda shop: shop),
                ):
                    shop_service.set_domain("sozan.sozan-core.ir")
                setup.assert_not_called()
                saved = shop_service._shop()
                self.assertTrue(saved["cnameOk"])
                self.assertEqual(saved["cnameCheck"]["status"], "sozan-host")

    def test_write_shop_upstream_rebuilds_without_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            map_path = Path(raw) / "shop-upstreams.map"
            names_path = Path(raw) / "shop-custom-names.conf"
            map_path.write_text(
                "not-a-real-cname.invalid 127.0.0.1:12377;\njoahr-froshi.sozan-core.ir 127.0.0.1:12370;\n",
                encoding="utf-8",
            )
            with patch.object(settings, "state_dir", raw), tenant_scope("09135409482"):
                with (
                    patch.object(shop_service, "_shop_map_path", return_value=map_path),
                    patch.object(shop_service, "_shop_custom_names_path", return_value=names_path),
                    patch.object(shop_service, "_reload_edge"),
                ):
                    shop_service._write_shop_upstream(
                        {
                            "slug": "sozan",
                            "port": 12377,
                            "publicHost": "sozan.sozan-core.ir",
                            "domain": "shop.example.com",
                        }
                    )
            text = map_path.read_text(encoding="utf-8")
            names = names_path.read_text(encoding="utf-8")
            self.assertIn("sozan.sozan-core.ir 127.0.0.1:12377;", text)
            self.assertIn("shop.example.com 127.0.0.1:12377;", text)
            self.assertIn("joahr-froshi.sozan-core.ir 127.0.0.1:12370;", text)
            self.assertNotIn("invalid", text)
            self.assertIn("server_name shop.example.com;", names)
            self.assertNotIn("sozan.sozan-core.ir", names)

    def test_reload_edge_skips_reload_when_nginx_t_fails(self) -> None:
        failed = subprocess.CompletedProcess(["nginx", "-t"], 1, stdout="", stderr="bad")

        class FakeNginx:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def is_file(self) -> bool:
                return True

            def __str__(self) -> str:
                return "/usr/sbin/nginx"

        with (
            patch("app.services.shop_service.Path", FakeNginx),
            patch("app.services.shop_service.subprocess.run", return_value=failed) as run,
            self.assertLogs("sozan.shop", level="WARNING") as captured,
        ):
            shop_service._reload_edge()
        self.assertEqual(run.call_count, 1)
        self.assertTrue(any("nginx -t failed" in line for line in captured.output))


class PriceMissingBuildTests(unittest.TestCase):
    def test_start_build_blocks_when_all_prices_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service

                storefront_service.add_product(title="جلد زیپی", price=0, stock=1, sku="z", category="جلد زیپی")
                shop_service._save_shop({**shop_service._shop(), "slug": "demo", "status": "ready", "hidePrices": False})
                with patch.object(shop_service, "_run_factory") as factory, patch.object(shop_service, "_emit_build"):
                    result = shop_service.start_build(prompt="از نو بساز", rebuild=True)
                factory.assert_not_called()
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "price_missing")
                self.assertIn("قیمت", result["error"])

    def test_contact_and_direct_notes_still_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service

                storefront_service.add_product(
                    title="جلد زیپی",
                    price=0,
                    stock=1,
                    sku="z",
                    category="جلد زیپی",
                    priceNote="تماس بگیرید",
                )
                shop_service._save_shop({**shop_service._shop(), "slug": "demo", "status": "ready", "jobId": "j1"})
                with (
                    patch("app.services.shop_edit_service.spawn_rebuild") as spawn,
                    patch.object(shop_service, "_run_factory") as factory,
                    patch.object(shop_service, "_emit_build"),
                ):
                    result = shop_service.start_build(prompt="بیلد کن", rebuild=True, revise_only=True)
                spawn.assert_not_called()
                factory.assert_not_called()
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "price_missing")
                self.assertIn("استعلام", result["error"])

                storefront_service.update_product(
                    storefront_service.list_products()["products"][0]["id"],
                    {"priceNote": "دایرکت"},
                )
                with (
                    patch("app.services.shop_edit_service.spawn_rebuild") as spawn,
                    patch.object(shop_service, "_run_factory") as factory,
                    patch.object(shop_service, "_emit_build"),
                ):
                    result = shop_service.start_build(prompt="از نو بساز", rebuild=True)
                spawn.assert_not_called()
                factory.assert_not_called()
                self.assertEqual(result["code"], "price_missing")

    def test_empty_catalog_blocks_unless_hide_prices(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_service._save_shop({**shop_service._shop(), "slug": "demo", "status": "ready", "hidePrices": False})
                with patch.object(shop_service, "_run_factory") as factory, patch.object(shop_service, "_emit_build"):
                    result = shop_service.start_build(prompt="از نو بساز", rebuild=True)
                factory.assert_not_called()
                self.assertEqual(result["code"], "price_missing")

    def test_inquiry_url_from_instagram_handle(self) -> None:
        self.assertEqual(
            shop_service._inquiry_url({"sourceHandle": "@optic_day", "source": "instagram"}),
            "https://ig.me/m/optic_day",
        )
        self.assertEqual(
            shop_service._inquiry_url({"sourceHandle": "shop_tg", "source": "telegram"}),
            "https://t.me/shop_tg",
        )
        self.assertEqual(shop_service._inquiry_url({"sourceHandle": "", "source": "instagram"}), "")
        self.assertEqual(shop_service._inquiry_url({"sourceHandle": "123456789", "source": "telegram"}), "")

    def test_start_build_allows_hide_prices(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                from app.services import storefront_service

                storefront_service.add_product(title="جلد زیپی", price=0, stock=1, sku="z", category="جلد زیپی")
                shop_service._save_shop({**shop_service._shop(), "slug": "demo", "status": "ready", "hidePrices": True})
                with (
                    patch.object(shop_service, "_run_factory", return_value={"ok": True, "jobId": "j", "status": "running"}),
                    patch.object(shop_service, "_emit_build"),
                    patch.object(shop_service, "_publish_dns", side_effect=lambda shop: shop),
                    patch("app.services.shop_service.get_settings", return_value={"storeName": "دمو"}),
                    patch("app.services.shop_service.record_site"),
                ):
                    result = shop_service.start_build(prompt="از نو بساز", rebuild=True)
                self.assertTrue(result.get("ok"))


class OperatorErrorTests(unittest.TestCase):
    def test_readiness_catalog_maps_to_persian(self) -> None:
        self.assertIn("کاتالوگ", shop_service._operator_error("readiness failed: catalog"))

    def test_gpu_busy_maps_to_persian(self) -> None:
        raw = (
            "ensure DESIGN_27B failed: WARN: GPU1 still loaded ['ornith-1.5-35b']; last-resort full unload\n"
            "FAIL: extra GPU1 LLMs still loaded: ['ornith-1.5-35b']\n"
        )
        self.assertIn("مشغول", shop_service._operator_error(raw))
        self.assertIn("مشغول", shop_service._operator_error("gpu_busy: qwen3.8-27b in flight"))

    def test_raw_fail_and_traceback_use_safe_persian(self) -> None:
        self.assertEqual(shop_service._operator_error("FAIL: GPU exploded"), shop_service.SAFE_BUILD)
        self.assertEqual(shop_service._operator_error("Traceback (most recent call last):"), shop_service.SAFE_BUILD)

    def test_denylist_strips_seed_and_fail(self) -> None:
        self.assertEqual(shop_service.sanitize_shop_text("send your seed phrase now"), "پیام نامعتبر حذف شد")
        self.assertEqual(shop_service.sanitize_shop_text("FAIL: GPU exploded"), "پیام نامعتبر حذف شد")
        self.assertEqual(shop_service.sanitize_shop_text("ساخت فروشگاه شروع شد."), "ساخت فروشگاه شروع شد.")

    def test_edit_fail_coalesces_to_one_bubble(self) -> None:
        first = {"id": "a1", "role": "assistant", "text": "صفحه ساخته نشد.", "at": 1}
        rows = [first]
        again = shop_service._append_assistant(
            rows,
            {"id": "a2", "role": "assistant", "text": "تیتر روی این صفحه پیدا نشد.", "at": 2},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(again["text"], shop_service.EDIT_FAIL_ONE)

    def test_bind_live_job_marks_stale_busy_failed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            jobs = Path(raw) / "jobs"
            jobs.mkdir()
            job_id = "stale-job"
            path = jobs / f"{job_id}.json"
            path.write_text(json.dumps({"id": job_id, "slug": "demo", "status": "running"}), encoding="utf-8")
            import os

            old = time.time() - 31 * 60
            os.utime(path, (old, old))
            shop = {"slug": "demo", "jobId": job_id, "status": "running"}
            with patch.object(shop_service, "_fastpath_root", return_value=Path(raw)):
                out = shop_service._bind_live_job(shop)
            self.assertEqual(out["status"], "failed")
            self.assertIn("تمام نشد", out.get("error") or "")

    def test_bind_live_job_fails_phantom_busy_after_stale(self) -> None:
        shop = {
            "slug": "demo",
            "jobId": "ghost",
            "status": "running",
            "buildAt": time.time() - 31 * 60,
        }
        with tempfile.TemporaryDirectory() as raw:
            (Path(raw) / "jobs").mkdir()
            with patch.object(shop_service, "_fastpath_root", return_value=Path(raw)):
                out = shop_service._bind_live_job(shop)
        self.assertEqual(out["status"], "failed")
        self.assertIn("تمام نشد", out.get("error") or "")


class CatalogBeforeStorefrontTests(unittest.TestCase):
    def _chat(self, text: str):
        from app.services import storefront_service

        answer = AsyncMock(return_value="«کفش» اضافه شد")
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09120001111"),
                patch.object(shop_service, "_shop", return_value={"status": "idle", "slug": ""}),
                patch.object(shop_service, "_refresh_job", side_effect=lambda shop: shop),
                patch("app.services.shop_service.emit_later"),
                patch("app.services.shop_service.complete_chat", new=answer),
                patch("app.services.channel_scan_service.scan_status", return_value={}),
            ):
                result = asyncio.run(shop_service.chat(text))
                products = storefront_service.list_products().get("products") or []
        return result, products, answer

    def test_persian_price_is_stored_and_quoted(self) -> None:
        result, products, answer = self._chat("کفش چرم مشکی را اضافه کن، قیمت ۴٬۸۰۰٬۰۰۰ تومان")
        answer.assert_not_called()
        self.assertEqual(len(products), 1)
        self.assertEqual(int(products[0]["price"]), 4800000)
        reply = result["assistant"]["text"]
        self.assertIn("4800000", reply)
        self.assertIn(str(products[0]["title"]), reply)
        self.assertNotIn("اضافه شد", reply)

    def test_missing_price_does_not_insert_or_claim_success(self) -> None:
        result, products, answer = self._chat("کفش چرم مشکی را اضافه کن")
        answer.assert_not_called()
        self.assertEqual(products, [])
        reply = result["assistant"]["text"]
        self.assertIn("قیمت", reply)
        self.assertNotIn("اضافه شد", reply)


if __name__ == "__main__":
    unittest.main()
