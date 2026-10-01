from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import ai_budget_service, llm, plan_service
from app.state_store import tenant_scope


class AiBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state = patch.object(settings, "state_dir", self._tmp.name)
        self._state.start()
        self.addCleanup(self._state.stop)

    def _record(self, tenant: str, usd: float, *, surface: str = "shop") -> None:
        with tenant_scope(tenant):
            ai_budget_service.record_cost(surface=surface, usd=usd)

    def test_record_cost_accumulates_per_tenant_day(self) -> None:
        self._record("09120000001", 0.0005)
        self._record("09120000001", 0.001)
        self._record("09120000002", 0.05)
        row = ai_budget_service.tenant_status("09120000001")
        self.assertEqual(row["dailyUsedUsd"], 0.0015)
        self.assertEqual(ai_budget_service.tenant_status("09120000002")["dailyUsedUsd"], 0.05)
        self.assertEqual(row["tier"], "ok")

    def test_voice_cost_is_sozans_own_not_a_tenant(self) -> None:
        self._record("09120000001", 0.01)
        with tenant_scope("09120000001"):
            ai_budget_service.record_cost(surface="voice", usd=5.0)
        row = ai_budget_service.tenant_status("09120000001")
        self.assertEqual(row["dailyUsedUsd"], 0.01)
        report = ai_budget_service.report()
        self.assertEqual(report["sozanVoiceWeekUsd"], 5.0)

    def test_warn_at_80_and_capped_at_100_daily(self) -> None:
        with patch.dict(
            ai_budget_service.DEFAULTS["plans"],
            {"pro": {"dailyUsd": 0.1, "weeklyUsd": 0.4}},
        ):
            with tenant_scope("09120000001"):
                plan_service.set_plan("pro")
            self._record("09120000001", 0.085)
            self.assertEqual(ai_budget_service.tenant_status("09120000001")["tier"], "warn")
            self._record("09120000001", 0.021)
            self.assertEqual(ai_budget_service.tenant_status("09120000001")["tier"], "capped")
            with tenant_scope("09120000001"):
                self.assertEqual(ai_budget_service.cloud_blocked(surface="inbox"), "daily")

    def test_weekly_cap_blocks_even_below_daily(self) -> None:
        with patch.dict(
            ai_budget_service.DEFAULTS["plans"],
            {"free": {"dailyUsd": 1.0, "weeklyUsd": 0.1}},
        ):
            self._record("09120000001", 0.05)
            # Backdate the spend so it lands on a previous day of the same week.
            ledger = ai_budget_service._ledger()
            ledger["2000-01-01"] = {"09120000001": 0.06}
            with ai_budget_service.shared_lock():
                ai_budget_service._save_ledger(ledger)
            self.assertEqual(ai_budget_service.tenant_status("09120000001")["tier"], "capped")
            with tenant_scope("09120000001"):
                self.assertEqual(ai_budget_service.cloud_blocked(surface="shop"), "weekly")

    def test_company_cap_blocks_all_but_voice(self) -> None:
        with patch.dict(ai_budget_service.DEFAULTS, {"company": {"dailyUsd": 0.05}}):
            self._record("09120000001", 0.03)
            self._record("09120000002", 0.02)
            with tenant_scope("09120000001"):
                self.assertEqual(ai_budget_service.cloud_blocked(surface="shop"), "company")
                self.assertIsNone(ai_budget_service.cloud_blocked(surface="voice"))

    def test_cloud_blocked_inbox_uses_local_only_hops(self) -> None:
        with patch.dict(ai_budget_service.DEFAULTS, {"company": {"dailyUsd": 0.01}}):
            self._record("09120000001", 0.02)
            with tenant_scope("09120000001"):
                hops = llm._inbox_hops("inbox")
        self.assertEqual(len(hops), 1)
        self.assertEqual(hops[0]["kind"], "local")

    def test_chat_completion_skips_cloud_when_capped(self) -> None:
        import asyncio

        with patch.dict(ai_budget_service.DEFAULTS, {"company": {"dailyUsd": 0.01}}):
            self._record("09120000001", 0.02)
            seen: dict = {}

            async def fake(route, **kwargs):
                seen["kind"] = route["kind"]
                return "ok"

            with (
                tenant_scope("09120000001"),
                patch.object(llm, "_complete_with_route", new=fake),
                patch.object(llm, "route_for_surface", return_value={"kind": "cloud", "url": "https://x", "model": "m", "token": "t"}),
            ):
                out = asyncio.run(llm._chat_completion(messages=[], temperature=0.1, max_tokens=8, surface="shop"))
        self.assertEqual(out, "ok")
        self.assertEqual(seen["kind"], "local")

    def test_report_hashes_tenants_and_groups_plans(self) -> None:
        with tenant_scope("09120000001"):
            plan_service.set_plan("pro")
        self._record("09120000001", 0.02)
        self._record("09120000002", 0.01)
        report = ai_budget_service.report()
        self.assertIn("pro", report["plans"])
        names = [row["tenant"] for row in report["topTenants"]]
        self.assertTrue(all(len(name) == 12 for name in names))
        self.assertNotIn("09120000001", str(report))

    def test_config_file_overrides_numbers_without_code(self) -> None:
        from app.state_store import write_json

        write_json("ai-budget.json", {"plans": {"pro": {"dailyUsd": 0.5, "weeklyUsd": 2.0}}}, shared=True)
        with tenant_scope("09120000001"):
            plan_service.set_plan("pro")
        row = ai_budget_service.tenant_status("09120000001")
        self.assertEqual(row["dailyCapUsd"], 0.5)
        self.assertEqual(row["weeklyCapUsd"], 2.0)


class CompanyCapDefaultTests(unittest.TestCase):
    def test_company_daily_cap_is_ten_dollars(self) -> None:
        self.assertEqual(ai_budget_service.DEFAULTS["company"]["dailyUsd"], 10.0)


if __name__ == "__main__":
    unittest.main()
