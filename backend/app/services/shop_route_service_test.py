from __future__ import annotations

import unittest

from app.services.shop_route_service import BUILDING, LIVE_CLEAN, LIVE_DIRTY, classify_turn, shop_state


class ShopRouteTests(unittest.TestCase):
    def test_states(self) -> None:
        self.assertEqual(shop_state({"status": "idle", "slug": ""}, brief_ready=False), "onboarding")
        self.assertEqual(shop_state({"status": "idle", "slug": ""}, brief_ready=True), "ready-to-build")
        self.assertEqual(shop_state({"status": "running", "slug": ""}, brief_ready=True), BUILDING)
        self.assertEqual(shop_state({"status": "ready", "slug": "x", "pendingBuild": 0}, brief_ready=True), LIVE_CLEAN)
        self.assertEqual(shop_state({"status": "ready", "slug": "x", "pendingBuild": 2}, brief_ready=True), LIVE_DIRTY)

    def test_question_is_answer_route(self) -> None:
        out = classify_turn("سبد خرید چطور کار می‌کند؟")
        self.assertEqual(out["route"], "answer")

    def test_color_is_edit_route(self) -> None:
        out = classify_turn("رنگ را زرشکی کن")
        self.assertEqual(out["route"], "edit")
        self.assertTrue(out["actions"])
