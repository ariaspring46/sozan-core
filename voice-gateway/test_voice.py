"""Unit tests for phone audio and SIP digest. No network."""

from __future__ import annotations

import array
import json
import os
import time
import unittest
from pathlib import Path

from sim_call import mix_shop_noise
from audio_codec import (
    PcmJitter,
    decode_to_pcm16,
    encode_pcm16,
    gate_kind,
    lowpass_pcm16,
    pcm_similarity,
    resample_pcm16,
    rms,
    rtp_packet,
    rtp_parse,
)
from brain import (
    Brain,
    clean_ear_text,
    cloud_speech_body,
    clarify,
    chat_completions_url,
    echo_should_block,
    is_ack,
    is_carrier_text,
    is_correction,
    is_done,
    is_hello,
    is_hold,
    is_howdy,
    is_repeat,
    is_stuck,
    is_who,
    looks_like_echo,
    looks_like_speech,
    should_hold_fragment,
    mask_messages,
    sales_request_body,
    speakable,
    usable_request,
    wants_bye,
    worth_llm,
)
from heard_bank import heard_rows, should_repair
from meaning import INTENTS, PHONE_PHRASES, MeaningIndex
from main import (
    CURIOUS_LINES,
    NUDGE_AFTER_S,
    SALES_HANG_AFTER_S,
    THINK_WAIT_S,
    THINKING_LINES,
    barge_kind_ready,
    hold_early_carrier,
    next_varied,
    parse_sim_command,
)
from sales import (
    ADDRESS_LINE,
    BYE_LINE,
    CLOSE_LINE,
    FIXED_SALES_LINES,
    HELLO_LINE,
    GREET_VARIANTS,
    INTRO_VARIANTS,
    INTRO_SMS_VARIANTS,
    NOTIME_VARIANTS,
    PERM_VARIANTS,
    PAIN_LINE,
    DM_LINE,
    CONTENT_LINE,
    ORDER_LINE,
    SITE_LINE,
    MISHEARD_LINE,
    REPEAT_FREE,
    SALES_PROBE_LINE,
    WAIT_BRIGHT,
    SalesState,
    ShopCard,
    fallback_line,
    finish_spoken,
    formalize_you,
    gift_allowed,
    gift_line,
    guard_reply,
    load_campaign,
    note_spoken,
    person_started,
    plan_turn,
    read_signals,
    sales_brief,
    sales_ended,
    sales_kind,
    sales_open,
    cached_sales_lines,
    set_plans_fetcher,
    set_payment_fetcher,
    shorten_reply,
    split_sentences,
    take_ready_sentences,
    toman_words,
    too_alike,
    stream_tail,
    wait_line,
    wants_address,
    plan_catalog,
    reset_plan_cache,
)
from sip import _private_ip, digest_response, normalize_dial, parse_auth_challenge, parse_message

ROOT = Path(__file__).resolve().parent
PLAN_FIXTURE = {
    "paymentReady": False,
    "plans": [
        {
            "id": "pro",
            "label": "پرو",
            "listPrice": 1_414_000,
            "price": 1_414_000,
            "features": ["یک فروشگاه", "خواندن دایرکت اینستاگرام", "پیش‌نویس پاسخ با لحن فروشنده"],
            "purchasable": True,
            "checkout": "open",
        },
        {
            "id": "promax",
            "label": "پرو مکس",
            "listPrice": 2_414_000,
            "price": 1_931_000,
            "features": ["پاسخ خودکار دایرکت با لحن فروشنده"],
            "purchasable": True,
            "checkout": "open",
        },
        {
            "id": "ultra",
            "label": "اولترا",
            "listPrice": 3_843_000,
            "price": 2_690_000,
            "features": ["تا ۲ فضای کاری کامل"],
            "purchasable": False,
            "checkout": "soon",
        },
    ],
}


class CodecTest(unittest.TestCase):
    def test_alaw_roundtrip_stays_close(self) -> None:
        src = array.array("h", [int(8000 * ((i % 40) - 20) / 20) for i in range(160)])
        encoded = encode_pcm16(src.tobytes(), "pcma")
        back = array.array("h")
        back.frombytes(decode_to_pcm16(encoded, "pcma"))
        err = sum(abs(a - b) for a, b in zip(src, back)) / len(src)
        self.assertLess(err, 200)

    def test_ulaw_roundtrip(self) -> None:
        src = array.array("h", [0, 100, -100, 4000, -8000])
        encoded = encode_pcm16(src.tobytes(), "pcmu")
        back = array.array("h")
        back.frombytes(decode_to_pcm16(encoded, "pcmu"))
        self.assertEqual(len(back), len(src))

    def test_resample_halves_rate(self) -> None:
        pcm = array.array("h", [100, 200] * 80).tobytes()
        out = resample_pcm16(pcm, 16000, 8000)
        self.assertAlmostEqual(len(out) // 2, 80, delta=2)

    def test_rms_and_rtp(self) -> None:
        pcm = array.array("h", [1000] * 160).tobytes()
        self.assertGreater(rms(pcm), 500)
        packet = rtp_packet(1, 160, 99, b"\xd5" * 160, marker=True, pt=8)
        parsed = rtp_parse(packet)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        pt, seq, payload = parsed
        self.assertEqual((pt, seq, len(payload)), (8, 1, 160))

    def test_gate_keeps_syllables_and_drops_a_tone(self) -> None:
        import math

        tone = array.array("h")
        for i in range(8000):
            tone.append(int(8000 * math.sin(2 * math.pi * 440 * i / 8000)))
        self.assertEqual(gate_kind(tone.tobytes()), "tone")
        speech = array.array("h")
        for block in range(6):
            for i in range(1600):
                speech.append(int(7000 * math.sin(2 * math.pi * (180 + block * 40) * i / 8000)))
            speech.extend([0] * 900)
        self.assertEqual(gate_kind(speech.tobytes()), "speech")

    def test_jitter_waits_and_hides_a_gap(self) -> None:
        jitter = PcmJitter(depth=3)
        self.assertEqual(jitter.push(2, b"b"), [])
        self.assertEqual(jitter.push(1, b"a"), [])
        ordered = jitter.push(3, b"c")
        self.assertEqual(ordered, [b"a", b"b", b"c"])
        self.assertEqual(jitter.push(5, b"e"), [])
        self.assertEqual(jitter.push(6, b"f"), [])
        concealed = jitter.push(7, b"g")
        self.assertEqual(concealed[0], b"c")
        self.assertEqual(concealed[1:], [b"e", b"f", b"g"])
        self.assertEqual(jitter.gaps, 1)


class DigestTest(unittest.TestCase):
    def test_rfc2617_vector(self) -> None:
        got = digest_response(
            username="Mufasa",
            password="Circle Of Life",
            realm="testrealm@host.com",
            nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093",
            method="GET",
            uri="/dir/index.html",
            qop="auth",
            nc="00000001",
            cnonce="0a4f113b",
        )
        self.assertEqual(got, "6629fae49393a05397450978507c4ef1")

    def test_parse_invite(self) -> None:
        raw = (
            "INVITE sip:673068@phone.telefonchy.com SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5099;branch=z9hG4bKtest\r\n"
            "From: <sip:caller@127.0.0.1>;tag=abc\r\n"
            "To: <sip:673068@phone.telefonchy.com>\r\n"
            "Call-ID: call-1\r\n"
            "CSeq: 1 INVITE\r\n"
            "Contact: <sip:caller@127.0.0.1:5099>\r\n"
            "Content-Type: application/sdp\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        msg = parse_message(raw.encode())
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertEqual(msg["headers"]["call-id"][0], "call-1")
        challenge = parse_auth_challenge(
            'Digest realm="phone.telefonchy.com", nonce="abc", algorithm=MD5, qop="auth"'
        )
        self.assertEqual(challenge["realm"], "phone.telefonchy.com")
        self.assertEqual(challenge["qop"], "auth")

    def test_private_contact_is_not_advertised(self) -> None:
        self.assertTrue(_private_ip("192.168.20.200"))
        self.assertTrue(_private_ip("10.1.1.1"))
        self.assertFalse(_private_ip("94.183.65.149"))

    def test_normalize_iran_mobile(self) -> None:
        self.assertEqual(normalize_dial("+989135409482"), "09135409482")
        self.assertEqual(normalize_dial("۰۹۱۳۵۴۰۹۴۸۲"), "09135409482")


class SpeechTest(unittest.TestCase):
    def test_speakable_keeps_one_sentence(self) -> None:
        text = speakable("سلام. فروشگاه را از چت بساز. این جملهٔ سوم نباید بیاید.")
        self.assertIn("سلام", text)
        self.assertNotIn("بساز", text)
        self.assertNotIn("سوم", text)

    def test_speech_and_bye(self) -> None:
        self.assertTrue(looks_like_speech("فروشگاه باز نمی‌شود"))
        self.assertFalse(looks_like_speech("[BLANK_AUDIO]"))
        self.assertFalse(looks_like_speech("بییییییی"))
        self.assertFalse(looks_like_speech("یا"))
        self.assertFalse(looks_like_speech("از " * 12))
        self.assertFalse(looks_like_speech("بیدیدیدیدیدیدیدیدیدیدیدی"))
        self.assertFalse(looks_like_speech("PYM JBZ"))
        self.assertTrue(is_carrier_text("PYM JBZ"))
        self.assertTrue(hold_early_carrier(True, False, 9))
        self.assertFalse(hold_early_carrier(True, True, 9))
        self.assertFalse(hold_early_carrier(True, False, 20))
        self.assertFalse(hold_early_carrier(False, False, 3))
        self.assertFalse(worth_llm("PYM JBZ"))
        self.assertFalse(worth_llm("سالون"))
        self.assertTrue(worth_llm("حالت خوبه"))
        self.assertTrue(is_howdy("حالت خوبه"))
        self.assertTrue(is_howdy("چطوری"))
        self.assertTrue(is_howdy("خوبی"))
        self.assertFalse(is_howdy("فروشگاه ساخته نشد"))
        self.assertFalse(wants_bye("آقای حافظ"))
        self.assertTrue(wants_bye("خداحافظ"))
        self.assertTrue(wants_bye("خدافه"))
        self.assertTrue(is_hello("سلام"))
        self.assertTrue(is_hello("الو"))
        self.assertTrue(is_hello("Allo"))
        self.assertTrue(is_hello("Allo Allo"))
        self.assertTrue(is_hello("hello"))
        self.assertTrue(is_hello("هلو"))
        self.assertTrue(is_hello("هالو"))

    def test_barge_in_accepts_speech_and_ignores_a_tone(self) -> None:
        self.assertTrue(barge_kind_ready(180, "speech"))
        self.assertFalse(barge_kind_ready(160, "speech"))
        self.assertFalse(barge_kind_ready(400, "tone"))
        self.assertFalse(barge_kind_ready(400, "music"))

    def test_echo_and_short_turn_helpers(self) -> None:
        import math

        sine = array.array("h", [int(8000 * math.sin(i / 8)) for i in range(160)]).tobytes()
        other = array.array("h", [int(8000 * math.sin(i / 3.1)) for i in range(160)]).tobytes()
        self.assertGreater(pcm_similarity(sine, sine), 0.99)
        self.assertLess(pcm_similarity(sine, other), 0.6)
        self.assertFalse(echo_should_block(4))
        self.assertTrue(echo_should_block(5))
        self.assertTrue(should_hold_fragment(1, 2))
        self.assertFalse(should_hold_fragment(0, 2))
        self.assertTrue(looks_like_echo("", "سلام، سوزانم."))
        self.assertTrue(looks_like_echo("سلام، سوزانم.", "سلام، سوزانم."))
        self.assertFalse(looks_like_echo("الو", "سلام، سوزانم."))
        self.assertTrue(any(name == "الو" for name, _samples in PHONE_PHRASES))
        rows = heard_rows()
        self.assertEqual(len(rows), 100)
        for canonical, train, holdout in rows:
            self.assertNotIn(holdout, train)
            self.assertNotEqual(holdout, canonical)
        self.assertFalse(should_repair("دایرکت چی", "دایرکت اینستاگرام را نمی‌خواند", 0.80))
        self.assertTrue(should_repair("سودان چیست", "سوزان چیست", 0.80))
        self.assertFalse(should_repair("گران اس", "گران است", 0.53))
        self.assertEqual(THINK_WAIT_S, 1.8)
        self.assertEqual(NUDGE_AFTER_S, 5.0)
        self.assertEqual(SALES_HANG_AFTER_S, 6.0)
        self.assertGreaterEqual(len(THINKING_LINES), 4)
        self.assertGreaterEqual(len(CURIOUS_LINES), 4)
        self.assertTrue(all(line.endswith("؟") for line in CURIOUS_LINES))
        self.assertTrue(SALES_PROBE_LINE.endswith("؟"))
        heard = ""
        index = 0
        spoken = []
        for _ in range(len(CURIOUS_LINES)):
            heard, index = next_varied(CURIOUS_LINES, index, heard)
            spoken.append(heard)
        self.assertEqual(len(spoken), len(set(spoken)))
        self.assertTrue(is_hello("سلام خوبی"))
        self.assertFalse(is_hello("سلام گفتم ولی فروشگاه ساخته نشد"))
        self.assertTrue(is_ack("باشه"))
        self.assertTrue(is_ack("ممنون"))
        self.assertFalse(is_ack("باشه فروشگاه"))
        self.assertTrue(is_repeat("چی گفتی"))
        self.assertTrue(is_repeat("متوجه نشدم"))
        self.assertFalse(is_repeat("نشنیدم کد ورود"))
        self.assertTrue(is_hold("یه لحظه"))
        self.assertTrue(is_who("اسمت چیه"))
        self.assertTrue(is_done("فروشگاه درست شد"))
        self.assertTrue(is_stuck("فایده نداشت"))
        self.assertTrue(is_correction("نه"))
        self.assertTrue(wants_bye("ممنون خداحافظ"))

    def test_spoken_lines_are_one_breath(self) -> None:
        for intent in INTENTS:
            self.assertTrue(intent.say)
            self.assertTrue(intent.again)
            self.assertNotEqual(intent.say, intent.again)
            self.assertLessEqual(len(intent.say), 90)
            self.assertNotIn("سی‌نیم", intent.say)
            self.assertNotIn("تب بیشتر", intent.say)

    def test_presence_and_rms_match(self) -> None:
        import math

        from audio_codec import match_rms_pcm16, presence_pcm16

        tone = array.array("h")
        for i in range(2205):
            tone.append(int(4000 * math.sin(2 * math.pi * 2000 * i / 22050)))
        boosted = presence_pcm16(tone.tobytes(), 22050, 1200, 3200, 5)
        self.assertGreater(rms(boosted), rms(tone.tobytes()))
        quiet = array.array("h", [800] * 8000).tobytes()
        matched = match_rms_pcm16(quiet, 7300)
        self.assertGreater(rms(matched), 4000)
        pcm = array.array("h", [8000, -8000, 0, 4000] * 200).tobytes()
        out = lowpass_pcm16(pcm, 22050, 3400)
        self.assertEqual(len(out), len(pcm))

    def test_ffmpeg_phone_chain_is_8k_and_unclipped(self) -> None:
        import math
        import os

        from audio_codec import pcm_stats
        from brain import amplify_pcm16, ffmpeg_bin

        if not ffmpeg_bin():
            self.skipTest("ffmpeg missing")
        os.environ["VOICE_CHAIN"] = "ffmpeg"
        os.environ["VOICE_PITCH"] = "1.0"
        tone = array.array("h")
        for i in range(22050):
            tone.append(int(8000 * math.sin(2 * math.pi * 220 * i / 22050)))
        out = amplify_pcm16(tone.tobytes(), gain=1.0, src_rate=22050)
        self.assertAlmostEqual(len(out) // 2, 8000, delta=80)
        stats = pcm_stats(out, 8000)
        self.assertEqual(stats["clips"], 0)
        self.assertGreater(stats["rms"], 1000)
        self.assertLess(stats["peak"], 32767)

    def test_analyze_tx_reports_a_mid_reply_gap(self) -> None:
        from audio_codec import analyze_tx_pcm

        speech = array.array("h", [4000] * 8000).tobytes()
        quiet = array.array("h", [0] * 4000).tobytes()
        stats = analyze_tx_pcm(speech + quiet + speech, 8000)
        self.assertGreaterEqual(int(stats["gaps_300ms"]), 1)
        self.assertGreaterEqual(int(stats["gap_ms_total"]), 300)

    def test_meaning_picks_the_closer_vector(self) -> None:
        index = MeaningIndex()
        index.add("explain", "درباره سوزان", [1.0, 0.0])
        index.add("shop", "فروشگاه", [0.0, 1.0])
        hit = index.best([0.9, 0.1])
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.name, "explain")
        self.assertGreater(hit.score, 0.9)
        self.assertFalse(usable_request("موسیقی"))
        self.assertFalse(usable_request("از اینجا موسیقی"))
        self.assertFalse(usable_request("با لان"))
        heard = clarify("میشه دواره سودان با من تازی بزید")
        self.assertIn("سوزان", heard)
        self.assertIn("توضیح", heard)
        self.assertTrue(usable_request(heard))


    def test_cloud_ear_keeps_only_verbatim_text(self) -> None:
        self.assertEqual(clean_ear_text("الو سلام"), "الو سلام")
        self.assertEqual(clean_ear_text("  «سلام، خوبید؟» "), "سلام، خوبید؟")
        self.assertEqual(clean_ear_text("لطفاً فایل صوتی را ارسال کنید تا رونویسی کنم."), "")
        self.assertEqual(clean_ear_text(""), "")
        self.assertEqual(clean_ear_text("x" * 400), "")

    def test_cloud_line_is_ready_without_the_local_model(self) -> None:
        from brain import Brain

        brain = Brain.__new__(Brain)
        brain.llm_url = "https://openrouter.ai/api/v1/chat/completions"
        brain.llm_model = "google/gemini-2.5-flash"
        self.assertTrue(brain.phone_ready())
        brain.llm_url = "http://127.0.0.1:19292/v1/chat/completions"
        brain.health = lambda: False
        self.assertFalse(brain.phone_ready())


class SalesTest(unittest.TestCase):
    def setUp(self) -> None:
        set_plans_fetcher(lambda: PLAN_FIXTURE)
        set_payment_fetcher(lambda: False)

    def tearDown(self) -> None:
        os.environ.pop("GIFT_CODE_SPOKEN", None)
        reset_plan_cache()

    def test_brief_names_the_shop_and_is_not_a_script(self) -> None:
        brief = sales_brief(ShopCard("kif_shop", "کیف چرم"))
        self.assertIn("سوزان هستی", brief)
        opened = sales_open()
        self.assertIn("آنلاین‌شاپ", opened)
        self.assertIn("وبسایت", opened)
        self.assertIn("استودیو", opened)
        self.assertIn("sozan-core.ir", opened)
        self.assertIn("ورود", opened)
        self.assertIn("شما", opened)
        self.assertIn("!", opened)
        self.assertNotIn("…", opened)
        self.assertIn("kif_shop", brief)
        self.assertIn("تعریف نکن", brief)
        self.assertNotIn("پیجت را دیدم", brief)
        for line in FIXED_SALES_LINES:
            self.assertNotIn(line, brief)
        self.assertTrue(sales_ended("ممنون خداحافظ", "چشم"))
        self.assertTrue(sales_ended("باشه خدا", "سوزانم."))
        self.assertFalse(sales_ended("سایتم هست", "کنار سایتت می‌ماند."))

    def test_sales_turns_listen_and_guard(self) -> None:
        self.assertEqual(sales_kind("اسم چیه"), "name")
        self.assertEqual(sales_kind("کارت چیه سوزان"), "what")
        self.assertEqual(sales_kind("برای چه مشاغلی به کار می ریزن"), "who")
        self.assertEqual(sales_kind("هزینه شو چجوری باید پرداخت کنم"), "cost")
        self.assertEqual(sales_kind("چه کارایی دیگه داری"), "more")
        self.assertEqual(sales_kind("عکس و فیلمم می سازی"), "studio")
        self.assertEqual(sales_kind("حالت خوبه سوزان"), "howdy")
        self.assertEqual(sales_kind("باشه خدا"), "bye")
        self.assertEqual(sales_kind("به حالت نون من"), "other")
        self.assertFalse(person_started("به حالت نون من"))
        self.assertFalse(person_started("چه خوشگله کنار"))
        self.assertTrue(person_started("بله"))
        self.assertTrue(person_started("بفرمایید"))
        self.assertTrue(person_started("سرم شلوغه سریع بگو"))
        self.assertTrue(person_started("شماره منو از کجا آوردید"))
        self.assertTrue(person_started("من مغازه ندارم اشتباه گرفتید"))
        wrong = plan_turn(SalesState(), "من مغازه ندارم اشتباه گرفتید")
        self.assertEqual(wrong.kind, "close")
        self.assertEqual(wrong.line, BYE_LINE)
        refused = SalesState()
        hello = plan_turn(refused, "سلام")
        self.assertEqual(hello.kind, "hello")
        self.assertIn(hello.line, GREET_VARIANTS)
        note_spoken(refused, hello.line)
        self.assertTrue(refused.greeted)
        no = plan_turn(refused, "لازم نیست ممنون نمیخوام")
        self.assertTrue(no.signals.refuse)
        gone = plan_turn(refused, "خداحافظ")
        self.assertEqual(gone.line, BYE_LINE)
        self.assertEqual(sales_kind("جونم سوزن چیه"), "what")
        self.assertEqual(sales_kind("توی کدوم پنل عکس بفرستم"), "where")
        self.assertEqual(sales_kind("باشه ممنون خدا"), "bye")
        self.assertFalse(should_repair("سلام سوزان", "سلام", 0.79))
        self.assertFalse(should_repair("خب اول سلام کن", "سلام", 0.76))
        self.assertFalse(should_repair("سوزان حالت چطوره", "سوزان چیست", 0.73))
        self.assertFalse(should_repair("معرفی کنید", "فقط معرفی کن", 0.77))
        self.assertNotIn("حسین", guard_reply("حسین، ساختن وبسایت پول نمی‌خواهد.", "هزینه شو چجوری باید پرداخت کنم"))
        self.assertNotIn("همین تماس", guard_reply("از همین تماس وارد پنل شو.", "چه پنلی"))
        self.assertFalse(wants_bye("باشه"))

    def test_sales_state_and_gift_rules(self) -> None:
        import os

        state = SalesState()
        hold = plan_turn(state, "ترایلی دارم")
        self.assertEqual(hold.kind, "hold")
        hello = plan_turn(state, "سلام")
        self.assertEqual(hello.kind, "hello")
        self.assertIn(hello.line, GREET_VARIANTS)
        self.assertNotIn("ورود", hello.line or "")
        note_spoken(state, hello.line)
        self.assertEqual(state.stage, "intro")
        later = plan_turn(state, "من آرایشگاه دارم")
        self.assertEqual(later.kind, "model")
        self.assertEqual(state.trade, "آرایشگاه")
        self.assertTrue(person_started("صحبت کن"))
        os.environ["GIFT_CODE_SPOKEN"] = "سوزان سی"
        state.stage = "cta"
        state.objection = "price"
        self.assertTrue(gift_allowed(state, read_signals("گرونه")))
        state.gifted = True
        self.assertFalse(gift_allowed(state, read_signals("گرونه")))
        self.assertIn("سوزان سی", gift_line())
        self.assertIn("براتون", gift_line())
        self.assertIn("تخفیف سایت", gift_line())
        self.assertNotIn("برات ", gift_line())
        os.environ.pop("GIFT_CODE_SPOKEN", None)
        self.assertEqual(gift_line(), "")
        self.assertFalse(gift_allowed(state, read_signals("گرونه")))
        self.assertIn("sozan-core.ir", CLOSE_LINE)
        self.assertIn("دایرکت", HELLO_LINE)
        self.assertIn("سفارش", HELLO_LINE)
        self.assertLessEqual(len(HELLO_LINE.split()), 18)
        self.assertNotIn("پیجت ", HELLO_LINE)
        self.assertNotIn("کور", ADDRESS_LINE)
        self.assertIn("کُر", ADDRESS_LINE)
        self.assertIn(ADDRESS_LINE, REPEAT_FREE)

    def test_address_intent_and_fallback(self) -> None:
        state = SalesState()
        opening = plan_turn(state, "سلام")
        note_spoken(state, opening.line)
        asked = plan_turn(state, "اسم سایتتون چیه")
        self.assertEqual(asked.kind, "address")
        self.assertEqual(asked.line, ADDRESS_LINE)
        self.assertTrue(wants_address("آدرس سایت چیه"))
        self.assertTrue(wants_address("از کجا شروع کنم"))
        self.assertFalse(wants_address("من اصلاً بلد نیستم سایت بسازم سخت نیست"))
        self.assertFalse(wants_address("از کجا اعتماد کنم درست کار می‌کنه"))
        self.assertTrue(too_alike(ADDRESS_LINE, ADDRESS_LINE))
        self.assertEqual(fallback_line(SalesState(), "چی"), MISHEARD_LINE)
        empty_state = SalesState()
        empty_state.linked = False
        self.assertEqual(fallback_line(empty_state, "چه کارایی انجام میدی"), ADDRESS_LINE)
        empty_state.linked = True
        self.assertIn("سؤال", fallback_line(empty_state, "چه کارایی انجام میدی"))
        self.assertEqual(wait_line("گرونه"), "حق دارید!")
        self.assertEqual(wait_line("اسم سایت چیه"), "سؤال خوبیه!")
        self.assertIn(wait_line("خب بگو"), WAIT_BRIGHT)
        note = SalesState(stage="confirm", linked=True).note()
        self.assertIn("تکرار نکن", note)
        self.assertIn("مسیر پیشنهادی این نوبت", note)
        long = "چه خوب مشتری‌ها دیگه لازم نیست دونه به دونه آدرس و شماره بگیرند و همه چیز ثبت می‌شود در فروشگاه."
        self.assertTrue(shorten_reply(long).endswith("فروشگاه."))
        self.assertGreater(len(shorten_reply(long).split()), 18)
        self.assertEqual(shorten_reply(" ".join(["کلمه"] * 22)), "")
        self.assertEqual(stream_tail("و اون پیش"), "")
        self.assertEqual(stream_tail("سلام، تمام شد."), "سلام، تمام شد.")
        self.assertNotIn("شماره بگیرید", guard_reply("مشتری‌ها باید شماره بگیرید از همه.", "چی کار می‌کنی"))
        self.assertIn("پیجتون", formalize_you("فقط اسم پیجت رو می‌نویسی"))
        self.assertIn("برید", formalize_you("برو sozan-core.ir"))
        self.assertIn("می‌زنید", formalize_you("دکمه ورود رو می‌زنی"))
        self.assertNotIn("پیجت ", formalize_you("پیجتون رو بنویسید"))
        self.assertTrue(wants_bye("فلحافظ"))
        missed_state = SalesState()
        opening_missed = plan_turn(missed_state, "سلام")
        note_spoken(missed_state, opening_missed.line)
        missed = plan_turn(missed_state, "")
        self.assertEqual(missed.kind, "fallback")
        pitched = SalesState()
        opening_pitched = plan_turn(pitched, "سلام")
        note_spoken(pitched, opening_pitched.line)
        note_spoken(pitched, "چه خوب، کیف می‌فروشید.")
        forced = plan_turn(pitched, "چجوری کار می‌کنه از کجا باید شروع کنم")
        self.assertEqual(forced.kind, "address")
        asked_job = SalesState()
        opening_job = plan_turn(asked_job, "سلام")
        note_spoken(asked_job, opening_job.line)
        thanks = plan_turn(asked_job, "ممنون خوبم شما چطورید")
        self.assertEqual(thanks.kind, "hello")
        self.assertIn(thanks.line, INTRO_VARIANTS)
        note_spoken(asked_job, thanks.line)
        perm = plan_turn(asked_job, "چی شده پس")
        self.assertIn(perm.line, PERM_VARIANTS)
        note_spoken(asked_job, perm.line)
        allowed = plan_turn(asked_job, "بله بگو")
        self.assertEqual(allowed.line, PAIN_LINE)
        note_spoken(asked_job, allowed.line)
        job = plan_turn(asked_job, "چه کارایی رو انجام میدی")
        self.assertEqual(job.kind, "model")
        where = plan_turn(asked_job, "پیجام کجا باید وارد کنم")
        self.assertEqual(where.kind, "address")
        self.assertEqual(where.line, ADDRESS_LINE)
        hard = plan_turn(asked_job, "از اون سخت سیباز باشه")
        self.assertEqual(hard.kind, "model")
        worried = SalesState()
        opening_worried = plan_turn(worried, "سلام")
        note_spoken(worried, opening_worried.line)
        trust = plan_turn(worried, "از کجا اعتماد کنم درست کار می‌کنه")
        self.assertEqual(trust.kind, "address")
        self.assertIn("حق دارید", trust.line or "")
        self.assertIn("sozan-core.ir", trust.line or "")
        cant = plan_turn(worried, "من اصلاً بلد نیستم سایت بسازم سخت نیست")
        self.assertEqual(cant.kind, "address")
        self.assertIn("لازم نیست", cant.line or "")
        self.assertIn("می‌ذارید", formalize_you("عکس غذاهاتون رو میذاری"))
        self.assertNotIn("رزرو", guard_reply("مشتری‌هاتون می‌تونن مستقیم از سایت رزرو کنن.", "آرایشگاه"))
        self.assertNotIn("کً", speakable("ساختنش کًلاً رایگانه 👌"))
        self.assertNotIn("👌", speakable("ساختنش کًلاً رایگانه 👌"))
        self.assertIn("اینستاگرام", speakable("مخصوص پیج‌های اینstagram فروشیه."))
        self.assertNotRegex(speakable("مخصوص پیج‌های اینstagram فروشیه."), r"[A-Za-z]")
        self.assertIn("اسمم", speakable("اسمن سوزان."))
        self.assertIn("یاسمن", speakable("یاسمن آمد."))
        masked = mask_messages(
            "https://openrouter.ai/api/v1",
            [{"role": "user", "content": "شماره من 09120000000 است"}],
        )
        self.assertNotIn("0912", masked[0]["content"])
        self.assertIn("شماره", masked[0]["content"])
        cloud = sales_request_body(
            "https://openrouter.ai/api/v1",
            "anthropic/claude-haiku-4.5",
            [{"role": "system", "content": "تو سوزانی"}, *masked],
        )
        self.assertEqual(cloud["temperature"], 0.6)
        self.assertEqual(cloud["max_tokens"], 70)
        self.assertEqual(cloud["provider"]["sort"], "latency")
        self.assertEqual(cloud["reasoning"]["effort"], "none")
        self.assertEqual(cloud["messages"][0]["content"][0]["cache_control"]["type"], "ephemeral")
        local = sales_request_body(
            "http://127.0.0.1:19292/v1",
            "ornith-phone",
            [{"role": "user", "content": "سلام"}],
        )
        self.assertEqual(local["max_tokens"], 120)
        self.assertNotIn("provider", local)
        self.assertTrue(chat_completions_url("http://127.0.0.1:19292/v1").endswith("/chat/completions"))
        quiet = b"\x00" * 320
        noisy = mix_shop_noise(quiet)
        self.assertEqual(len(noisy), 320)
        self.assertNotEqual(noisy, quiet)


    def test_sentence_split_keeps_short_commas(self) -> None:
        ready, rest = take_ready_sentences("سلام سوزانم. برو سایت")
        self.assertEqual(ready, ["سلام سوزانم."])
        self.assertIn("برو", rest)
        domain, rest = take_ready_sentences("برو sozan-core.ir، دکمهٔ ورود رو بزن.")
        self.assertTrue(domain)
        self.assertIn("sozan-core.ir", domain[0])
        self.assertNotEqual(domain[0], "برو sozan-core.")
        comma = "سایت رو خودم از کپشن‌های پیجتون می‌سازم، نوبتتون که رسید بروید"
        ready, rest = take_ready_sentences(comma)
        self.assertEqual(ready, [])
        self.assertIn("نوبتتون", rest)
        parts = split_sentences(comma)
        self.assertEqual(len(parts), 1)
        long = " ".join(["کلمه"] * 17) + "، ادامه."
        ready, rest = take_ready_sentences(long)
        self.assertTrue(ready)

    def test_sentence_split_and_repeat(self) -> None:
        ready, rest = take_ready_sentences("سلام سوزانم. برو سایت")
        self.assertEqual(ready, ["سلام سوزانم."])
        self.assertIn("برو", rest)
        domain, rest = take_ready_sentences("برو sozan-core.ir، دکمهٔ ورود رو بزن.")
        self.assertTrue(domain)
        self.assertIn("sozan-core.ir", domain[0])
        self.assertNotEqual(domain[0], "برو sozan-core.")
        parts = split_sentences("اولی تمام. دومی هم تمام.")
        self.assertEqual(len(parts), 2)
        self.assertTrue(too_alike("برو تو سایت سوزان کور و ورود رو بزن", "برو تو سایت سوزان کور و ورود را بزن"))
        state = SalesState()
        state.said = ["سوزان برای آنلاین‌شاپه و وبسایت می‌سازه."]
        spoken, tags = finish_spoken("سوزان برای آنلاین‌شاپه و وبسایت می‌سازه. [پایان]", state, "چیه")
        self.assertEqual(spoken, "")
        self.assertIn("end", tags)

    def test_campaign_keeps_the_phone_the_page_and_the_product(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "campaign.json"
            path.write_text(
                '{"targets":[{"phone":"۰۹۱۲۱۲۳۴۵۶۷","instagram":"@kif_shop","product":"کیف چرم","smsSent":true},{"phone":"","instagram":"x"}]}',
                encoding="utf-8",
            )
            found = load_campaign(path)
            self.assertEqual(found["09121234567"], ShopCard("kif_shop", "کیف چرم", True))
            self.assertTrue(found["09121234567"].sms_sent)
            self.assertEqual(load_campaign(path.with_name("missing.json")), {})

    def test_spoken_prices_match_the_catalog(self) -> None:
        self.assertEqual(toman_words(1_414_000), "یک میلیون و چهارصد و چهارده هزار")
        self.assertEqual(toman_words(1_931_000), "یک میلیون و نهصد و سی و یک هزار")
        self.assertEqual(toman_words(2_690_000), "دو میلیون و ششصد و نود هزار")
        opened = sales_open()
        self.assertIn("یک میلیون و چهارصد و چهارده هزار تومان", opened)
        self.assertIn("یک میلیون و نهصد و سی و یک هزار تومان", opened)
        self.assertIn("دو میلیون و چهارصد و چهارده هزار تومان", opened)
        self.assertIn("پاسخ خودکار", opened)
        self.assertIn("به‌زودی", opened)
        self.assertNotIn("فقط خواندن دایرکت", opened)
        kept = guard_reply("پرو یک میلیون و چهارصد و چهارده هزار تومان است.", "قیمت پرو چقدره")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", kept)
        promax = guard_reply("پرو مکس با تخفیف سایت یک میلیون و نهصد و سی و یک هزار تومان است.", "پرو مکس")
        self.assertIn("یک میلیون و نهصد و سی و یک هزار", promax)
        self.assertEqual(guard_reply("پرو چهارصد و نود هزار تومان است.", "قیمت"), "")
        self.assertEqual(guard_reply("قیمت 490000 تومان است.", "قیمت"), "")
        self.assertEqual(guard_reply("343000 تومان.", "قیمت"), "")

    def test_missing_catalog_quotes_no_price(self) -> None:
        def down():
            raise OSError("down")

        set_plans_fetcher(down)
        opened = sales_open()
        self.assertIn("قیمت هیچ پلنی را نگو", opened)
        self.assertNotIn("تومان", opened)
        self.assertEqual(guard_reply("پرو یک میلیون تومان است.", "قیمت"), "")

    def test_plan_catalog_is_cached_for_ten_minutes(self) -> None:
        import sales

        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return PLAN_FIXTURE

        set_plans_fetcher(fetch)
        self.assertIsNotNone(plan_catalog())
        self.assertIsNotNone(plan_catalog())
        self.assertEqual(calls["n"], 1)
        sales._plans_cached_at = time.monotonic() - 601
        self.assertIsNotNone(plan_catalog())
        self.assertEqual(calls["n"], 2)

    def test_campaign_example_uses_runner_keys(self) -> None:
        spec = json.loads((ROOT / "campaign.example.json").read_text(encoding="utf-8"))
        self.assertEqual(spec.get("source"), "instagram-shops")
        self.assertTrue(spec.get("contacts"))
        self.assertNotIn("targets", spec)

    def test_gift_uses_code_price_from_the_catalog(self) -> None:
        priced = json.loads(json.dumps(PLAN_FIXTURE))
        priced["plans"][0]["codePrice"] = 989_800
        set_plans_fetcher(lambda: priced)
        os.environ["GIFT_CODE_SPOKEN"] = "سوزان سی"
        line = gift_line()
        self.assertIn("نهصد و هشتاد و نه هزار و هشتصد", line)
        self.assertIn("تخفیف سایت", line)

    def test_price_question_speaks_the_catalog_amount(self) -> None:
        state = SalesState()
        hello = plan_turn(state, "سلام")
        self.assertEqual(hello.kind, "hello")
        note_spoken(state, HELLO_LINE)
        asked = plan_turn(state, "هزینه‌ش چقدره گرون نباشه")
        self.assertEqual(asked.kind, "address")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", asked.line or "")
        self.assertIn("رایگان", asked.line or "")
        self.assertLessEqual(len((asked.line or "").split()), 18)
        promax = plan_turn(SalesState(greeted=True, stage="discover"), "پرو مکس چقدر است")
        self.assertIn("یک میلیون و نهصد و سی و یک هزار", promax.line or "")
        self.assertLessEqual(len((promax.line or "").split()), 18)

        def down():
            raise OSError("down")

        set_plans_fetcher(down)
        missed = plan_turn(SalesState(greeted=True, stage="discover"), "قیمت پرو چقدره")
        self.assertNotIn("تومان", missed.line or "")
        self.assertIn("کُر", missed.line or "")

    def test_intro_asks_one_pain_and_sms_does_not_insist(self) -> None:
        for group in (GREET_VARIANTS, INTRO_VARIANTS, INTRO_SMS_VARIANTS, PERM_VARIANTS, NOTIME_VARIANTS):
            for line in group:
                self.assertLessEqual(len(line.split()), 18)
        for line in (HELLO_LINE, PAIN_LINE, DM_LINE, CONTENT_LINE, ORDER_LINE, SITE_LINE):
            self.assertLessEqual(len(line.split()), 18)
        opened = sales_open()
        self.assertIn("دستیار فروش", opened)
        self.assertIn("پرو مکس", opened)
        self.assertIn("لینک پرداخت داخل گفتگو را نگو", opened)
        self.assertIn("لغو است", opened)
        self.assertIn("اول به حرف مخاطب ربط", opened)
        self.assertIn("حدس نزن", opened)
        self.assertIn("از سوزان‌کُر", opened)
        self.assertIn("سه قدم", opened)
        set_payment_fetcher(lambda: True)
        self.assertIn("داخل همان گفتگو", sales_open())
        sms = SalesState(sms_sent=True)
        first = plan_turn(sms, "الو")
        self.assertEqual(first.kind, "hello")
        self.assertIn(first.line, GREET_VARIANTS)
        note_spoken(sms, first.line)
        second = plan_turn(sms, "ممنون خوبم شما چطورید")
        self.assertIn(second.line, INTRO_SMS_VARIANTS)
        self.assertIn("پیامک", second.line or "")
        note_spoken(sms, second.line)
        third = plan_turn(sms, "چی شده پس")
        self.assertIn(third.line, PERM_VARIANTS)
        self.assertNotIn("پیامک", third.line or "")
        note_spoken(sms, third.line)
        fourth = plan_turn(sms, "باشه بگو")
        self.assertEqual(fourth.line, PAIN_LINE)
        who = SalesState()
        who_greet = plan_turn(who, "الو")
        note_spoken(who, who_greet.line)
        identity = plan_turn(who, "تو کی هستی اصلاً")
        self.assertEqual(identity.kind, "model")
        busy_intro = SalesState()
        bi_greet = plan_turn(busy_intro, "الو")
        note_spoken(busy_intro, bi_greet.line)
        bi_busy = plan_turn(busy_intro, "الان وقت ندارم بعداً زنگ می‌زنم")
        self.assertIn(bi_busy.line, NOTIME_VARIANTS)
        self.assertEqual(busy_intro.stage, "discover")
        busy_state = SalesState()
        busy_greet = plan_turn(busy_state, "سلام")
        note_spoken(busy_state, busy_greet.line)
        busy_intro = plan_turn(busy_state, "سلام خوبید")
        note_spoken(busy_state, busy_intro.line)
        busy_perm = plan_turn(busy_state, "خوبه")
        note_spoken(busy_state, busy_perm.line)
        self.assertIn(busy_perm.line, PERM_VARIANTS)
        busy_no = plan_turn(busy_state, "الان سرم شلوغه")
        self.assertIn(busy_no.line, NOTIME_VARIANTS)
        site = plan_turn(SalesState(greeted=True, stage="pitch", pain_asked=True), "یه سایت می‌خوام")
        self.assertEqual(site.line, SITE_LINE)
        content = plan_turn(SalesState(greeted=True, stage="pitch", pain_asked=True), "استوری و کپشن")
        self.assertEqual(content.line, CONTENT_LINE)
        order = plan_turn(SalesState(greeted=True, stage="pitch", pain_asked=True), "سفارش‌ها رو کی پیگیری می‌کنه")
        self.assertEqual(order.line, ORDER_LINE)

    def test_gemini_flash_style_is_not_spoken(self) -> None:
        body = cloud_speech_body("google/gemini-3.8-flash-tts", "Kore", "سلام")
        self.assertEqual(body["input"], "سلام")
        self.assertEqual(body["voice"], "Kore")
        self.assertEqual(body["model"], "google/gemini-3.8-flash-tts")
        style = body["provider"]["options"]["google-ai-studio"]["speech_metadata"]["style"]
        self.assertIn("گرم", style)
        self.assertNotIn("گرم", body["input"])
        lines = cached_sales_lines()
        self.assertIn(HELLO_LINE, lines)
        self.assertIn(ADDRESS_LINE, lines)
        self.assertTrue(any("تومان" in line for line in lines))
        self.assertEqual(parse_sim_command("SIM"), ("", ""))
        self.assertEqual(parse_sim_command("SIM bag_shop کیف"), ("bag_shop", "کیف"))
        self.assertEqual(parse_sim_command("SIM @kif_shop"), ("kif_shop", ""))
        self.assertEqual(parse_sim_command("DIAL 0912"), ("", ""))
        self.assertEqual(parse_sim_command("sim gold طلا"), ("gold", "طلا"))


if __name__ == "__main__":
    unittest.main()
