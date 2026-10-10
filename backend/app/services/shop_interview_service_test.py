import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import onboard_service, shop_interview_service as loop, shop_service, shop_voice_service as voice
from app.state_store import tenant_scope


def _run(coro):
    return asyncio.run(coro)


def _assessment(**over) -> dict:
    base = {
        "brief": {},
        "wishes": [],
        "confidence": 30,
        "missing": [{"slot": "style", "question": "حس سایت را چطور می‌خواهی؟"}],
        "hurry": False,
        "confirms_build": False,
        "wants_change": False,
        "suggest": {},
    }
    return loop.clean_assessment({**base, **over})


class Delegation(unittest.TestCase):
    def test_handing_the_choice_to_the_model_is_recognised(self) -> None:
        for text in ("هرچی خودت صلاح می‌دونی", "هر چی", "فرقی نداره", "عجله دارم", "فقط بساز", "همین کافیه"):
            self.assertTrue(loop.is_delegate(text), text)
        for text in ("رنگش سبز باشه", "اسمش نقره‌خانه‌ست", "مشتری‌ها دانشجوهان"):
            self.assertFalse(loop.is_delegate(text), text)


class Acks(unittest.TestCase):
    def test_short_agreements_are_acks_and_questions_or_changes_are_not(self) -> None:
        for yes in ("آره", "بله!", "باشه", "خوب", "آره، شروع کن", "اوکی؟", "همین خوبه"):
            self.assertTrue(loop.is_ack(yes), yes)
        for other in ("", "نه", "رنگش رو سبز کن", "آره ولی اسمش رو عوض کن", "خوب قیمتش چنده", "آره بساز ولی لوگو بزرگ باشه"):
            self.assertFalse(loop.is_ack(other), other)


class AssessmentShape(unittest.TestCase):
    def test_everything_the_model_says_is_bounded(self) -> None:
        a = loop.clean_assessment(
            {
                "brief": {"style": "Boutique", "colors": "کرم و قهوه‌ای", "evil": "x"},
                "wishes": ["بالای صفحه ویدیو باشد", "بالای صفحه ویدیو باشد", "http://x.ir", "  لوگو   بزرگ  "],
                "confidence": 250,
                "missing": [
                    {"slot": "colors", "question": "رنگ‌ها؟"},
                    {"slot": "nonsense", "question": "؟"},
                    {"slot": "story", "question": ""},
                    {"slot": "audience", "question": "مشتری‌ها؟"},
                    {"slot": "order", "question": "سفارش؟"},
                    {"slot": "avoid", "question": "چه نباشد؟"},
                ],
                "hurry": "yes",
                "suggest": {"style": "atelier", "colors": "سفید"},
            }
        )
        self.assertEqual(a["brief"], {"style": "boutique", "colors": "کرم و قهوه‌ای"})
        self.assertEqual(a["wishes"], ["بالای صفحه ویدیو باشد", "لوگو بزرگ"])
        self.assertEqual(a["confidence"], 100)
        self.assertEqual([m["slot"] for m in a["missing"]], ["colors", "audience", "order"])
        self.assertTrue(a["hurry"] and not a["confirms_build"] and not a["wants_change"])
        self.assertEqual(loop.clean_assessment("nope")["confidence"], 0)
        self.assertEqual(loop.clean_assessment({"confidence": "abc"})["confidence"], 0)

    def test_wishes_accumulate_without_repeats_and_stay_bounded(self) -> None:
        got = loop.merge_wishes(["بالای صفحه ویدیو باشد"], ["لوگو بزرگ وسط هدر", "بالای صفحه ویدیو باشد"])
        self.assertEqual(got, ["بالای صفحه ویدیو باشد", "لوگو بزرگ وسط هدر"])
        many = loop.merge_wishes([f"درخواست شمارهٔ {i} برای سایت" for i in range(12)], ["درخواست تازه برای صفحهٔ اول"])
        self.assertEqual(len(many), 12)
        self.assertEqual(many[-1], "درخواست تازه برای صفحهٔ اول")

    def test_facts_that_sit_in_other_fields_are_not_wishes(self) -> None:
        brief = {"colors": "قهوه‌ای و کرم، مشکی نه", "brandName": "نقره‌خانه", "audience": "خانم‌های جوان ۲۰ تا ۳۵ ساله"}
        got = loop.merge_wishes(
            [],
            ["قهوه‌ای و کرم، مشکی نه", "نقره‌خانه", "بیشتر خانم‌های جوان ۲۰ تا ۳۵ ساله", "بالای صفحه ویدیو باشد", "تو"],
            brief,
        )
        self.assertEqual(got, ["بالای صفحه ویدیو باشد"])

    def test_a_longer_version_replaces_the_shorter_one(self) -> None:
        got = loop.merge_wishes(["لوگو بزرگ باشد"], ["لوگو بزرگ باشد و وسط هدر"])
        self.assertEqual(got, ["لوگو بزرگ باشد و وسط هدر"])


class Exit(unittest.TestCase):
    ready = {"style": "boutique", "colors": "کرم"}

    more = {"audience": "خانم‌های جوان", "story": "دست‌ساز", "brandName": "نقره‌خانه"}

    def test_enough_means_style_colours_three_more_facts_and_a_few_turns(self) -> None:
        a = _assessment(confidence=80)
        full = {**self.ready, **self.more}
        self.assertEqual(loop.decide(full, a, {}, 3), "propose")
        self.assertEqual(loop.decide(full, a, {}, 2), "ask")  # too early, however sure the model is
        self.assertEqual(loop.decide({**self.ready, "audience": "x", "story": "y"}, a, {}, 6), "ask")  # only two extras
        self.assertEqual(loop.decide({"style": "boutique", **self.more}, a, {}, 8), "ask")  # no colours yet
        self.assertEqual(loop.decide(full, _assessment(confidence=10), {}, 5), "ask")  # the model says it is lost

    def test_a_long_talk_ends_with_a_proposal_once_style_and_colours_are_known(self) -> None:
        self.assertEqual(loop.decide(self.ready, _assessment(confidence=40), {}, loop.MAX_TURNS), "propose")
        self.assertEqual(loop.decide({"style": "boutique"}, _assessment(confidence=40), {}, 20), "ask")

    def test_a_seller_in_a_hurry_gets_a_proposal_with_the_models_own_suggestion(self) -> None:
        a = _assessment(hurry=True, suggest={"style": "atelier", "colors": "کرم و طلایی"})
        self.assertEqual(loop.decide({}, a, {}, 1), "propose")
        self.assertEqual(loop.decide({}, _assessment(hurry=True), {}, 1), "ask")  # nothing to propose yet

    def test_a_build_needs_a_proposal_from_the_previous_turn(self) -> None:
        yes = _assessment(confirms_build=True)
        self.assertEqual(loop.decide(self.ready, yes, {"mode": "propose"}, 5), "build")
        self.assertNotEqual(loop.decide(self.ready, yes, {"mode": "ask"}, 5), "build")
        self.assertNotEqual(loop.decide(self.ready, yes, {}, 5), "build")
        change = _assessment(confirms_build=True, wants_change=True)
        self.assertEqual(loop.decide(self.ready, change, {"mode": "propose"}, 5), "ask")

    def test_two_empty_answers_in_a_row_end_the_questions(self) -> None:
        a = _assessment(confidence=10, suggest={"style": "boutique", "colors": "کرم و قهوه‌ای"})
        self.assertEqual(loop.decide({}, a, {"stalls": 1}, 4), "ask")
        self.assertEqual(loop.decide({}, a, {"stalls": loop.MAX_STALLS}, 4), "propose")
        self.assertEqual(loop.decide({}, a, {"stalls": loop.MAX_STALLS}, 2), "ask")  # a greeting and one vague line are not stalling yet
        self.assertEqual(loop.decide({}, _assessment(confidence=10), {"stalls": 5}, 4), "ask")  # nothing to propose yet

    def test_a_remark_while_the_proposal_is_open_reoffers_it(self) -> None:
        self.assertEqual(loop.decide(self.ready, _assessment(confidence=50), {"mode": "propose"}, 6), "propose")


class Turns(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for item in (
            patch.object(settings, "state_dir", self.tmp.name),
            patch.object(voice, "_capped", return_value=False),
            patch.object(voice, "_catalog_lines", return_value="کالایی نیست."),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.scope = tenant_scope("09123456789")
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.shop = {"brand": "نقره‌خانه"}

    def _turn(self, assessment: dict, speech: str | None, rows=None):
        rows = rows or [{"id": "1", "role": "user", "text": "سلام"}]
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=assessment)), patch.object(
            voice, "complete_text_chat", new=AsyncMock(return_value=speech)
        ) as said:
            out = _run(loop.turn(rows, onboard_service.get_brief(), self.shop))
        return out, said

    def test_ask_mode_keeps_what_was_learned_and_remembers_what_it_asked(self) -> None:
        out, said = self._turn(
            {"brief": {"style": "boutique", "audience": "خانم‌های جوان"}, "wishes": ["بالای صفحه ویدیو باشد"], "confidence": 35,
             "missing": [{"slot": "colors", "question": "رنگ‌ها؟"}, {"slot": "story", "question": "داستان برندت؟"}]},
            "عالی! رنگ‌هایی که دوست داری کدامند؟ و چه چیز برندت خاص است؟",
        )
        self.assertEqual(out["mode"], "ask")
        self.assertFalse(out["build"])
        self.assertIn("رنگ", out["reply"])
        brief = onboard_service.get_brief()
        self.assertEqual(brief["style"], "boutique")
        self.assertEqual(brief["audience"], "خانم‌های جوان")
        self.assertEqual(brief["wishes"], ["بالای صفحه ویدیو باشد"])
        self.assertFalse(brief["proposed"])
        state = loop._state()
        self.assertEqual(state["asked"], ["colors", "story"])
        self.assertEqual(state["turns"], 1)
        self.assertIn("رنگ‌ها؟", said.await_args.kwargs["system"])
        self.assertIn("بالای صفحه ویدیو باشد", said.await_args.kwargs["system"])

    def test_answers_that_teach_nothing_are_counted_and_the_second_one_brings_a_proposal(self) -> None:
        sure = {"confidence": 10, "suggest": {"style": "boutique", "colors": "کرم و قهوه‌ای"}, "missing": [{"slot": "name", "question": "اسمش چیه؟"}]}
        loop._save_state({"mode": "ask", "turns": 2})
        out, _ = self._turn(sure, "اسم فروشگاهت چیه؟", rows=[{"id": "1", "role": "user", "text": "نمی‌دونم"}])
        self.assertEqual(out["mode"], "ask")
        self.assertEqual(loop._state()["stalls"], 1)
        out, _ = self._turn(sure, "پیشنهاد من: بوتیک گرم با کرم و قهوه‌ای. همین را بسازم یا چیزی را عوض کنم؟", rows=[{"id": "2", "role": "user", "text": "خوب"}])
        self.assertEqual(out["mode"], "propose")
        self.assertEqual(loop._state()["stalls"], 0)

    def test_a_proposal_without_the_build_question_is_asked_again_and_then_summarised_in_plain_words(self) -> None:
        assessment = {"hurry": True, "confidence": 10, "suggest": {"style": "boutique", "colors": "کرم و قهوه‌ای"}}
        said = AsyncMock(side_effect=["سؤال تازه: اسمت چیه و چه می‌فروشی؟", "باز هم سؤال دیگری: ارسال چطور است؟"])
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=assessment)), patch.object(voice, "complete_text_chat", new=said):
            out = _run(loop.turn([{"id": "1", "role": "user", "text": "فقط بساز"}], onboard_service.get_brief(), self.shop))
        self.assertEqual(said.await_count, 2)
        self.assertEqual(out["mode"], "propose")
        self.assertIn("همین را بسازم", out["reply"])
        self.assertIn("بوتیک گرم و خانوادگی", out["reply"])  # the plain summary built from the model's own suggestion

    def test_the_models_suggestion_never_overrides_what_the_seller_said(self) -> None:
        onboard_service.save_brief({"style": "atelier", "colors": "سفید"})
        assessment = {"hurry": True, "confidence": 20, "suggest": {"style": "street", "colors": "نارنجی", "brandName": "مه‌لقا"}}
        said = AsyncMock(return_value="طرح من: لوکس و خلوت با سفید و اسم مه‌لقا. همین را بسازم یا چیزی را عوض کنم؟")
        with patch.object(voice, "complete_json", new=AsyncMock(return_value=assessment)), patch.object(voice, "complete_text_chat", new=said):
            _run(loop.turn([{"id": "1", "role": "user", "text": "هرچی"}], onboard_service.get_brief(), self.shop))
        system = said.await_args.kwargs["system"]
        self.assertIn("brandName: مه‌لقا", system)
        self.assertNotIn("style: street", system)
        self.assertNotIn("colors: نارنجی", system)

    def test_the_wishes_reach_the_factory_prompt(self) -> None:
        self._turn({"brief": {"style": "atelier", "colors": "سفید"}, "wishes": ["شبیه سایت زارا"], "confidence": 40}, "باشه، چشم به‌خاطر دارم.")
        block = onboard_service.brief_block()
        self.assertIn("شبیه سایت زارا", block)
        self.assertIn("اولویت بالا", block)

    def test_when_the_model_cannot_word_the_turn_its_own_question_is_asked(self) -> None:
        out, _ = self._turn({"confidence": 20, "missing": [{"slot": "style", "question": "حس سایت را چطور می‌خواهی؟"}]}, None)
        self.assertEqual(out["reply"], "حس سایت را چطور می‌خواهی؟")

    def test_no_assessment_means_the_caller_uses_its_script(self) -> None:
        with patch.object(voice, "complete_json", new=AsyncMock(return_value={"error": "llm_unreachable"})):
            self.assertIsNone(_run(loop.turn([{"id": "1", "role": "user", "text": "سلام"}], {}, self.shop)))
        with patch.object(voice, "_capped", return_value=True), patch.object(
            voice, "complete_json", new=AsyncMock(side_effect=AssertionError("no model call when capped"))
        ):
            self.assertIsNone(_run(loop.turn([{"id": "1", "role": "user", "text": "سلام"}], {}, self.shop)))

    def test_propose_then_confirm_builds_once_and_fills_assumed_gaps(self) -> None:
        proposal = {"brief": {}, "confidence": 20, "hurry": True, "suggest": {"style": "atelier", "colors": "کرم و طلایی", "brandName": "نقره‌خانه"}}
        out, _ = self._turn(proposal, "پیشنهاد من: لوکس و خلوت با کرم و طلایی. بسازم؟")
        self.assertEqual(out["mode"], "propose")
        self.assertTrue(onboard_service.get_brief()["proposed"])
        self.assertFalse(onboard_service.brief_ready(onboard_service.get_brief()))  # a proposal is not yet the seller's word
        yes, said = self._turn(
            {"confirms_build": True, "confidence": 60}, "x",
            rows=[{"id": "1", "role": "assistant", "text": out["reply"]}, {"id": "2", "role": "user", "text": "آره بساز"}],
        )
        self.assertTrue(yes["build"])
        said.assert_not_awaited()  # no words needed, the build starts
        brief = onboard_service.get_brief()
        self.assertEqual(brief["style"], "atelier")
        self.assertEqual(brief["colors"], "کرم و طلایی")
        self.assertEqual(brief["assumed"], ["style", "colors", "brandName"])
        self.assertFalse(brief["proposed"])

    def test_a_confirmed_wider_palette_is_kept_next_to_the_sellers_own_colours(self) -> None:
        onboard_service.save_brief({"style": "atelier", "colors": "سفید"})
        loop._save_state({"mode": "propose", "turns": 3, "proposal": {"style": "atelier", "colors": "سفید، مشکی و خاکی روشن"}})
        out, _ = self._turn({"confirms_build": True, "confidence": 60}, "x", rows=[{"id": "3", "role": "user", "text": "آره بساز"}])
        self.assertTrue(out["build"])
        brief = onboard_service.get_brief()
        self.assertEqual(brief["colors"], "سفید")
        self.assertIn("مشکی و خاکی روشن", brief["notes"])

    def test_internal_style_names_never_reach_the_seller(self) -> None:
        out, _ = self._turn({"brief": {"style": "atelier", "colors": "سفید"}, "confidence": 50}, "حس atelier با سفید خیلی می‌شینه. مشتری‌ها چه کسانی‌اند؟")
        self.assertNotIn("atelier", out["reply"])
        self.assertIn("لوکس و خلوت", out["reply"])

    def test_a_change_after_the_proposal_reopens_the_questions(self) -> None:
        onboard_service.save_brief({"style": "atelier", "colors": "کرم"})
        loop._save_state({"mode": "propose", "turns": 4})
        out, _ = self._turn(
            {"brief": {"colors": "سبز و کرم"}, "wants_change": True, "confirms_build": True, "confidence": 70,
             "missing": [{"slot": "avoid", "question": "چیزی هست که نخواهی؟"}]},
            "حتماً، سبز و کرم. چیزی هست که اصلاً نخواهی توی سایت باشد؟",
        )
        self.assertEqual(out["mode"], "ask")
        self.assertFalse(out["build"])
        self.assertEqual(onboard_service.get_brief()["colors"], "سبز و کرم")

    def test_a_bare_yes_after_the_proposal_confirms_even_when_the_model_doubts(self) -> None:
        onboard_service.save_brief({"style": "boutique", "colors": "کرم"})
        for word in ("خوب", "آره", "باشه", "شروع کن", "اوکی؟"):
            loop._save_state({"mode": "propose", "turns": 4})
            out, _ = self._turn({"confirms_build": False, "confidence": 20}, "x", rows=[{"id": "9", "role": "user", "text": word}])
            self.assertTrue(out["build"], word)

    def test_a_bare_yes_without_a_proposal_builds_nothing(self) -> None:
        onboard_service.save_brief({"style": "boutique", "colors": "کرم"})
        loop._save_state({"mode": "ask", "turns": 2})
        out, _ = self._turn({"confidence": 40, "missing": [{"slot": "name", "question": "اسمش چیست؟"}]}, "اسم فروشگاهت چیه؟", rows=[{"id": "9", "role": "user", "text": "آره"}])
        self.assertFalse(out["build"])

    def test_a_proposal_goes_stale_after_half_an_hour_and_a_bare_yes_then_builds_nothing(self) -> None:
        onboard_service.save_brief({"style": "boutique", "colors": "کرم"})
        loop._save_state({"mode": "propose", "turns": 4, "at": time.time() - loop.PROPOSAL_TTL - 60})
        out, _ = self._turn({"confidence": 40, "missing": [{"slot": "name", "question": "اسمش چیست؟"}]}, "اسم فروشگاهت چیه؟", rows=[{"id": "9", "role": "user", "text": "آره"}])
        self.assertFalse(out["build"])
        self.assertEqual(out["mode"], "ask")

    def test_the_build_button_under_an_old_proposal_still_builds(self) -> None:
        # 2026-10-10: a new seller left the proposal open for over an hour; «آره، بساز» then got the summary again
        onboard_service.save_brief({"style": "boutique", "colors": "کرم"})
        proposal = "جمع‌بندی من: حس سایت: بوتیک گرم و خانوادگی؛ رنگ‌ها: قهوه‌ای، کرم. همین را بسازم یا چیزی را عوض کنم؟"
        loop._save_state({"mode": "propose", "turns": 4, "at": time.time() - loop.PROPOSAL_TTL - 3600, "said": loop._squash(proposal)[:24]})
        rows = [{"id": "a", "role": "assistant", "text": proposal}, {"id": "9", "role": "user", "text": "آره، بساز"}]
        out, _ = self._turn({"confidence": 40, "missing": []}, "x", rows=rows)
        self.assertTrue(out["build"])

    def test_an_answer_to_the_interview_question_goes_back_to_the_interview(self) -> None:
        from app.services import router_service
        from app.state_store import write_json

        question = "حالا رنگ‌های اصلی سایت را همان قهوه‌ای و کرم بگذارم یا رنگ دیگری در ذهن داری؟"
        write_json("shop-messages.json", [{"role": "user", "text": "بوتیک گرم"}, {"role": "assistant", "text": question, "kind": "ask"}])
        loop._save_state({"mode": "ask", "turns": 2})
        asked = {"role": "assistant", "text": question, "kind": "ask", "options": ["کرم و قهوه‌ای", "سفید و مینیمال"]}

        def answer(text: str) -> list[dict]:
            return [asked, {"role": "user", "text": text}]

        self.assertTrue(loop.awaits_answer(answer("کرم و قهوه‌ای")))
        self.assertTrue(loop.awaits_answer(answer("سبز تیره")))
        self.assertFalse(loop.awaits_answer(answer("فروش امروز چقدر بود؟")))
        self.assertFalse(loop.awaits_answer([{**asked, "text": "کدام کالا حذف شود؟"}, {"role": "user", "text": "کیف"}]))  # the router's own question
        # the tapped chip has no build word: the router still hands it to the interview, not to the shop editor
        with patch.object(router_service, "_messages", return_value=answer("کرم و قهوه‌ای")), patch(
            "app.services.shop_service.current_shop", return_value={"brand": "ایران‌دخت", "slug": ""}
        ):
            self.assertEqual(router_service.route_tool("کرم و قهوه‌ای"), "shop_chat")
        loop._save_state({"mode": "build", "turns": 3})
        self.assertFalse(loop.awaits_answer(answer("کرم و قهوه‌ای")))

    def test_a_proposal_is_answered_only_when_it_is_still_the_last_thing_sozan_said(self) -> None:
        onboard_service.save_brief({"style": "boutique", "colors": "کرم"})
        proposal = "پیشنهاد من یک سایت گرم است. همین را بسازم یا چیزی را عوض کنم؟"
        for assistant_last, builds in ((proposal, True), ("وضعیت: ساخت فروشگاه در جریان نیست.", False)):
            loop._save_state({"mode": "propose", "turns": 4, "at": time.time(), "said": loop._squash(proposal)[:24]})
            rows = [{"id": "a", "role": "assistant", "text": assistant_last}, {"id": "9", "role": "user", "text": "آره"}]
            out, _ = self._turn({"confidence": 40, "missing": [{"slot": "name", "question": "اسمش چیست؟"}]}, "اسم فروشگاهت چیه؟", rows=rows)
            self.assertEqual(out["build"], builds, assistant_last)

    def test_a_reply_that_claims_the_build_already_started_is_never_shown(self) -> None:
        out, _ = self._turn({"hurry": True, "suggest": {"style": "boutique", "colors": "کرم"}, "confidence": 20}, "باشه، همین را می‌سازم. همین را بسازم یا چیزی را عوض کنم؟")
        self.assertNotIn("می‌سازم", out["reply"])
        self.assertIn("بسازم", out["reply"])

    def test_after_the_build_the_interview_steps_aside(self) -> None:
        loop._save_state({"mode": "build", "turns": 6})
        with patch.object(voice, "complete_json", new=AsyncMock(side_effect=AssertionError("no model after the build started"))):
            out = _run(loop.turn([{"id": "1", "role": "user", "text": "آره همینو بساز"}], onboard_service.get_brief(), self.shop))
        self.assertTrue(out["skip"])

    def test_turns_are_counted_by_the_interview_not_by_the_whole_chat_history(self) -> None:
        old_chat = [{"id": str(i), "role": "user", "text": "پیام قدیمی"} for i in range(20)]
        out, _ = self._turn({"confidence": 40, "missing": [{"slot": "style", "question": "حس سایت؟"}]}, "حس سایت را چطور می‌خواهی؟", rows=old_chat)
        self.assertEqual(loop._state()["turns"], 1)
        self.assertEqual(out["mode"], "ask")

    def test_reset_starts_a_fresh_interview(self) -> None:
        loop._save_state({"mode": "propose", "turns": 7, "asked": ["style"]})
        onboard_service.save_brief({"proposed": True})
        loop.reset()
        self.assertEqual(loop._state(), {})
        self.assertFalse(onboard_service.get_brief()["proposed"])


class QuickAnswers(unittest.TestCase):
    def test_taps_follow_the_question_just_asked(self) -> None:
        style = loop.quick_answers("ask", _assessment(missing=[{"slot": "style", "question": "حس سایت؟"}]))
        self.assertEqual(style[:3], ["لوکس و خلوت", "خیابانی و پرانرژی", "بوتیک گرم و خانوادگی"])
        self.assertEqual(style[-1], loop.DELEGATE_ANSWER)
        self.assertEqual(loop.quick_answers("ask", _assessment(missing=[{"slot": "story", "question": "داستان؟"}])), [])
        self.assertEqual(loop.quick_answers("ask", _assessment(missing=[])), [])
        yes = loop.quick_answers("propose", _assessment())
        self.assertEqual(yes, ["آره، بساز", "چیزی را عوض کنم"])
        self.assertTrue(loop.is_ack(yes[0]))
        self.assertTrue(loop.is_delegate(loop.DELEGATE_ANSWER))
        self.assertFalse(loop.is_ack(yes[1]))

    def test_a_tap_answer_is_understood_by_the_loop(self) -> None:
        for answer in ("لوکس و خلوت", "کرم و قهوه‌ای", "از دایرکت اینستاگرام", "فقط کالاها"):
            self.assertFalse(loop.is_ack(answer), answer)  # these are content, not a yes


class GuidedTurn(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for item in (patch.object(settings, "state_dir", self.tmp.name), patch.object(voice, "_capped", return_value=False)):
            item.start()
            self.addCleanup(item.stop)
        self.scope = tenant_scope("09123456789")
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)

    def _guided(self, raw: str, turn, brief=None, shop=None, build=None):
        shop = {"status": "idle", "slug": "", "brand": "x", **(shop or {})}
        with patch.object(loop, "turn", new=AsyncMock(return_value=turn)), patch.object(
            shop_service, "start_build", return_value=build or {"ok": True}
        ) as start:
            out = _run(shop_service._guided_turn(raw, [], brief if brief is not None else onboard_service.get_brief(), shop))
        return out, start

    def test_a_confirmed_build_starts_once_and_the_reply_is_the_models(self) -> None:
        onboard_service.save_brief({"style": "boutique", "colors": "کرم"})
        with patch.object(voice, "complete_json", new=AsyncMock(return_value={"reply": "شروع کردم؛ پیشرفتش را در صفحهٔ «فروشگاه» می‌بینی."})):
            out, start = self._guided("آره، شروع کن", {"reply": "", "build": True, "mode": "build"})
        start.assert_called_once()
        self.assertIn("شروع کردم", out["text"])

    def test_a_refused_build_is_not_announced(self) -> None:
        out, start = self._guided("آره، شروع کن", {"reply": "", "build": True, "mode": "build"}, build={"ok": False, "error": ""})
        self.assertNotIn("شروع شد", out["text"])

    def test_no_model_means_the_old_script(self) -> None:
        out, _ = self._guided("یه فروشگاه می‌خوام", None, brief={})
        self.assertEqual(out, {"text": shop_service.STYLE_Q})

    def test_a_stepping_aside_interview_leaves_the_message_to_the_shop_chat(self) -> None:
        out, start = self._guided("همینو بساز", {"reply": "", "build": False, "mode": "build", "skip": True}, brief={})
        self.assertIsNone(out)
        start.assert_not_called()

    def test_no_interview_while_building_or_after_the_shop_exists(self) -> None:
        turn = {"reply": "سؤال", "build": False, "mode": "ask"}
        self.assertIsNone(self._guided("سلام", turn, brief={}, shop={"status": "running"})[0])
        done = {"style": "atelier", "colors": "کرم"}
        self.assertIsNone(self._guided("سلام", turn, brief=done, shop={"slug": "x", "status": "failed"})[0])
        self.assertIsNone(self._guided("بساز", turn, brief=done)[0])  # the seller's own «بساز» takes the explicit path


if __name__ == "__main__":
    unittest.main()
