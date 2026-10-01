import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import pay_service, shop_service, tenant_index_service as tix
from app.state_store import tenant_scope, write_json


class TenantIndexLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._state = patch.object(settings, "state_dir", self._tmp.name)
        self._state.start()
        self.addCleanup(self._state.stop)
        for i in range(5):
            with tenant_scope(f"0912111000{i}"):
                write_json("shop.json", {"slug": f"shop{i}"})

    def _count_scans(self):
        calls = {"n": 0}
        real = tix.scan_all

        def counting():
            calls["n"] += 1
            return real()

        return calls, patch.object(tix, "scan_all", counting)

    def test_unknown_slug_scans_at_most_once_per_gap(self) -> None:
        calls, counting = self._count_scans()
        with counting:
            for _ in range(20):
                self.assertIsNone(pay_service.find_tenant_by_slug("nobody-here"))
        self.assertEqual(calls["n"], 1)

    def test_known_slug_after_build_needs_no_scan(self) -> None:
        tix.build_all()
        calls, counting = self._count_scans()
        with counting:
            self.assertEqual(pay_service.find_tenant_by_slug("shop3"), "09121110003")
        self.assertEqual(calls["n"], 0)

    def test_new_shop_is_found_without_waiting_for_a_rescan(self) -> None:
        tix.build_all()  # the gap is now closed: a miss cannot rescan
        with tenant_scope("09121110099"):
            shop_service._save_shop({**shop_service.DEFAULT_SHOP, "slug": "brand-new"})
        self.assertEqual(pay_service.find_tenant_by_slug("brand-new"), "09121110099")

    def test_stale_row_is_verified_and_repaired(self) -> None:
        data = tix._empty()
        data["slug"]["shop1"] = "09121110004"  # wrong owner, index old enough to rescan
        tix._save(data)
        self.assertEqual(pay_service.find_tenant_by_slug("shop1"), "09121110001")
        self.assertEqual(tix.load()["slug"]["shop1"], "09121110001")

    def test_orders_are_indexed_on_create_and_found_by_index(self) -> None:
        tix.build_all()
        with tenant_scope("09121110002"):
            pay_service._append_order({"id": "ORD123", "phone": "09121110002", "status": "pending", "amount": 1000})
        calls, counting = self._count_scans()
        with counting:
            found = pay_service.locate_order("ORD123")
        self.assertEqual(calls["n"], 0)
        self.assertEqual(found[0], "09121110002")
        self.assertEqual(found[1]["id"], "ORD123")
        self.assertIsNone(pay_service.locate_order("missing-order"))

    def test_upsert_is_idempotent_and_survives_errors(self) -> None:
        tix.upsert(phone="09121110000", slug="shop0")
        before = tix.load()
        tix.upsert(phone="09121110000", slug="shop0")
        self.assertEqual(before, tix.load())
        tix.upsert(phone="", slug="x")  # ignored, no raise


if __name__ == "__main__":
    unittest.main()
