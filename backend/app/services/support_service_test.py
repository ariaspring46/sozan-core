import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import support_service
from app.state_store import tenant_scope


class HubTicketTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(settings, "state_dir", self._tmp.name)
        self._patch.start()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._patch.stop)

    def _file(self, phone: str, kind: str, subject: str) -> str:
        with tenant_scope(phone):
            return support_service.create_ticket(subject=subject, text="متن تیکت", kind=kind)["ticketId"]

    def test_hub_admin_sees_seller_tickets_of_every_tenant(self) -> None:
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), patch("threading.Thread"):
            first = self._file("09121110001", "seller", "مشکل یک")
            second = self._file("09121110002", "seller", "مشکل دو")
            self._file("09121110002", "storefront", "تیکت مشتری ویترین")
        with tenant_scope("09129990000"):
            rows = support_service.list_all_tickets_for_hub_admin()
        self.assertEqual({row["id"] for row in rows}, {first, second})
        self.assertEqual({row["tenant"] for row in rows}, {"09121110001", "09121110002"})

    def test_hub_reply_lands_in_the_sellers_own_file(self) -> None:
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), patch("threading.Thread"):
            ident = self._file("09121110001", "seller", "کمک")
        with tenant_scope("09129990000"):
            out = support_service.reply_hub_ticket(ident, text="رسیدگی شد", status="closed")
        self.assertEqual(out["tenant"], "09121110001")
        with tenant_scope("09121110001"):
            mine = support_service.list_tickets(kind="seller")
        self.assertEqual(mine[0]["status"], "closed")
        self.assertEqual(mine[0]["replies"][0]["by"], "support")

    def test_hub_reply_unknown_ticket_fails(self) -> None:
        with self.assertRaises(ValueError):
            support_service.reply_hub_ticket("nope", text="x")

    def test_storefront_list_hides_seller_tickets(self) -> None:
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), patch("threading.Thread"):
            self._file("09121110001", "seller", "به سوزان")
            self._file("09121110001", "storefront", "از مشتری")
        with tenant_scope("09121110001"):
            rows = support_service.list_tickets(kind="storefront")
        self.assertEqual([row["subject"] for row in rows], ["از مشتری"])


if __name__ == "__main__":
    unittest.main()
