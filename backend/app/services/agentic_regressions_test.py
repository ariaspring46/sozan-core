"""Regressions for docs/راستی‌آزمایی-اجزای-عاملی-سوزان.md (N2–N7, F2, F5)."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import inbox_agent_service as ia
from app.services import router_service as rs
from app.services import shop_edit_service as se
from app.services import storefront_service
from app.state_store import read_json, tenant_scope, write_json

TENANT = "09120001111"



_VOICE_PATCHES: list = []


def setUpModule() -> None:
    # The assistant's own voice (shop_voice_service) asks the cloud model; tests that are not about it take the plain fallbacks.
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE_PATCHES.append(started)


def tearDownModule() -> None:
    while _VOICE_PATCHES:
        _VOICE_PATCHES.pop().stop()

class _StateCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        state = patch.object(settings, "state_dir", self.tmp.name)
        state.start()
        self.addCleanup(state.stop)
        scope = tenant_scope(TENANT)
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)


def _call(name: str, **args) -> dict:
    return {"id": f"c{time.monotonic_ns()}", "name": name, "arguments": args}


def _scripted(steps):
    state = {"i": 0}

    async def fake(messages, *, allow_payment, timeout):
        step = steps[min(state["i"], len(steps) - 1)]
        state["i"] += 1
        return step[0], step[1], {}

    return fake


class DirectNumberGuardTests(_StateCase):
    def test_amounts_read_separators_and_spoken_prices(self) -> None:
        cases = {
            "قیمت ۱٬۵۰۰٬۰۰۰ تومان": "1500000",
            "1,500,000 تومان": "1500000",
            "یک و نیم میلیون تومان": "1500000",
            "۲.۵ میلیون تومنه": "2500000",
            "دو میلیون و پانصد هزار تومان": "2500000",
        }
        for text, value in cases.items():
            self.assertIn(value, ia._amounts(text), msg=text)
        self.assertEqual(ia._amounts("سایز ۳۸ و ۲ عدد"), set())
        self.assertEqual(ia._amounts("سایز ۵۴ دارید؟"), set())
        self.assertTrue(ia._numbers_ok("سایز ۵۴ موجوده", "سایز ۵۴"))

    def test_wrong_formatted_price_after_stock_is_handed_off(self) -> None:
        async def hint(_sentence):
            return "stock"

        storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=3, sku="n1")
        question = "برای هدیهٔ تولد چی پیشنهاد می‌دید؟ قیمتش چنده؟"
        for wrong, ok in (
            ("قیمت گردنبند نقره ۱٬۵۰۰٬۰۰۰ تومان است", False),
            ("قیمت گردنبند نقره یک و نیم میلیون تومان است", False),
            ("قیمت گردنبند نقره ۱٬۹۵۰٬۰۰۰ تومان است", True),
        ):
            steps = [("", [_call("stock", product="گردنبند نقره")]), (wrong, [])]
            with patch.object(ia, "_complete", _scripted(steps)), patch.object(ia, "emit_later"), patch.object(
                ia, "intent_hint", hint
            ):
                reply = asyncio.run(ia.answer(question, thread={"sender": "x"}, source="battery"))
            self.assertEqual(reply != ia.HANDOFF_LINE, ok, msg=wrong)

    def test_a_size_answer_is_not_handed_off(self) -> None:
        async def hint(_sentence):
            return "stock"

        storefront_service.add_product(title="انگشتر", price=850000, stock=2, sku="s54", sizes="54")
        steps = [("", [_call("stock", product="انگشتر")]), ("سایز ۵۴ موجوده", [])]
        with patch.object(ia, "_complete", _scripted(steps)), patch.object(ia, "emit_later"), patch.object(
            ia, "intent_hint", hint
        ):
            reply = asyncio.run(ia.answer("سایز ۵۴ دارید؟", thread={"sender": "x"}, source="battery"))
        self.assertNotEqual(reply, ia.HANDOFF_LINE)
        self.assertIn("۵۴", reply)


class PaymentLinkTests(_StateCase):
    def setUp(self) -> None:
        super().setUp()
        self.orders: list[dict] = []

        async def order(**kwargs):
            self.orders.append(kwargs)
            return {"payUrl": f"https://pay.example/o{len(self.orders)}", "amount": kwargs["amount"], "title": kwargs["title"]}

        for item in (
            patch("app.services.pay_service.create_order", order),
            patch.object(ia, "_seller_has_own_gateway", lambda: True),
            patch.object(ia, "_dry_gateway", lambda: False),
            patch.object(ia, "emit_later"),
        ):
            item.start()
            self.addCleanup(item.stop)

    def test_out_of_stock_and_qty_over_stock(self) -> None:
        storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=0, sku="n1")
        storefront_service.add_product(title="دستبند طلا", price=4200000, stock=2, sku="d1")
        none = asyncio.run(ia.run_tool("payment_link", {"product": "گردنبند نقره", "qty": 1}, thread={}))
        capped = asyncio.run(ia.run_tool("payment_link", {"product": "دستبند طلا", "qty": 5}, thread={}))
        self.assertFalse(none["ok"])
        self.assertEqual(capped["amount"], 2 * 4200000)
        self.assertEqual([row["qty"] for row in self.orders], [2])

    def test_one_order_per_turn(self) -> None:
        storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=3, sku="n1")
        steps = [
            ("", [_call("payment_link", product="گردنبند نقره", qty=1), _call("payment_link", product="گردنبند نقره", qty=1)]),
            ("", [_call("payment_link", product="گردنبند نقره", qty=2)]),
            ("لینک پرداخت آماده است", []),
        ]
        with patch.object(ia, "_complete", _scripted(steps)):
            reply = asyncio.run(ia.answer("لینک پرداخت بفرستید", thread={"sender": "x", "id": "t1"}, source="battery"))
        self.assertEqual(len(self.orders), 1)
        self.assertEqual(reply.count("https://pay.example/"), 1)


class ExpiredCardTests(_StateCase):
    def test_expired_card_is_not_executed(self) -> None:
        applied: list[str] = []

        async def complete(_messages, _tools):
            return {"text": "", "tool_calls": [{"name": "set_voice_tone", "arguments": {"toneId": "formal"}}], "usage": {}}

        with patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")), patch.object(rs, "_emit"), patch(
            "app.services.voice_service.apply_tone", side_effect=lambda tone, *a, **k: applied.append(tone) or {}
        ):
            out = asyncio.run(rs.turn("لحن جواب‌ها رو رسمی کن", complete=complete))
            card = out["pendingConfirm"]["id"]
            name = rs._pend_name(rs._bind_thread(""))
            row = read_json(name, {})
            row["expiresAt"] = time.time() - 60
            write_json(name, row)
            out = asyncio.run(rs.turn("", confirm_id=card))
        rs._THREAD.set("")
        self.assertEqual(applied, [])
        self.assertEqual(out["messages"][-1]["text"], rs.CARD_EXPIRED)
        self.assertFalse(out.get("pendingConfirm"))


class ImageBudgetTests(_StateCase):
    def test_cloud_image_respects_the_budget_cap(self) -> None:
        from app.services import ai_budget_service, image_provider_service as ip

        calls: list[str] = []

        def chain(prompt, size, model, raw, **_kw):
            calls.append(model)
            return {"png": b"x" * 4096, "model": model, "cost": 0.04}

        with patch("app.services.plan_service.current_plan_id", return_value="free"), patch.object(
            ip, "_cloud_chain", chain
        ), patch.object(ip, "emit_later"), patch("app.services.llm.emit_later"):
            ai_budget_service.record_cost(surface="studio", usd=5.0)
            out = ip.generate_image("a silver necklace", plan="free")
        self.assertEqual(calls, [])
        self.assertTrue(out.get("failed"))
        self.assertEqual(ip.last_error, "budget")


class ShopEditRollbackTests(_StateCase):
    def _root(self) -> Path:
        root = Path(self.tmp.name) / "site"
        for rel, text in {
            "lib/brand.ts": "export const brand = {}\n",
            "app/page.tsx": "<h1>x</h1>\n",
            "public/storefront-flags.json": "{}",
            "public/catalog.json": "[]",
        }.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        (root / "public/images").mkdir(parents=True, exist_ok=True)
        (root / "public/images/hero.png").write_bytes(b"OLD")
        return root

    def _run(self, root: Path, actions: list[dict], verify) -> dict:
        async def hero(shop, root, prompt):
            (root / "public/images/hero.png").write_bytes(b"NEW")
            return {"preview": {}}

        with patch("app.services.shop_edit_verify.verify_action", verify), patch.object(
            se, "publish_shop_runtime", lambda *a, **k: None
        ), patch.object(se, "publish_shop_hero", lambda *a, **k: None), patch.object(se, "apply_hero_image", hero), patch(
            "app.services.shop_service._save_shop", lambda s: None
        ), patch("app.services.shop_service._shop", lambda: {"siteRevision": 0}), patch.object(
            se, "_finish_edit", lambda shop, reply, *a, **k: {"ok": True, "patched": True, "reply": reply}
        ):
            return asyncio.run(se._run_action_list({"siteRevision": 0}, root, actions, prompt="x", page="/"))

    def test_rolled_back_create_page_leaves_no_files(self) -> None:
        root = self._root()
        out = self._run(root, [{"type": "create_page", "kind": "about"}], lambda **kw: {"ok": False})
        self.assertTrue(out.get("rolledBack"))
        self.assertFalse((root / "app/about/page.tsx").exists())
        self.assertFalse((root / "public/pages/about.json").exists())
        self.assertFalse((root / "lib/nav.ts").exists())
        self.assertEqual(list(root.glob(".sozan-turn-*")), [])

    def test_hero_restored_when_a_later_action_fails(self) -> None:
        root = self._root()

        def verify(*, action, **_kw):
            return {"ok": action.get("type") == "hero_image"}

        self._run(root, [{"type": "hero_image"}, {"type": "create_page", "kind": "about"}], verify)
        self.assertEqual((root / "public/images/hero.png").read_bytes(), b"OLD")

    def test_snapshot_has_no_forty_file_cap(self) -> None:
        root = self._root()
        for index in range(45):
            path = root / "components" / f"C{index:02d}.tsx"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<p/>\n", encoding="utf-8")
        se.snapshot_edit_files(root, ".sozan-test")
        self.assertTrue((root / ".sozan-test/components/C44.tsx").is_file())
        self.assertTrue((root / ".sozan-test/public/images/hero.png").is_file())


class SharedStateFileTests(_StateCase):
    def test_concurrent_writers_keep_each_others_keys(self) -> None:
        import threading

        from app.state_store import tenant_scope, update_json

        def writer(key: str) -> None:
            with tenant_scope(TENANT):
                for i in range(40):
                    update_json("shop.json", lambda shop, i=i: shop.__setitem__(key, i), {}, lock="shop")

        threads = [threading.Thread(target=writer, args=(k,)) for k in ("brand", "paySecret", "status")]
        for item in threads:
            item.start()
        for item in threads:
            item.join()
        shop = read_json("shop.json", {})
        self.assertEqual({k: shop.get(k) for k in ("brand", "paySecret", "status")}, {"brand": 39, "paySecret": 39, "status": 39})

    def test_pay_secret_and_store_name_do_not_clobber(self) -> None:
        from app.services import pay_service, settings_service

        write_json("shop.json", {"slug": "demo", "status": "ready"})
        secret = pay_service.ensure_pay_secret()
        with patch.object(settings_service, "plan_service", create=True):
            settings_service.save_settings({"storeName": "گالری"})
        shop = read_json("shop.json", {})
        self.assertEqual(shop.get("paySecret"), secret)
        self.assertEqual(shop.get("brand"), "گالری")
        self.assertEqual(shop.get("status"), "ready")
        self.assertEqual(pay_service.ensure_pay_secret(), secret)


class RouterTraceTests(_StateCase):
    def test_trace_rotates(self) -> None:
        from app.state_store import tenant_dir

        path = tenant_dir() / "router-turns.jsonl"
        path.write_text("x" * (rs.TRACE_MAX_BYTES + 1), encoding="utf-8")
        rs._TURN_TRACE.set({"text": "سلام"})
        rs._flush_trace({})
        self.assertLess(path.stat().st_size, 1000)
        self.assertTrue((tenant_dir() / "router-turns.1.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
