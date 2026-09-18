from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import shop_edit_service, shop_service
from app.services.shop_route_service import classify_turn, shop_state
from app.state_store import tenant_scope


class ShopPipelineScenarioTests(unittest.TestCase):
    def test_onboarding_to_ready_states(self) -> None:
        idle = {"status": "idle", "slug": "", "pendingBuild": 0}
        self.assertEqual(shop_state(idle, brief_ready=False), "onboarding")
        self.assertEqual(shop_state(idle, brief_ready=True), "ready-to-build")
        self.assertEqual(
            shop_state({"status": "ready", "slug": "demo", "pendingBuild": 0}, brief_ready=True),
            "live-clean",
        )
        self.assertEqual(
            shop_state({"status": "ready", "slug": "demo", "pendingBuild": 1}, brief_ready=True),
            "live-dirty",
        )

    def test_live_question_is_answer_not_edit(self) -> None:
        self.assertEqual(classify_turn("سبد خرید چطور کار می‌کند؟")["route"], "answer")

    def test_mixed_edit_classifies_once(self) -> None:
        out = classify_turn("رنگ را زرشکی کن")
        self.assertEqual(out["route"], "edit")
        self.assertTrue(out["actions"])

    def test_start_build_keeps_pending_until_ready(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_service._save_shop(
                    {
                        **shop_service._shop(),
                        "slug": "demo-shop",
                        "status": "ready",
                        "pendingBuild": 3,
                        "port": 12410,
                        "jobId": "j1",
                    }
                )
                with (
                    patch("app.services.shop_edit_service.spawn_rebuild") as spawn,
                    patch.object(shop_service, "_emit_build"),
                ):
                    shop_service.start_build(prompt="x", rebuild=True)
                spawn.assert_called_once()
                self.assertEqual(shop_service._shop()["pendingBuild"], 3)

    def test_revision_conflict_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "site"
            root.mkdir()
            shop = {"jobId": "old", "siteRevision": 1, "pendingBuild": 0, "slug": "demo"}
            with patch("app.services.shop_service._shop", return_value={"jobId": "new", "siteRevision": 4}):
                result = asyncio.run(
                    shop_edit_service._run_action_list(
                        shop,
                        root,
                        [{"type": "set_brand", "fields": {"name": "x"}}],
                        prompt="x",
                        page="/",
                    )
                )
            self.assertTrue(result.get("rolledBack"))
            self.assertFalse(result.get("patched"))
