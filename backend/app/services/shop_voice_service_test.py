import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import onboard_service, shop_service, shop_voice_service as voice
from app.state_store import tenant_scope


def _run(coro):
    return asyncio.run(coro)


class ReplyChecks(unittest.TestCase):
    def test_a_reply_must_be_persian_short_and_free_of_addresses(self) -> None:
        self.assertTrue(voice.acceptable("عالی شد، تیتر را گذاشتم «نقرهٔ نیشابور» و همین‌جا می‌بینی."))
        self.assertFalse(voice.acceptable(""))
        self.assertFalse(voice.acceptable("Done! Your title was changed."))
        self.assertFalse(voice.acceptable("سایتت روی http://127.0.0.1:9000 باز است و آماده است."))

    def test_a_quoted_fact_must_survive(self) -> None:
        keep = ["«نقرهٔ نیشابور»"]
        self.assertFalse(voice.acceptable("تیتر عوض شد و همین‌جا می‌بینی.", must_keep=["نقرهٔ نیشابور"]))
        self.assertTrue(voice.acceptable("تیتر شد نقرهٔ نیشابور و همین‌جا می‌بینی.", must_keep=["نقرهٔ نیشابور"]))
        self.assertTrue(keep)

    def test_success_words_are_refused_when_nothing_happened(self) -> None:
        self.assertFalse(voice.acceptable("رنگ را عوض کردم و تغییر اعمال شد.", patched=False))
        self.assertTrue(voice.acceptable("این یکی انجام نشد؛ المان را نگه دار تا دقیق‌تر ببینم.", patched=False))
        self.assertFalse(voice.acceptable("انجام نشد و کار ناموفق ماند، نمی‌شود.", patched=True))

    def test_a_name_in_quotes_must_come_from_the_facts(self) -> None:
        facts = "ساخت فروشگاه شروع شد."
        self.assertFalse(voice.acceptable("ساخت فروشگاه «بساز» شروع شد و همین‌جا می‌بینی.", facts=facts))
        self.assertTrue(voice.acceptable("ساخت فروشگاه شروع شد و همین‌جا می‌بینی‌اش.", facts=facts))
        self.assertTrue(voice.acceptable("متن شد «نقره» و همین‌جا می‌بینی.", facts="متن به «نقره» تغییر کرد."))

    def test_no_promises_the_system_cannot_keep(self) -> None:
        self.assertFalse(voice.acceptable("داریم می‌سازیمش؛ تموم شد بهت می‌گم، یه کم صبر کن."))
        self.assertFalse(voice.acceptable("ساخت شروع شد و بعدش خبرت می‌کنم که آماده شد."))
        self.assertTrue(voice.acceptable("ساخت شروع شد و پیشرفتش را همین‌جا می‌بینی."))

    def test_markdown_and_newlines_are_flattened(self) -> None:
        self.assertEqual(voice.clean_reply("**سلام**\n\nچطوری؟"), "سلام چطوری؟")

    def test_brief_only_takes_known_style_and_plain_text(self) -> None:
        out = voice.clean_brief(
            {"style": "Atelier", "colors": ["کرم", "مشکی"], "audience": "زن‌های ۲۵ تا ۴۰ ساله", "story": "http://x.ir", "evil": "x", "tone": "  گرم   و صمیمی "}
        )
        self.assertEqual(out["style"], "atelier")
        self.assertEqual(out["colors"], "کرم، مشکی")
        self.assertEqual(out["tone"], "گرم و صمیمی")
        self.assertNotIn("story", out)
        self.assertNotIn("evil", out)
        self.assertEqual(voice.clean_brief({"style": "gothic"}), {})
        self.assertEqual(voice.clean_brief("nope"), {})


class SayTests(unittest.TestCase):
    def test_model_words_are_used_when_they_keep_the_facts(self) -> None:
        reply = {"reply": "تیتر را شد «نقرهٔ نیشابور»؛ همین‌جا می‌بینی‌اش."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=reply)):
            out = _run(voice.say("edit_result", ["متن به «نقرهٔ نیشابور» تغییر کرد."], seller_text="تیتر را عوض کن", fallback="F", patched=True))
        self.assertEqual(out, reply["reply"])

    def test_plain_fallback_when_the_model_drops_a_fact_or_fails(self) -> None:
        dropped = {"reply": "تیتر عوض شد و همین‌جا می‌بینی‌اش دوست من."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=dropped)):
            self.assertEqual(_run(voice.say("edit_result", ["متن به «نقرهٔ نیشابور» تغییر کرد."], fallback="F", patched=True)), "F")
        with patch.object(voice, "complete_json", new=AsyncMock(return_value={"error": "llm_unreachable", "reply": "مدل پاسخ نداد."})):
            self.assertEqual(_run(voice.say("edit_result", ["x"], fallback="F")), "F")

    def test_a_failure_is_never_dressed_up_as_success(self) -> None:
        lie = {"reply": "حله، رنگ را عوض کردم و روی سایت آمد."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=lie)):
            self.assertEqual(_run(voice.say("edit_not_done", ["رنگ پیدا نشد."], fallback="F", patched=False)), "F")


class InterviewTests(unittest.TestCase):
    def _turn(self, payload: dict, brief: dict | None = None):
        with patch.object(voice, "complete_json_chat", new=AsyncMock(return_value=payload)), patch.object(
            voice, "_catalog_lines", return_value="کالایی نیست."
        ):
            return _run(voice.interview_turn([{"id": "1", "role": "user", "text": "انگشتر نقره می‌فروشم"}], brief or {}, {"brand": "نقره‌خانه"}))

    def test_turn_carries_reply_brief_and_flags(self) -> None:
        out = self._turn(
            {"reply": "چه خوب! مشتری‌هات بیشتر چه سنی هستند و دوست داری سایت چه حسی داشته باشد؟", "brief": {"style": "boutique", "audience": "زن‌های جوان"}, "ready": False}
        )
        self.assertIn("مشتری‌هات", out["reply"])
        self.assertEqual(out["brief"], {"style": "boutique", "audience": "زن‌های جوان"})
        self.assertFalse(out["ready"] or out["build"])

    def test_unusable_model_output_means_fallback_to_the_script(self) -> None:
        self.assertIsNone(self._turn({"error": "llm_unreachable"}))
        self.assertIsNone(self._turn({"reply": "ok"}))


class GuidedTurnTests(unittest.TestCase):
    def _guided(self, raw: str, turn: dict | None, brief: dict, shop: dict | None = None):
        shop = {"status": "idle", "slug": "", "brand": "نقره‌خانه", **(shop or {})}
        with patch.object(voice, "interview_turn", new=AsyncMock(return_value=turn)), patch.object(
            shop_service, "start_build", return_value={"ok": True}
        ) as start:
            out = _run(shop_service._guided_turn(raw, [], brief, shop))
        return out, start

    def test_the_brief_grows_from_the_model_and_nothing_builds_by_itself(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
            turn = {"reply": "عالی؛ رنگ‌ها چی باشد؟ مثلاً چیزی که با نقره بنشیند.", "brief": {"style": "atelier", "audience": "خانم‌های شهری"}, "ready": False, "build": True}
            out, start = self._guided("لوکس و خلوت", turn, onboard_service.get_brief())
            self.assertEqual(out, turn["reply"])
            start.assert_not_called()  # build=True is not enough without a style and colours
            brief = onboard_service.get_brief()
            self.assertEqual(brief["style"], "atelier")
            self.assertEqual(brief["audience"], "خانم‌های شهری")
            self.assertFalse(brief["proposed"])

    def test_a_seller_who_says_go_starts_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
            onboard_service.save_brief({"style": "atelier", "colors": "کرم و مشکی"})
            turn = {"reply": "باشه، همین الان شروع می‌کنم.", "brief": {}, "ready": True, "build": True}
            out, start = self._guided("آره، شروع کن", turn, onboard_service.get_brief())
            self.assertEqual(out, turn["reply"])
            start.assert_called_once()
            asked, start = self._guided("شروع کنم؟", turn, onboard_service.get_brief())
            start.assert_not_called()  # a question is not an order

    def test_a_build_the_factory_refuses_is_not_announced(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
            onboard_service.save_brief({"style": "atelier", "colors": "کرم و مشکی", "proposed": True})
            turn = {"reply": "باشه، همین الان شروع می‌کنم.", "brief": {}, "ready": True, "build": True}
            shop = {"status": "idle", "slug": "", "brand": "x"}
            with patch.object(voice, "interview_turn", new=AsyncMock(return_value=turn)), patch.object(
                shop_service, "start_build", return_value={"ok": False, "error": ""}
            ):
                out = _run(shop_service._guided_turn("آره، شروع کن", [], onboard_service.get_brief(), shop))
            self.assertNotIn("شروع می‌کنم", out)

    def test_model_failure_falls_back_to_the_old_script(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
            out, _ = self._guided("یه فروشگاه می‌خوام", None, {})
            self.assertEqual(out, shop_service.STYLE_Q)

    def test_no_interview_while_building_or_after_the_shop_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
            turn = {"reply": "یک چیزی بگو.", "brief": {}, "ready": False, "build": False}
            self.assertIsNone(self._guided("سلام", turn, {}, {"status": "running"})[0])
            done = {"style": "atelier", "colors": "کرم"}
            self.assertIsNone(self._guided("سلام", turn, done, {"slug": "x", "status": "failed"})[0])
            self.assertIsNone(self._guided("بساز", turn, done)[0])


if __name__ == "__main__":
    unittest.main()
