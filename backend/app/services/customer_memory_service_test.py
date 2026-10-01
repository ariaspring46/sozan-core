import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import customer_memory_service, inbox_agent_service, storefront_service
from app.state_store import tenant_scope


class CustomerMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_remember_keeps_only_masked_shop_facts(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)):
            saved = customer_memory_service.remember(
                {"sender": "علی ۰۹۱۲۱۲۳۴۵۶۷"},
                "سایز ۳۸ می‌خوام، آدرس خیابان ولیعصر پلاک ۵، مانتو کرپ برداشتید",
            )
            snap = customer_memory_service.snapshot()
        self.assertTrue(saved)
        self.assertEqual(snap["customers"], 1)
        self.assertGreaterEqual(snap["facts"], 1)
        raw = (self.root / "tenants" / "09120001111" / "customer-memory.json").read_text(encoding="utf-8")
        self.assertNotIn("ولیعصر", raw)
        self.assertNotIn("09121234567", raw)
        self.assertIn("سایز", raw)

    def test_plain_greeting_records_nothing(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)):
            saved = customer_memory_service.remember({"sender": "مریم"}, "سلام خوبید")
            self.assertEqual(customer_memory_service.snapshot()["customers"], 0)
        self.assertFalse(saved)

    def test_voice_and_consent_off_record_nothing(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.settings_service.get_settings", lambda: {"sozanImprove": False}
        ):
            self.assertFalse(customer_memory_service.remember({"sender": "علی"}, "سایز ۴۰ دارید؟"))

    def test_block_is_injected_and_hashkeyed_per_sender(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)):
            customer_memory_service.remember({"sender": "علی"}, "سایز ۳۸ برداشتید")
            block = customer_memory_service._prompt_block({"sender": "علی"})
            other = customer_memory_service._prompt_block({"sender": "مریم"})
        self.assertIn("سایز 38", block)
        self.assertIn("حافظهٔ مشتری", block)
        self.assertEqual(other, "")
        self.assertNotIn("علی", block)

    def test_agent_remembers_real_turns_only_and_never_voice(self) -> None:
        async def forbidden(**_kwargs):
            raise AssertionError("model")

        import asyncio

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", forbidden):
            storefront_service.add_product(title="مانتو کرپ", price=1000000, stock=4, sku="m1")
            asyncio.run(
                inbox_agent_service.answer("سایز ۳۸ مانتو کرپ هست؟", thread={"sender": "علی"}, source="real")
            )
            asyncio.run(
                inbox_agent_service.answer("سایز ۴۰ مانتو کرپ هست؟", thread={"sender": "علی"}, source="voice")
            )
            snap = customer_memory_service.snapshot()
        self.assertEqual(snap["customers"], 1)
        self.assertEqual(snap["facts"], 1)

    def test_inbox_auto_reply_path_records_memory(self) -> None:
        """The production DM path (draft_reply) is a real turn, not the phone line."""
        async def forbidden(**_kwargs):
            raise AssertionError("model")

        import asyncio

        from app.services import voice_service

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)), patch(
            "app.services.inbox_agent_service.emit_later"
        ), patch("app.services.inbox_agent_service.complete_tools", forbidden):
            storefront_service.add_product(title="مانتو کرپ", price=1000000, stock=4, sku="m1")
            asyncio.run(voice_service.draft_reply("سایز ۳۸ مانتو کرپ هست؟", thread={"sender": "علی"}))
            snap = customer_memory_service.snapshot()
        self.assertEqual(snap["customers"], 1)

    def test_forget_removes_the_customer(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(self.root)):
            customer_memory_service.remember({"sender": "علی"}, "سایز ۳۸ برداشتید")
            self.assertTrue(customer_memory_service.forget("علی"))
            self.assertEqual(customer_memory_service.snapshot()["customers"], 0)


if __name__ == "__main__":
    unittest.main()
