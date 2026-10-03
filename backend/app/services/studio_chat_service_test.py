import asyncio
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services import studio_chat_service


@contextmanager
def _nolock(_name: str = "studio"):
    yield



_VOICE_PATCHES: list = []


def setUpModule() -> None:
    # The assistant's own voice (shop_voice_service) asks the cloud model; tests that are not about it take the plain fallbacks.
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE_PATCHES.append(started)


def tearDownModule() -> None:
    while _VOICE_PATCHES:
        _VOICE_PATCHES.pop().stop()

class FakeCampaigns:
    def __init__(self) -> None:
        self.created = 0
        self.raw: list[str] = []
        self.composed = 0
        self.last_id = uuid4()
        self.outputs: list[dict] = []
        self.kwargs: dict = {}

    async def create(self, **kwargs):
        self.created += 1
        self.kwargs = kwargs
        return SimpleNamespace(id=self.last_id)

    async def save_raw(self, campaign_id, filename, data):
        self.raw.append(filename)
        return SimpleNamespace(id=uuid4())

    async def compose(self, campaign_id):
        self.composed += 1
        return SimpleNamespace(id=campaign_id)

    async def preview_outputs(self, campaign_id):
        return self.outputs

    async def update_copy(self, campaign_id, **kwargs):
        return SimpleNamespace(id=campaign_id)


class StudioChatTests(unittest.TestCase):
    def _patches(self, root: Path, rows=None):
        stored = {"rows": list(rows or [])}

        def reader(name, default=None):
            return list(stored["rows"])

        def writer(name, payload):
            stored["rows"] = list(payload)

        return (
            patch("app.services.studio_chat_service.read_json", side_effect=reader),
            patch("app.services.studio_chat_service.write_json", side_effect=writer),
            patch("app.services.studio_chat_service.emit_later"),
            patch("app.services.studio_chat_service.tenant_file_lock", _nolock),
            patch("app.state_store.tenant_dir", return_value=root),
        )

    def test_greeting_skips_campaign(self) -> None:
        campaigns = FakeCampaigns()
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = asyncio.run(studio_chat_service.chat("سلام", campaigns))
        self.assertEqual(campaigns.created, 0)
        self.assertEqual(result["campaignId"], "")
        self.assertIn("اینستاگرام", result["messages"][-1]["text"])
        self.assertNotIn("attachments", result["messages"][-1])

    def test_greeting_variants(self) -> None:
        self.assertTrue(studio_chat_service._is_greeting("سلام خوبی؟"))
        self.assertTrue(studio_chat_service._is_greeting("سلام، چطوری"))
        self.assertFalse(studio_chat_service._is_greeting("پست اینستاگرام بساز"))

    def test_formal_revision_does_not_start_a_new_image(self) -> None:
        campaigns = FakeCampaigns()
        prior = [
            {
                "id": "old",
                "role": "assistant",
                "text": "پست آماده شد.",
                "campaignId": "c-old",
                "captions": {"instagram": "کپشن", "telegram": "کپشن", "whatsapp": "کپشن"},
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw), prior)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(return_value={"reply": "کپشن رسمی‌تر شد.", "instagram": "کپشن رسمی", "telegram": "کپشن رسمی", "whatsapp": "کپشن رسمی"}),
            ), patch("app.services.studio_compose_service.start") as started, patch(
                "app.services.image_provider_service.generate_still"
            ) as still:
                result = asyncio.run(studio_chat_service.chat("رسمی‌تر کن", campaigns))
        started.assert_not_called()
        still.assert_not_called()
        self.assertEqual(campaigns.created, 0)
        self.assertIn("رسمی", result["messages"][-1]["text"])

    def test_image_starts_background_compose(self) -> None:
        campaigns = FakeCampaigns()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media_dir = root / "chat-media"
            media_dir.mkdir()
            still = media_dir / "pic-image.png"
            still.write_bytes(b"png")
            patches = self._patches(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "reply": "کپشن آماده شد.",
                        "title": "ویترین شب",
                        "subtitle": "",
                        "cta": "ببین",
                        "instagram": "کپشن اینستا",
                        "telegram": "کپشن تلگرام",
                        "whatsapp": "پیام واتساپ",
                        "compose": False,
                        "imagePrompt": "a shop window, no text",
                    }
                ),
            ), patch("app.services.chat_media_service.tenant_dir", return_value=root), patch(
                "app.services.studio_compose_service.start", return_value="job-1"
            ) as started:
                result = asyncio.run(
                    studio_chat_service.chat(
                        "پست اینستاگرام بساز",
                        campaigns,
                        {"kind": "image", "name": still.name},
                    )
                )
        self.assertEqual(campaigns.created, 1)
        self.assertEqual(campaigns.composed, 0)
        self.assertEqual(campaigns.kwargs.get("whatsapp_caption"), "پیام واتساپ.")
        self.assertTrue(started.called)
        assistant = result["messages"][-1]
        self.assertEqual(assistant["captions"]["whatsapp"], "پیام واتساپ.")
        self.assertIn("در حال ساخت", assistant["text"])

    def test_llm_error_emits_failed(self) -> None:
        campaigns = FakeCampaigns()
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2] as emit, patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(return_value={"error": "llm_unreachable", "reply": "مدل پاسخ نداد. پیام را دوباره بفرست."}),
            ):
                result = asyncio.run(studio_chat_service.chat("پست بساز", campaigns))
        self.assertEqual(campaigns.created, 0)
        self.assertTrue(result["messages"][-1]["text"])
        failed = [call for call in emit.call_args_list if (call.kwargs or {}).get("status") == "failed"]
        self.assertTrue(failed)

    def test_mark_published_and_regenerate_caption(self) -> None:
        campaigns = FakeCampaigns()
        message_id = str(uuid4())
        rows = [
            {
                "id": message_id,
                "role": "assistant",
                "text": "کپشن آماده شد.",
                "campaignId": str(campaigns.last_id),
                "captions": {"instagram": "قدیمی", "telegram": "تلگرام", "whatsapp": "واتساپ"},
                "attachments": [{"kind": "image", "name": "pic-image.png"}],
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw), rows)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={"reply": "تازه", "instagram": "اینستا تازه", "telegram": "تلگرام تازه", "whatsapp": "واتساپ تازه"}
                ),
            ):
                marked = studio_chat_service.mark_published(message_id, "telegram")
                self.assertTrue(marked["messages"][0]["published"]["telegram"])
                result = asyncio.run(
                    studio_chat_service.regenerate(message_id=message_id, part="caption", campaigns=campaigns)
                )
        self.assertEqual(result["messages"][0]["captions"]["instagram"], "اینستا تازه.")

    def test_question_without_captions_skips_campaign(self) -> None:
        campaigns = FakeCampaigns()
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "reply": "چه محصولی؟",
                        "title": "",
                        "instagram": "",
                        "telegram": "",
                        "whatsapp": "",
                        "compose": False,
                    }
                ),
            ), patch("app.services.studio_compose_service.start") as started:
                result = asyncio.run(studio_chat_service.chat("پست بساز", campaigns))
        self.assertEqual(campaigns.created, 0)
        started.assert_not_called()
        self.assertEqual(result["campaignId"], "")
        self.assertEqual(result["messages"][-1]["text"], "چه محصولی؟")

    def test_stub_schema_reply_uses_caption(self) -> None:
        campaigns = FakeCampaigns()
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "reply": "متن فارسی",
                        "title": "تیتر کوتاه",
                        "instagram": "ویترین امشب با نور نرم آماده است.",
                        "telegram": "ویترین امشب باز است.",
                        "whatsapp": "ویترین آماده‌ست.",
                        "compose": True,
                        "imagePrompt": "shop window still, no text",
                    }
                ),
            ), patch("app.services.studio_compose_service.start", return_value="job-1"):
                result = asyncio.run(studio_chat_service.chat("پست اینستاگرام بساز", campaigns))
        self.assertEqual(campaigns.created, 1)
        self.assertNotIn("متن فارسی", result["messages"][-1]["text"])
        self.assertIn("ویترین", result["messages"][-1]["text"])
        self.assertEqual(campaigns.kwargs.get("title"), "")
        self.assertEqual(campaigns.kwargs.get("cta"), "")

    def test_campaign_create_failure_emits(self) -> None:
        campaigns = FakeCampaigns()
        campaigns.create = AsyncMock(side_effect=RuntimeError("db"))
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2] as emit, patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "reply": "کپشن آماده شد.",
                        "title": "ویترین",
                        "instagram": "کپشن اینستا",
                        "telegram": "تلگرام",
                        "whatsapp": "واتساپ",
                        "compose": True,
                    }
                ),
            ), patch("app.services.studio_compose_service.start") as started:
                result = asyncio.run(studio_chat_service.chat("پست بساز", campaigns))
        started.assert_not_called()
        titles = [(call.kwargs or {}).get("title") for call in emit.call_args_list]
        self.assertIn("campaign-create-failed", titles)
        self.assertEqual(result["campaignId"], "")

    def test_caption_regen_llm_error_raises(self) -> None:
        campaigns = FakeCampaigns()
        message_id = str(uuid4())
        rows = [
            {
                "id": message_id,
                "role": "assistant",
                "text": "کپشن آماده شد.",
                "campaignId": str(campaigns.last_id),
                "captions": {"instagram": "قدیمی", "telegram": "تلگرام", "whatsapp": "واتساپ"},
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw), rows)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(return_value={"error": "llm_unreachable", "reply": "مدل کپشن تازه نداد."}),
            ):
                with self.assertRaises(ValueError):
                    asyncio.run(studio_chat_service.regenerate(message_id=message_id, part="caption", campaigns=campaigns))

    def test_mark_published_lock_serialises(self) -> None:
        import threading

        message_id = str(uuid4())
        stored = {
            "rows": [
                {"id": message_id, "role": "assistant", "text": "x", "published": {}},
            ]
        }

        def reader(name, default=None):
            return list(stored["rows"])

        def writer(name, payload):
            stored["rows"] = list(payload)

        with tempfile.TemporaryDirectory() as raw:
            with patch("app.services.studio_chat_service.read_json", side_effect=reader), patch(
                "app.services.studio_chat_service.write_json", side_effect=writer
            ), patch("app.services.studio_chat_service.emit_later"), patch(
                "app.services.tenant_lock.tenant_dir", return_value=Path(raw)
            ), patch("app.services.tenant_lock.current_tenant", return_value="09120001111"):
                errors = []

                def ig():
                    try:
                        studio_chat_service.mark_published(message_id, "instagram")
                    except Exception as exc:
                        errors.append(exc)

                def tg():
                    try:
                        studio_chat_service.mark_published(message_id, "telegram")
                    except Exception as exc:
                        errors.append(exc)

                a = threading.Thread(target=ig)
                b = threading.Thread(target=tg)
                a.start()
                b.start()
                a.join()
                b.join()
                self.assertFalse(errors)
                published = stored["rows"][0].get("published") or {}
                self.assertIn("instagram", published)
                self.assertIn("telegram", published)

    def test_content_library_keeps_full_copy_and_asset_name(self) -> None:
        body = "کپشن کامل " * 40
        campaign = SimpleNamespace(
            id="c1",
            title="ویترین شب",
            copies=[SimpleNamespace(channel="instagram", body=body)],
            assets=[
                SimpleNamespace(kind="overlay", channel="instagram", format="feed", rel_path="c1/out/ig-feed.png")
            ],
        )
        rows = [
            {"id": "m1", "role": "assistant", "campaignId": "c1", "compose": {"status": "ready"}},
            {"id": "m2", "role": "assistant", "captions": {"telegram": "پیش‌نویس تلگرام"}},
        ]
        with patch("app.services.studio_chat_service.expire_stale_compose"), patch(
            "app.services.studio_chat_service.read_json",
            return_value=rows,
        ):
            out = studio_chat_service.content_library([campaign])
        self.assertEqual(out["items"][0]["copies"][0]["body"], body)
        self.assertEqual(out["items"][0]["assets"][0]["name"], "ig-feed.png")
        self.assertEqual(out["items"][0]["compose"], "ready")
        self.assertEqual(out["drafts"][0]["title"], "پیش‌نویس")
        self.assertEqual(out["drafts"][0]["copies"][0]["body"], "پیش‌نویس تلگرام")

    def test_bad_json_retries_once_and_keeps_the_campaign(self) -> None:
        campaigns = FakeCampaigns()
        long_ask = "برای کفش چرم مشکی لوکس یک پست بلند اینستاگرام و تلگرام و واتساپ بنویس " * 8
        first = {"error": "llm_bad_json", "reply": "مدل پاسخ خوانا نداد. پیام را کوتاه‌تر دوباره بفرست."}
        second = {
            "reply": "کپشن‌ها آماده شد.",
            "title": "چرم شب",
            "instagram": "کپشن اینستاگرام برای ویترین چرم",
            "telegram": "کپشن تلگرام",
            "whatsapp": "پیام واتساپ",
            "compose": False,
            "imagePrompt": "a black leather shoe on a plain background, no text",
        }
        async def complete(*_args, **_kwargs):
            complete.n += 1
            if complete.n == 1:
                return first
            return second

        complete.n = 0
        completer = AsyncMock(side_effect=complete)
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=completer,
            ):
                result = asyncio.run(studio_chat_service.chat(long_ask, campaigns))
        self.assertGreaterEqual(completer.await_count, 2)
        self.assertGreaterEqual(completer.await_args_list[0].kwargs["max_tokens"], 1600)
        self.assertGreater(completer.await_args_list[1].kwargs["max_tokens"], completer.await_args_list[0].kwargs["max_tokens"])
        self.assertEqual(campaigns.created, 1)
        self.assertNotIn("خوانا نداد", result["messages"][-1]["text"])
        self.assertEqual(result["messages"][-1]["captions"]["instagram"], "کپشن اینستاگرام برای ویترین چرم.")

    def test_content_library_shows_message_missing_from_campaign_list(self) -> None:
        rows = [
            {
                "id": "m1",
                "role": "assistant",
                "campaignId": "gone",
                "text": "کپشن آماده شد.",
                "captions": {"instagram": "کپشن اینستاگرام", "telegram": "تلگرام", "whatsapp": "واتساپ"},
                "attachments": [{"kind": "image", "name": "still-image.png"}],
                "compose": {"status": "ready"},
            }
        ]
        with patch("app.services.studio_chat_service.expire_stale_compose"), patch(
            "app.services.studio_chat_service.read_json",
            return_value=rows,
        ):
            out = studio_chat_service.content_library([])
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["id"], "gone")
        self.assertEqual(out["items"][0]["compose"], "ready")
        self.assertEqual(out["items"][0]["copies"][0]["body"], "کپشن اینستاگرام")
        self.assertEqual(out["items"][0]["assets"][0]["name"], "still-image.png")
        self.assertEqual(out["drafts"], [])

    def test_content_library_items_carry_the_time_they_were_last_touched(self) -> None:
        rows = [
            {"id": "m1", "role": "assistant", "campaignId": "c1", "text": "اول", "at": 1000, "captions": {"instagram": "الف"}},
            {"id": "m2", "role": "assistant", "campaignId": "c1", "text": "دوم", "at": 2500, "captions": {"instagram": "ب"}},
            {"id": "m3", "role": "assistant", "campaignId": "c2", "text": "سوم", "at": 1800, "captions": {"instagram": "ج"}},
        ]
        with patch("app.services.studio_chat_service.expire_stale_compose"), patch(
            "app.services.studio_chat_service.read_json",
            return_value=rows,
        ):
            out = studio_chat_service.content_library([])
        times = {item["id"]: item["at"] for item in out["items"]}
        self.assertEqual(times, {"c1": 2500, "c2": 1800})

    def test_content_library_empty(self) -> None:
        with patch("app.services.studio_chat_service.expire_stale_compose"), patch(
            "app.services.studio_chat_service.read_json",
            return_value=[],
        ):
            out = studio_chat_service.content_library([])
        self.assertEqual(out, {"items": [], "drafts": []})

    def test_latin_hashtags_leave_captions(self) -> None:
        out = studio_chat_service._clip_captions(
            {
                "instagram": "انگشتر فیروزه #TurquoiseRing #HandmadeJewelry",
                "telegram": "انگشتر فیروزه",
                "whatsapp": "سلام",
            }
        )
        self.assertEqual(out["instagram"], "انگشتر فیروزه.")
        self.assertNotIn("#", out["instagram"])
        bare = studio_chat_service._clip_captions(
            {
                "instagram": "گردنبند فیروزه با زنجیر نقره‌ای و نقره خالص TurquoiseNecklace",
                "telegram": "سلام",
                "whatsapp": "سلام",
            },
            spoken="برای گردنبند فیروزه با زنجیر نقره‌ای یک پست بساز",
            drop_unclaimed=True,
        )
        self.assertNotIn("Turquoise", bare["instagram"])
        self.assertNotIn("خالص", bare["instagram"])
        self.assertIn("نقره‌ای", bare["instagram"])
        kept_info = studio_chat_service._clip_captions(
            {"instagram": "برای خرید و اطلاعات بیشتر سر بزنید", "telegram": "سلام", "whatsapp": "سلام"},
            spoken="یک پست بساز",
            drop_unclaimed=True,
        )
        self.assertIn("اطلاعات", kept_info["instagram"])

    def test_catalog_skips_test_titles(self) -> None:
        self.assertEqual(studio_chat_service._catalog_title("Winter is coming…"), "")
        self.assertEqual(studio_chat_service._catalog_title("سلام! 👋 این یک پست آزمایشی"), "")
        self.assertEqual(studio_chat_service._catalog_title("آویز فیروزه"), "آویز فیروزه")
        self.assertEqual(studio_chat_service._title_from_spoken("برای انگشتر فیروزه یک پست اینستاگرام بساز"), "انگشتر فیروزه")
        self.assertEqual(
            studio_chat_service._overlay_title("پست اینستاگرام گردنبند فیروزه", "برای گردنبند فیروزه یک پست بساز"),
            "گردنبند فیروزه",
        )
        self.assertTrue(studio_chat_service._revises_caption("کپشن قبلی را رسمی‌تر کن"))
        self.assertFalse(studio_chat_service._revises_caption("عکس انگشتر فیروزه بساز"))

    def test_unclaimed_handmade_is_removed(self) -> None:
        kept = studio_chat_service._clip_captions(
            {"instagram": "آویز فیروزه دست‌ساز سوزان", "telegram": "سلام", "whatsapp": "سلام"},
            spoken="برای آویز فیروزه یک پست بساز",
            drop_unclaimed=True,
        )
        self.assertNotIn("دست", kept["instagram"])
        claimed = studio_chat_service._clip_captions(
            {"instagram": "آویز دست‌ساز", "telegram": "سلام", "whatsapp": "سلام"},
            spoken="بنویس دست‌ساز است",
            drop_unclaimed=True,
        )
        self.assertIn("دست‌ساز", claimed["instagram"])

    def test_the_sellers_own_caption_is_saved_as_typed(self) -> None:
        typed = "گردنبند فیروزه ✨\nارسال رایگان برای مشهد، ضمانت اصالت\n\nBrand: Zara-style\n#فیروزه #Mashhad"
        out = studio_chat_service._seller_captions({"instagram": typed, "telegram": typed + "\r\n\r\n\r\n", "whatsapp": ""})
        self.assertEqual(out["instagram"], typed)
        self.assertIn("ارسال رایگان", out["telegram"])
        self.assertIn("#Mashhad", out["telegram"])
        self.assertNotIn("\r", out["telegram"])
        self.assertEqual(out["whatsapp"], "")
        long = studio_chat_service._seller_captions({"instagram": "الف" * 5000, "telegram": "", "whatsapp": ""})
        self.assertEqual(len(long["instagram"]), studio_chat_service.CAPTION_LIMITS["instagram"])

    def test_model_text_is_still_guarded_but_marketing_words_stay(self) -> None:
        out = studio_chat_service._clip_captions(
            {"instagram": "کیفیت بالا و ارسال رایگان برای همه", "telegram": "سلام", "whatsapp": "سلام"},
            spoken="یک پست بساز",
            drop_unclaimed=True,
        )
        self.assertIn("کیفیت بالا", out["instagram"])
        self.assertNotIn("ارسال رایگان", out["instagram"])

    def test_no_text_on_photo_clears_overlay(self) -> None:
        self.assertTrue(studio_chat_service._no_overlay_text("عکس انگشتر بساز؛ روی عکس هیچ نوشته‌ای نباشد"))

    def test_image_prompt_uses_spoken_product(self) -> None:
        prompt = studio_chat_service._image_prompt(
            {"imagePrompt": "product photo of a turquoise pendant"},
            "برای گردنبند فیروزه یک پست بساز",
        )
        self.assertIn("turquoise pendant", prompt)
        self.assertNotIn("گردنبند", prompt)

    def test_caption_rewrite_applies_instruction_without_compose(self) -> None:
        campaigns = FakeCampaigns()
        rows = [
            {
                "id": "s1",
                "role": "assistant",
                "text": "قدیمی",
                "campaignId": str(campaigns.last_id),
                "captions": {"instagram": "کپشن اول", "telegram": "تلگرام", "whatsapp": "واتساپ"},
            },
            {
                "id": "hold",
                "role": "assistant",
                "text": "در حال ساخت.",
                "compose": {"status": "running", "jobId": "hold"},
            },
        ]
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw), rows)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "reply": "کپشن رسمی شد.",
                        "instagram": "گردنبند فیروزه با زنجیر نقره‌ای.",
                        "telegram": "گردنبند فیروزه.",
                        "whatsapp": "گردنبند فیروزه.",
                        "compose": False,
                    }
                ),
            ), patch("app.services.studio_compose_service.start") as started:
                result = asyncio.run(
                    studio_chat_service.chat("کپشن قبلی را رسمی‌تر کن", campaigns, into_id="hold")
                )
        started.assert_not_called()
        self.assertEqual(campaigns.created, 0)
        assistant = next(row for row in result["messages"] if row.get("id") == "s1")
        self.assertIn("نقره‌ای", assistant["captions"]["instagram"])
        self.assertNotIn("در حال ساخت", assistant["text"])
        placeholder = next(row for row in result["messages"] if row.get("id") == "hold")
        self.assertIn("نقره‌ای", placeholder["captions"]["instagram"])
        self.assertEqual(placeholder["compose"]["status"], "done")
        self.assertNotEqual(placeholder["text"], "در حال ساخت.")

    def test_recorded_model_sentence_drops_unclaimed_claims(self) -> None:
        sample = json.loads(
            (Path(__file__).resolve().parent / "fixtures" / "studio_model_samples.json").read_text(encoding="utf-8")
        )[0]
        out = studio_chat_service._clip_captions(
            {"instagram": sample["instagram"], "telegram": "سلام", "whatsapp": "سلام"},
            spoken=sample["spoken"],
            drop_unclaimed=True,
        )
        for word in sample["absent"]:
            self.assertNotIn(word, out["instagram"])
        for word in sample["present"]:
            self.assertIn(word, out["instagram"])

    def test_regenerate_image_keeps_prompt(self) -> None:
        campaigns = FakeCampaigns()
        message_id = str(uuid4())
        rows = [
            {
                "id": message_id,
                "role": "assistant",
                "text": "پست",
                "campaignId": str(campaigns.last_id),
                "imagePrompt": "product photo of a turquoise ring, studio light, no text, no logos, no people",
                "captions": {"instagram": "انگشتر", "telegram": "انگشتر", "whatsapp": "انگشتر"},
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw), rows)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_compose_service.start", return_value="job"
            ) as started:
                asyncio.run(studio_chat_service.regenerate(message_id=message_id, part="image", campaigns=campaigns))
        self.assertIn("turquoise ring", started.call_args.kwargs["image_prompt"])
        self.assertNotRegex(started.call_args.kwargs["image_prompt"], r"[\u0600-\u06FF]")

    def test_regenerate_image_without_campaign_creates_fresh_one(self) -> None:
        campaigns = FakeCampaigns()
        message_id = str(uuid4())
        rows = [
            {
                "id": message_id,
                "role": "assistant",
                "text": "پست انگشتر",
                "captions": {"instagram": "انگشتر", "telegram": "انگشتر", "whatsapp": "انگشتر"},
                "imagePrompt": "product photo of a silver ring, studio light, no text",
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw), rows)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_compose_service.start", return_value="job"
            ) as started:
                out = asyncio.run(
                    studio_chat_service.regenerate(message_id=message_id, part="image", campaigns=campaigns)
                )
        # کمپین تازه ساخته شد و ساخت از نو راه افتاد؛ پیام هم کمپین گرفت
        self.assertTrue(campaigns.created, "campaign create must be called")
        self.assertTrue(started.call_args.kwargs["campaign_id"])
        found = next(row for row in out.get("messages", []) if row.get("id") == message_id)
        self.assertTrue(found.get("campaignId"))

    def test_incomplete_caption_keeps_the_last_full_sentence(self) -> None:
        out = studio_chat_service._clip_captions(
            {
                "instagram": "جملهٔ اول تمام شد. همین حالا",
                "telegram": "کوتاه",
                "whatsapp": "کوتاه",
            },
            spoken="برای انگشتر نقره یک پست بساز",
        )
        self.assertEqual(out["instagram"], "جملهٔ اول تمام شد.")
        self.assertEqual(out["telegram"], "کوتاه.")

    def test_caption_drops_a_product_from_an_earlier_request(self) -> None:
        rows = [{"role": "user", "text": "برای کیف چرمی استوری بساز"}]
        with patch("app.services.studio_chat_service._messages", return_value=rows):
            out = studio_chat_service._clip_captions(
                {
                    "instagram": "انگشتر نقره نماد است. کیف چرمی نیز همراه است.",
                    "telegram": "انگشتر نقره.",
                    "whatsapp": "انگشتر نقره.",
                },
                spoken="عکس همین کالا را روی پس‌زمینهٔ تمیز بگذار",
                drop_unclaimed=True,
            )
        self.assertNotIn("کیف چرمی", out["instagram"])
        self.assertIn("انگشتر", out["instagram"])

    def test_prompt_fields_and_unclaimed_sales_lines_leave(self) -> None:
        raw = "کیف چرمی آماده است. جنس: چرم طبیعی با دوخت دقیق زاویه: نمای روبرو پس‌زمینه: میز چوبی قابل سفارش."
        out = studio_chat_service._clip_captions(
            {"instagram": raw, "telegram": raw, "whatsapp": raw},
            spoken="برای کیف چرمی استوری بساز",
            drop_unclaimed=True,
        )
        self.assertNotIn("جنس:", out["instagram"])
        self.assertNotIn("زاویه:", out["instagram"])
        self.assertNotIn("پس‌زمینه:", out["instagram"])
        self.assertNotIn("چرم طبیعی", out["instagram"])
        self.assertNotIn("قابل سفارش", out["instagram"])
        self.assertIn("کیف چرمی", out["instagram"])
        kept = studio_chat_service._repair_rewrite(
            {
                "instagram": "این انگشتر نقره برای استفادهٔ روزمره مناسب است.",
                "telegram": "این انگشتر نقره رسمی‌تر معرفی شد.",
                "whatsapp": "سلام.",
            }
        )
        self.assertNotIn("سلام", kept["whatsapp"])
        self.assertIn("انگشتر", kept["whatsapp"])

    def test_hashtags_do_not_start_an_image(self) -> None:
        campaigns = FakeCampaigns()
        with tempfile.TemporaryDirectory() as raw:
            patches = self._patches(Path(raw))
            with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
                "app.services.studio_chat_service.complete_json",
                new=AsyncMock(
                    return_value={
                        "reply": "هشتگ‌ها آماده شد.",
                        "instagram": "#گردنبند #نقره #زیورآلات #هدیه #استایل #اکسسوری",
                        "telegram": "",
                        "whatsapp": "",
                    }
                ),
            ), patch("app.services.studio_compose_service.start") as started:
                result = asyncio.run(studio_chat_service.chat("هشتگ فارسی برای گردنبند", campaigns))
        started.assert_not_called()
        self.assertEqual(campaigns.created, 0)
        caption = result["messages"][-1]["captions"]["instagram"]
        self.assertGreaterEqual(caption.count("#"), 5)
        self.assertIn("#گردنبند", caption)
        self.assertNotIn("نقره", caption)

    def test_hashtag_roots_are_balanced(self) -> None:
        raw = [
            "#گردنبند",
            "#گردنبند_شیک",
            "#گردنبند_خاص",
            "#گردنبند_دخترانه",
            "#گردنبند_مجلسی",
            "#گردنبند_هدیه",
            "#گردنبند_روزمره",
            "#فروشگاه",
            "#فروشگاه_گردنبند",
            "#اکسسوری_گردنبند",
        ]
        kept = studio_chat_service._balance_roots(raw)
        self.assertGreaterEqual(len(kept), 5)
        self.assertFalse(studio_chat_service._repeated_root(kept))


if __name__ == "__main__":
    unittest.main()
