import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services import shop_voice_service as voice


def _run(coro):
    return asyncio.run(coro)


class ReplyChecks(unittest.TestCase):
    def test_a_reply_must_be_persian_short_and_free_of_addresses(self) -> None:
        self.assertTrue(voice.acceptable("عالی شد، تیتر را گذاشتم «نقرهٔ نیشابور» و همین‌جا می‌بینی."))
        self.assertFalse(voice.acceptable(""))
        self.assertFalse(voice.acceptable("Done! Your title was changed."))
        self.assertFalse(voice.acceptable("سایتت روی http://127.0.0.1:9000 باز است و آماده است."))

    def test_markup_words_and_unfilled_slots_never_reach_the_seller(self) -> None:
        self.assertFalse(voice.acceptable("تیتر h1 هنوز سر جایش است و حذف نشده، می‌خواهی بردارم؟"))
        self.assertFalse(voice.acceptable("پیشنهادم این است که اسمش «بوتیک [نام شما]» باشد، همین را بسازم؟"))
        self.assertFalse(voice.acceptable("اسم فروشگاه را {brand} می‌گذارم و شعارش را بعداً می‌گویم"))
        self.assertTrue(voice.acceptable("اسمش را «نقره‌خانه» می‌گذارم، همین را بسازم یا چیزی را عوض کنم؟"))
        self.assertEqual(voice.clean_reply("نمیکنم؛ فروشگاهت را میسازم"), "نمی‌کنم؛ فروشگاهت را می‌سازم")
        self.assertEqual(voice.clean_reply("پیج pinkshop528_sirjan و mahsoo__beauty را خواندم _مهم_"), "پیج pinkshop528_sirjan و mahsoo__beauty را خواندم مهم")

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

    def test_numbers_and_hosts_of_the_facts_must_survive(self) -> None:
        facts = "کالا «انگشتر» با ۱٬۲۰۰٬۰۰۰ تومان روی nogre.sozan-core.ir آمد."
        self.assertTrue(voice.acceptable("انگشتر با 1200000 تومان روی nogre.sozan-core.ir آمد و باز می‌شود.", facts=facts.replace("«انگشتر»", "انگشتر")))
        self.assertFalse(voice.acceptable("انگشتر با قیمتی که گفتی روی سایتت آمد و باز می‌شود.", facts=facts.replace("«انگشتر»", "انگشتر")))
        self.assertFalse(voice.acceptable("انگشتر با 900000 تومان روی nogre.sozan-core.ir آمد و باز می‌شود.", facts=facts.replace("«انگشتر»", "انگشتر")))
        self.assertTrue(
            voice.acceptable(
                "سایز ۵۴ را روی کالا گذاشتم و تمام شد.",
                facts="کالا به کاتالوگ اضافه شد.",
                seller_text="انگشتر سایز ۵۴ اضافه کن",
            )
        )
        self.assertFalse(voice.acceptable("سه کالا در کاتالوگ است و تمام.", facts="۲ کالا در کاتالوگ است."))
        self.assertTrue(voice.acceptable("قیمت ۸۵۰ هزار تومان ثبت شد و تمام.", facts="قیمت ۸۵۰٬۰۰۰ تومان است."))

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
    def setUp(self) -> None:
        patcher = patch.object(voice, "_capped", return_value=False)  # the shared test ledger may be full
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_over_budget_means_the_plain_text_and_no_model_call(self) -> None:
        with patch.object(voice, "_capped", return_value=True), patch.object(
            voice, "complete_json", new=AsyncMock(side_effect=AssertionError("capped tenants must not wait for a model"))
        ):
            self.assertEqual(_run(voice.say("edit_result", ["x"], fallback="F")), "F")

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

    def test_a_failure_in_the_facts_is_not_reworded_as_success_even_without_the_flag(self) -> None:
        lie = {"reply": "حله، پست را فرستادم و همین الان روی تلگرام نشست."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=lie)):
            self.assertEqual(_run(voice.say("tool_result", ["پست ارسال نشد؛ تلگرام وصل نیست."], fallback="F")), "F")
        ok = {"reply": "ارسال نشد چون تلگرام وصل نیست؛ اول وصلش کن بعد دوباره بگو."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=ok)):
            self.assertEqual(_run(voice.say("tool_result", ["پست ارسال نشد؛ تلگرام وصل نیست."], fallback="F")), ok["reply"])

    def test_an_introduction_keeps_the_four_features(self) -> None:
        brief = voice.about_text()
        self.assertLess(len(brief), 600)
        self.assertTrue(voice.covers_about(brief))
        thin = {"reply": "من سوزانم و فروشگاه را با چند جمله می‌سازم."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=thin)):
            out = _run(voice.say("about_self", [brief], seller_text="تو کی هستی؟", fallback=brief))
        self.assertEqual(out, brief)
        full = {"reply": "من سوزانم. فروشگاه را می‌سازم، در استودیو پست می‌سازم، صندوق را جمع می‌کنم و پرداخت را ثبت می‌کنم."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=full)):
            kept = _run(voice.say("about_self", [brief], seller_text="تو کی هستی؟", fallback=brief))
        self.assertEqual(kept, full["reply"])

    def test_a_made_up_count_falls_back_and_is_observed(self) -> None:
        seen: list[dict] = []

        def emit_later(**kwargs):
            seen.append(kwargs)

        with patch.object(voice, "complete_json", new=AsyncMock(return_value={"reply": "سه کالا در کاتالوگ است و تمام."})), patch(
            "app.services.observe_client.emit_later", emit_later
        ):
            out = _run(voice.say("tool_result", ["۲ کالا در کاتالوگ است."], fallback="۲ کالا در کاتالوگ است."))
        self.assertEqual(out, "۲ کالا در کاتالوگ است.")
        self.assertEqual(seen[-1]["payload"]["reason"], "numbers")
        self.assertEqual(seen[-1]["title"], "voice-plain")

    def test_the_sellers_own_number_is_kept(self) -> None:
        reply = {"reply": "سایز ۵۴ را گذاشتم و کالا اضافه شد."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=reply)):
            out = _run(
                voice.say(
                    "tool_result",
                    ["کالا به کاتالوگ اضافه شد."],
                    seller_text="انگشتر سایز ۵۴ اضافه کن",
                    fallback="کالا به کاتالوگ اضافه شد.",
                )
            )
        self.assertEqual(out, reply["reply"])

    def test_an_unbacked_claim_falls_back_to_the_plain_sentence(self) -> None:
        reply = {"reply": "این انگشتر نقره است و به کاتالوگ آمد."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=reply)), patch(
            "app.services.claims_guard.check", new=AsyncMock(return_value=["نقره"])
        ):
            out = _run(voice.say("tool_result", ["کالا به کاتالوگ اضافه شد."], fallback="کالا به کاتالوگ اضافه شد."))
        self.assertEqual(out, "کالا به کاتالوگ اضافه شد.")

    def test_a_failure_is_never_dressed_up_as_success(self) -> None:
        lie = {"reply": "حله، رنگ را عوض کردم و روی سایت آمد."}
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=lie)):
            self.assertEqual(_run(voice.say("edit_not_done", ["رنگ پیدا نشد."], fallback="F", patched=False)), "F")


if __name__ == "__main__":
    unittest.main()
