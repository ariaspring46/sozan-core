import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import channel_tool
from app.state_store import tenant_scope, write_json


def _page() -> None:
    write_json(
        "channels.json",
        [
            {
                "id": "ig",
                "platform": "instagram",
                "handle": "sozan_core",
                "credentials": {"sendboxAccountId": "sb-1"},
            }
        ],
    )
    write_json("sendbox-posts-error.json", {"accountId": "sb-1", "error": "access token expired"})
    write_json(
        "channel-scan.json",
        {
            "accounts": [
                {
                    "platform": "instagram",
                    "handle": "sozan_core",
                    "fetched": True,
                    "about": "جواهر فروشی با ویترین خلوت",
                    "categories": ["انگشتر"],
                    "colors": ["فیروزه"],
                    "images": ["ring.jpg"],
                    "products": [
                        {
                            "title": "انگشتر فیروزه",
                            "description": "انگشتر فیروزه دست‌ساز",
                            "sourceCaption": "انگشتر فیروزه دست‌ساز",
                        }
                    ],
                }
            ],
            "productCount": 1,
            "categories": ["انگشتر"],
            "colors": ["فیروزه"],
        },
    )


class ChannelReviewTests(unittest.TestCase):
    def test_a_downloaded_page_is_described_even_when_login_expired(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09130000001"):
                _page()
                text = channel_tool.result_sentence("instagram", "sozan_core")
        self.assertNotIn("منقضی", text)
        self.assertIn("انگشتر فیروزه", text)
        self.assertIn("@sozan_core", text)

    def test_login_error_stays_when_nothing_was_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09130000001"):
                _page()
                write_json(
                    "channel-scan.json",
                    {"accounts": [{"platform": "instagram", "handle": "sozan_core", "fetched": False, "products": []}]},
                )
                text = channel_tool.result_sentence("instagram", "sozan_core")
        self.assertIn("منقضی", text)

    def test_review_uses_the_downloaded_page(self) -> None:
        async def model(**kwargs):
            self.assertIn("جواهر فروشی", kwargs["turns"][0]["text"])
            return "پیج جواهر است و کپشن‌ها کوتاه‌اند."

        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09130000001"),
                patch("app.services.llm.complete_text_chat", new=model),
            ):
                _page()
                text = asyncio.run(channel_tool.review_sentence("instagram", "sozan_core"))
        self.assertEqual(text, "پیج جواهر است و کپشن‌ها کوتاه‌اند.")

    def test_review_falls_back_to_the_page_when_the_model_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09130000001"),
                patch("app.services.llm.complete_text_chat", new=AsyncMock(return_value=None)),
            ):
                _page()
                text = asyncio.run(channel_tool.review_sentence("instagram", "sozan_core"))
        self.assertIn("انگشتر فیروزه", text)
        self.assertNotIn("منقضی", text)

    def test_an_opinion_downloads_without_writing_the_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09130000001"),
                patch("app.services.channel_scan_service.start_scan", return_value={"status": "running"}) as scan,
            ):
                _page()
                text, _extra = asyncio.run(
                    channel_tool.run("برو پیج اینستاگرام من رو ببین و نظرتو بگو", {"action": "scan"})
                )
        self.assertIn("می‌خوانم", text)
        self.assertIn("@sozan_core", text)
        self.assertFalse(scan.call_args.kwargs["import_catalog"])
        pending = scan.call_args.kwargs["notify"]()
        self.assertTrue(asyncio.iscoroutine(pending))
        pending.close()

    def _scan(self, spoken: str, args: dict):
        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09130000001"),
                patch("app.services.channel_scan_service.start_scan", return_value={"status": "running"}) as own,
                patch("app.services.channel_scan_service.start_other_scan") as other,
            ):
                _page()
                text, _extra = asyncio.run(channel_tool.run(spoken, args))
        return text, own, other

    def test_someone_elses_page_is_only_read(self) -> None:
        # review 2026-10-09: a competitor's page was imported into the seller's catalog from a read tool
        text, own, other = self._scan("پیج rival_shop.ir رو ببین", {"action": "scan", "handle": "rival_shop"})
        self.assertFalse(own.called)
        self.assertTrue(other.called)
        self.assertEqual(other.call_args.args[0], [{"platform": "instagram", "handle": "rival_shop"}])
        self.assertIn("پیج خودت نیست", text)

    def test_the_connected_page_still_fills_the_catalog(self) -> None:
        _text, own, other = self._scan("پیج sozan_core رو ببین", {"action": "scan", "handle": "sozan_core"})
        self.assertFalse(other.called)
        self.assertTrue(own.call_args.kwargs["import_catalog"])

    def test_a_page_the_seller_calls_theirs_is_theirs(self) -> None:
        _text, own, other = self._scan("پیج من new_page_2 رو بخون", {"action": "scan", "handle": "new_page_2"})
        self.assertFalse(other.called)
        self.assertTrue(own.called)


class OtherPageScanTests(unittest.TestCase):
    def test_other_page_never_touches_the_seller_files(self) -> None:
        from app.services import channel_scan_service
        from app.state_store import read_json

        page = {
            "platform": "instagram",
            "handle": "rival_shop",
            "fetched": True,
            "about": "بیو رقیب",
            "products": [{"title": "کیف چرم", "price": 900000, "image": "x.jpg", "stableKey": "k1"}],
        }

        async def fake_fetch(**_kw):
            return dict(page)

        with tempfile.TemporaryDirectory() as raw:
            with (
                patch.object(settings, "state_dir", raw),
                tenant_scope("09130000001"),
                patch.object(channel_scan_service, "scan_account", new=fake_fetch),
                patch.object(channel_scan_service.voice_service, "merge_summary") as merged,
                patch.object(channel_scan_service.storefront_service, "remove_scanned_handle") as removed,
            ):
                _page()
                before = read_json("channel-scan.json", {})
                asyncio.run(channel_scan_service.scan_accounts([{"platform": "instagram", "handle": "rival_shop"}], own=False))
                after = read_json("channel-scan.json", {})
                products = read_json("products.json", [])
                kept = read_json(channel_scan_service.OTHER_SCAN_FILE, {})
                view = channel_scan_service.page_view("instagram", "rival_shop")
        self.assertEqual(before, after)
        self.assertFalse(merged.called)
        self.assertFalse(removed.called)
        self.assertEqual(products, [])
        self.assertEqual([item.get("handle") for item in kept.get("accounts") or []], ["rival_shop"])
        self.assertTrue(view.get("fetched"))
