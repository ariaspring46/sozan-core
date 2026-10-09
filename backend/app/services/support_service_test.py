import asyncio
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import support_service
from app.state_store import read_json, tenant_scope, write_json


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

    def test_seller_categories_and_a_missing_one_reads_as_other(self) -> None:
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), patch("threading.Thread"):
            with tenant_scope("09121110001"):
                for category in support_service.TICKET_CATEGORIES:
                    support_service.create_ticket(subject=category, text="متن تیکت", kind="seller", category=category)
                support_service.create_ticket(subject="بی‌دسته", text="متن تیکت", kind="seller")
                write_json(
                    "support-tickets.json",
                    _tickets_plus_old(),
                )
                listed = {row["subject"]: row["category"] for row in support_service.list_tickets(kind="seller")}
                on_disk = read_json("support-tickets.json", [])
        self.assertEqual(listed["billing"], "billing")
        self.assertEqual(listed["technical"], "technical")
        self.assertEqual(listed["other"], "other")
        self.assertEqual(listed["بی‌دسته"], "other")
        self.assertEqual(listed["قدیمی"], "other")
        old = next(row for row in on_disk if row["subject"] == "قدیمی")
        self.assertNotIn("category", old)

    def test_an_invalid_seller_category_is_refused(self) -> None:
        with tenant_scope("09121110001"):
            with self.assertRaises(ValueError):
                support_service.create_ticket(subject="بد", text="متن تیکت", kind="seller", category="spam")
            self.assertEqual(support_service.list_tickets(kind="seller"), [])

    def test_hub_list_keeps_the_category_and_skips_the_storefront(self) -> None:
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), patch("threading.Thread"):
            self._file_category("09121110001", "billing")
            with tenant_scope("09121110001"):
                support_service.create_ticket(subject="ویترین", text="متن تیکت", kind="storefront")
        with tenant_scope("09129990000"):
            rows = support_service.list_all_tickets_for_hub_admin()
        self.assertEqual([row["category"] for row in rows], ["billing"])
        self.assertEqual(rows[0]["subject"], "مالی")

    def test_create_and_reply_at_once_both_stay(self) -> None:
        phone = "09121110001"
        with patch("asyncio.get_running_loop", side_effect=RuntimeError), patch(
            "app.services.telegram_alert_service.seller_ticket_alert", new=AsyncMock()
        ), patch("app.services.observe_client.emit_later"):
            with tenant_scope(phone):
                existing = support_service.create_ticket(
                    subject="قبلی", text="متن تیکت", kind="seller", category="billing"
                )["ticketId"]
            barrier = threading.Barrier(2)
            errors: list[BaseException] = []

            def creator() -> None:
                try:
                    with tenant_scope(phone):
                        barrier.wait(timeout=2)
                        support_service.create_ticket(subject="تازه", text="متن تازه", kind="seller", category="technical")
                except BaseException as exc:
                    errors.append(exc)

            def replier() -> None:
                try:
                    with tenant_scope(phone):
                        barrier.wait(timeout=2)
                        support_service.reply_ticket(existing, text="جواب همزمان", status="working", by="support")
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=creator), threading.Thread(target=replier)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            time.sleep(0.2)
        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        with tenant_scope(phone):
            rows = support_service.list_tickets(kind="seller")
        self.assertEqual({row["subject"] for row in rows}, {"قبلی", "تازه"})
        previous = next(row for row in rows if row["id"] == existing)
        self.assertEqual(previous["replies"][0]["text"], "جواب همزمان")
        self.assertEqual(previous["status"], "working")

    def test_alert_names_the_category_and_the_admin_tab(self) -> None:
        from app.services import telegram_alert_service

        seen: dict[str, str] = {}

        async def fake_send(text: str) -> bool:
            seen["text"] = text
            return True

        with patch.object(telegram_alert_service, "send", fake_send):
            asyncio.run(telegram_alert_service.seller_ticket_alert("abc", "موضوع", "09121110001", "billing"))
        self.assertIn("دسته: مالی", seen["text"])
        self.assertIn("تیکت‌ها", seen["text"])
        self.assertIn("/admin", seen["text"])
        self.assertIn("0912***", seen["text"])
        self.assertNotIn("پشتیبانی و رسیدها", seen["text"])

    def _file_category(self, phone: str, category: str) -> str:
        with tenant_scope(phone):
            return support_service.create_ticket(
                subject="مالی" if category == "billing" else category,
                text="متن تیکت",
                kind="seller",
                category=category,
            )["ticketId"]


def _tickets_plus_old() -> list:
    rows = read_json("support-tickets.json", [])
    rows.append(
        {
            "id": "old-ticket",
            "subject": "قدیمی",
            "text": "بدون دسته",
            "kind": "seller",
            "status": "open",
            "replies": [],
            "at": 1,
        }
    )
    return rows


if __name__ == "__main__":
    unittest.main()
