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
