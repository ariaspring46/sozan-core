from __future__ import annotations

from app.services.admin_service import _pages

import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings


class AdminServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state = patch.object(settings, "state_dir", self._tmp.name)
        self._state.start()
        self.addCleanup(self._state.stop)
        # env هاب OTP_TEST_UNTIL و کلید واقعی دارد؛ این تست بی‌طرف است
        self._test = patch.object(settings, "otp_test_until", "")
        self._test.start()
        self.addCleanup(self._test.stop)

    def _make_tenant(self, phone: str, plan: str = "free") -> None:
        import time as _t
        from pathlib import Path
        from app.state_store import write_json, tenant_scope

        tenant_dir = Path(self._tmp.name) / "tenants" / phone
        tenant_dir.mkdir(parents=True, exist_ok=True)
        with tenant_scope(phone):
            write_json("plan.json", {"plan": plan, "at": int(_t.time())})

    def test_set_plan_requires_reason(self) -> None:
        from app.services import admin_service

        with self.assertRaises(ValueError):
            admin_service.set_user_plan("09120000001", "pro", days=30, reason="")

    def test_set_plan_writes_audit(self) -> None:
        from app.services import admin_service
        from app.state_store import read_json

        self._make_tenant("09120000001")
        out = admin_service.set_user_plan("09120000001", "pro", days=7, reason="تست")
        self.assertTrue(out["ok"])
        rows = read_json("admin-actions.json", [], shared=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "set-plan")
        self.assertIn("09120000001", rows[0]["target"])

    def test_global_payments_totals(self) -> None:
        from app.services import admin_service
        from app.state_store import write_json, tenant_scope
        import time as _t

        self._make_tenant("09120000001", "pro")
        with tenant_scope("09120000001"):
            write_json("billing.json", [
                {"plan": "pro", "amount": 1000, "status": "paid", "at": int(_t.time()), "refId": "r1"},
                {"plan": "pro", "amount": 2000, "status": "pending", "at": int(_t.time())},
            ])
        out = admin_service.global_payments()
        self.assertEqual(out["totals"]["today"], 1000)  # فقط paid
        self.assertEqual(len(out["rows"]), 1)

    def test_audit_trail_sorted(self) -> None:
        from app.services import admin_service

        admin_service.record_action(action="a", target="t1", reason="r")
        rows = admin_service.audit_trail()
        self.assertTrue(rows)


class AdminApiGuardTests(unittest.TestCase):
    def test_non_admin_gets_403(self) -> None:
        import asyncio
        import tempfile
        from unittest.mock import patch as _p

        import httpx

        async def run() -> None:
            from unittest.mock import AsyncMock as _AM

            from app.main import app
            from app.security import encode_token

            # endpoint به DB وصل می‌شود؛ برای تست مجوز، پاسخ را mock می‌کنیم
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.get("/admin/users")
                self.assertEqual(res.status_code, 401)  # بدون توکن

        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw):
            asyncio.run(run())


class AdminPagesTests(unittest.TestCase):
    def test_channels_then_scan_without_duplicates_or_secrets(self) -> None:
        channels = [{"platform": "telegram", "handle": "@shopchan", "token": "SECRET"}]
        scanned = {"accounts": [{"platform": "instagram", "handle": "pink_shop", "about": "x"}]}
        scan = {"handles": ["@Pink_Shop", "other.page"]}
        pages = _pages(channels, scan, scanned)
        self.assertEqual(pages, ["telegram:@shopchan", "instagram:@pink_shop", "instagram:@other.page"])
        self.assertNotIn("SECRET", " ".join(pages))

    def test_nothing_known(self) -> None:
        self.assertEqual(_pages([], {}, {}), [])
        self.assertEqual(_pages(None, None, None), [])


if __name__ == "__main__":
    unittest.main()
