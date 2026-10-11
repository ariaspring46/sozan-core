"""Unit tests for phone audio and SIP digest. No network."""

from __future__ import annotations

import array
import json
import tempfile
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
    HELLO_SMS_LINE,
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
        self.assertIn("تو سوزانی", brief)
        self.assertIn("هوش مصنوعی", brief)
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
        self.assertIn("بیو را از رو نخوان", brief)
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
        note_spoken(refused, HELLO_LINE)
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
        self.assertEqual(hello.line, HELLO_LINE)
        self.assertNotIn("ورود", HELLO_LINE)
        note_spoken(state, HELLO_LINE)
        later = plan_turn(state, "من آرایشگاه دارم")
        self.assertEqual(later.kind, "feature")
        self.assertEqual(later.line, PAIN_LINE)
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
        self.assertIn("هوش مصنوعی", HELLO_LINE)
        self.assertTrue(HELLO_LINE.endswith("؟"))
        self.assertLessEqual(len(HELLO_LINE.split()), 30)
        self.assertNotIn("پیجت ", HELLO_LINE)
        self.assertNotIn("کور", ADDRESS_LINE)
        self.assertIn("کُر", ADDRESS_LINE)
        self.assertIn(ADDRESS_LINE, REPEAT_FREE)

    def test_address_intent_and_fallback(self) -> None:
        state = SalesState()
        plan_turn(state, "سلام")
        note_spoken(state, HELLO_LINE)
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
        self.assertIn("کار این نوبت", note)
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
        plan_turn(missed_state, "سلام")
        note_spoken(missed_state, HELLO_LINE)
        missed = plan_turn(missed_state, "")
        self.assertEqual(missed.kind, "fallback")
        pitched = SalesState()
        plan_turn(pitched, "سلام")
        note_spoken(pitched, HELLO_LINE)
        note_spoken(pitched, "چه خوب، کیف می‌فروشید.")
        forced = plan_turn(pitched, "چجوری کار می‌کنه از کجا باید شروع کنم")
        self.assertEqual(forced.kind, "address")
        asked_job = SalesState()
        plan_turn(asked_job, "سلام")
        note_spoken(asked_job, HELLO_LINE)
        note_spoken(asked_job, "اسمم سوزانه.")
        job = plan_turn(asked_job, "چه کارایی رو انجام میدی")
        self.assertEqual(job.line, PAIN_LINE)
        again = plan_turn(asked_job, "چه کارایی رو انجام میدی")
        self.assertEqual(again.kind, "model")
        where = plan_turn(asked_job, "پیجام کجا باید وارد کنم")
        self.assertEqual(where.kind, "address")
        self.assertEqual(where.line, ADDRESS_LINE)
        hard = plan_turn(asked_job, "از اون سخت سیباز باشه")
        self.assertEqual(hard.kind, "model")
        worried = SalesState()
        plan_turn(worried, "سلام")
        note_spoken(worried, HELLO_LINE)
        trust = plan_turn(worried, "از کجا اعتماد کنم درست کار می‌کنه")
        self.assertEqual(trust.kind, "address")
        self.assertIn("حق دارید", trust.line or "")
        # An objection is acknowledged and reframed; the address is not pushed on every objection.
        self.assertIn("رایگان", trust.line or "")
        self.assertNotIn("sozan-core.ir", trust.line or "")
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
        for line in (DM_LINE, CONTENT_LINE, ORDER_LINE, SITE_LINE):
            self.assertLessEqual(len(line.split()), 20)
            self.assertTrue(line.endswith("؟"), line)
        for line in (HELLO_LINE, HELLO_SMS_LINE, PAIN_LINE):
            self.assertLessEqual(len(line.split()), 30)
        opened = sales_open()
        self.assertIn("دستیار فروش", opened)
        self.assertIn("پرو مکس", opened)
        self.assertIn("لینک پرداخت داخل گفتگو را نگو", opened)
        self.assertIn("جواب دایرکت", opened)
        set_payment_fetcher(lambda: True)
        self.assertIn("داخل همان گفتگو", sales_open())
        sms = SalesState(sms_sent=True)
        first = plan_turn(sms, "الو")
        self.assertEqual(first.line, HELLO_SMS_LINE)
        note_spoken(sms, HELLO_SMS_LINE)
        # The opening already introduced Sozan and asked permission: any reply gets the value line once.
        second = plan_turn(sms, "سلام")
        self.assertEqual(second.line, PAIN_LINE)
        self.assertNotIn("پیامک", second.line or "")
        note_spoken(sms, PAIN_LINE)
        third = plan_turn(sms, "دایرکت‌هام مونده")
        self.assertEqual(third.line, DM_LINE)
        site = plan_turn(SalesState(greeted=True, intro_said=True, pain_asked=True), "یه سایت می‌خوام")
        self.assertEqual(site.line, SITE_LINE)
        content = plan_turn(SalesState(greeted=True, intro_said=True, pain_asked=True), "استوری و کپشن")
        self.assertEqual(content.line, CONTENT_LINE)
        order = plan_turn(SalesState(greeted=True, intro_said=True, pain_asked=True), "سفارش‌ها رو کی پیگیری می‌کنه")
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


class OpeningAndProfileTest(unittest.TestCase):
    """Personal hook from the page bio, AI disclosure after it, permission, then a tailored value line."""

    def setUp(self) -> None:
        set_plans_fetcher(lambda: PLAN_FIXTURE)

    def tearDown(self) -> None:
        reset_plan_cache()

    def test_opening_hook_then_ai_disclosure_then_permission(self) -> None:
        import sales

        card = ShopCard("ava_bags", "کیف چرم", name="گالری کیف آوا", signals=("dm_orders",))
        opening = sales.hello_for(card)
        self.assertTrue(opening.startswith("سلام"))
        self.assertIn("گالری کیف آوا", opening)
        self.assertIn("از دایرکت", opening)
        self.assertIn("هوش مصنوعی", opening)
        self.assertLess(opening.index("گالری کیف آوا"), opening.index("هوش مصنوعی"))
        self.assertTrue(opening.endswith("؟"))
        self.assertLessEqual(len(opening.split()), 30)
        latin = sales.hello_for(ShopCard("ava_bags", "", name="Ava Bags"))
        self.assertNotRegex(latin, r"[A-Za-z]")
        self.assertIn("پیج اینستاگرامتون", latin)
        self.assertIn("کیف چرم کار می‌کنید", sales.hello_for(ShopCard("x", "کیف چرم")))
        self.assertEqual(sales.hello_for(None), HELLO_LINE)

    def test_permission_paths(self) -> None:
        import sales

        card = ShopCard("ava_bags", "کیف چرم", name="گالری کیف آوا", signals=("dm_orders",))

        def fresh() -> SalesState:
            state = SalesState(opening=sales.hello_for(card), value_line=sales.value_for(card))
            hello = plan_turn(state, "الو بفرمایید")
            self.assertEqual(hello.line, state.opening)
            note_spoken(state, hello.line)
            return state

        yes = plan_turn(fresh(), "بله بفرمایید")
        self.assertEqual(yes.line, sales.value_for(card))
        self.assertIn("دایرکت", yes.line or "")
        self.assertTrue((yes.line or "").endswith("؟"))
        busy = plan_turn(fresh(), "الان وقت ندارم سرم شلوغه")
        self.assertTrue(busy.hangup)
        self.assertEqual(busy.line, sales.BUSY_LINE)
        no = plan_turn(fresh(), "نمیخوام ممنون")
        self.assertTrue(no.hangup)
        self.assertEqual(no.line, sales.DECLINE_LINE)
        self.assertNotIn("sozan", no.line or "")
        robot_state = fresh()
        robot = plan_turn(robot_state, "شما رباتی؟")
        self.assertEqual(robot.line, sales.ROBOT_LINE)
        self.assertIn("هوش مصنوعی", robot.line or "")
        note_spoken(robot_state, robot.line or "")
        after = plan_turn(robot_state, "باشه بگو")
        self.assertEqual(after.line, sales.value_for(card))
        # The opening already offered DM replies: a yes about DMs hears how it works, not the offer again.
        pain = plan_turn(fresh(), "آره دایرکتام خیلی زیاده")
        self.assertEqual(pain.line, sales.DM_YES_LINE)
        self.assertNotEqual(pain.line, sales.DM_LINE)
        # A topic already pitched is never pitched again: their answer goes to the model.
        told = fresh()
        told.value_kind = "dm"
        note_spoken(told, plan_turn(told, "بگید").line or "")
        answered = plan_turn(told, "روزی پنجاه تا دایرکت دارم")
        self.assertEqual(answered.kind, "model")

    def test_brief_carries_bio_facts_not_raw_bio(self) -> None:
        card = ShopCard("ava_bags", "کیف چرم", name="گالری کیف آوا", city="تهران", signals=("ships", "physical"))
        brief = sales_brief(card)
        self.assertIn("گالری کیف آوا", brief)
        self.assertIn("تهران", brief)
        self.assertIn("به همهٔ شهرها ارسال دارد", brief)
        self.assertIn("مغازهٔ حضوری هم دارد", brief)
        self.assertIn("هوش مصنوعی", brief)

    def test_campaign_profile_is_loaded_and_whitelisted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "campaign.json"
            path.write_text(json.dumps({"source": "instagram-shops", "contacts": [
                {"phone": "09121234567", "instagram": "ava_bags", "product": "",
                 "profile": {"ok": True, "name": "گالری کیف آوا", "city": "تهران", "product": "کیف",
                             "signals": ["dm_orders", "hack"], "bio": "کیف چرم"}},
                {"phone": "09121234568", "instagram": "gone_page", "profile": {"ok": False}},
            ]}, ensure_ascii=False), encoding="utf-8")
            found = load_campaign(path)
        card = found["09121234567"]
        self.assertEqual(card.name, "گالری کیف آوا")
        self.assertEqual(card.signals, ("dm_orders",))
        self.assertEqual(card.product, "کیف")
        self.assertEqual(found["09121234568"].signals, ())

    def test_enrich_reads_bio_safely_offline(self) -> None:
        import enrich_campaign as enrich

        user = {
            "full_name": "گالری کیف آوا 👜",
            "biography": "👜 کیف چرم دست‌ساز\n📍تهران، پاساژ کوروش\nارسال به سراسر کشور\nسفارش فقط از دایرکت\n0912 123 4567\nwww.avabags.ir",
            "external_url": "https://avabags.ir",
        }
        profile = enrich.profile_from_user(user)
        self.assertEqual(profile["name"], "گالری کیف آوا")
        self.assertEqual(profile["city"], "تهران")
        self.assertNotIn("0912", profile["bio"])
        self.assertNotIn("4567", profile["bio"])
        self.assertNotIn("avabags", profile["bio"])
        self.assertEqual(set(profile["signals"]), {"dm_orders", "ships", "physical", "has_site", "handmade"})
        self.assertNotIn("has_site", enrich.bio_signals("سفارش", external_url="https://linktr.ee/x"))

        calls = []

        def fake_get(url, proxy):
            calls.append(url)
            if "rate_me" in url:
                return 429, b""
            return 200, json.dumps({"data": {"user": user}}).encode()

        spec = {"contacts": [
            {"phone": "09121111111", "instagram": "ava_bags"},
            {"phone": "09122222222", "instagram": "fresh_page", "profile": {"ok": True, "fetchedAt": "2999-01-01T00:00:00+00:00"}},
            {"phone": "09123333333", "instagram": "rate_me"},
            {"phone": "09124444444", "instagram": "never_reached"},
        ]}
        counts = enrich.enrich(spec, max_fetch=10, refresh_days=14, proxy="", get=fake_get, sleep=lambda _s: None)
        self.assertEqual(counts["ok"], 1)
        self.assertEqual(counts["rateLimited"], 1)
        self.assertTrue(spec["contacts"][0]["profile"]["ok"])
        self.assertNotIn("never_reached", " ".join(calls))
        self.assertFalse(any("fresh_page" in url for url in calls))
        self.assertIsNone(enrich.fetch_user("bad handle!", "", fake_get))



class SimFindingsTest(unittest.TestCase):
    """Fixes from the first simulated calls with the real model: busy callers, the robot question, prices, tools."""

    def setUp(self) -> None:
        set_plans_fetcher(lambda: PLAN_FIXTURE)
        set_payment_fetcher(lambda: False)

    def tearDown(self) -> None:
        reset_plan_cache()

    def opened(self, card: ShopCard | None = None) -> SalesState:
        import sales

        card = card or ShopCard("golnaz_hair", "رنگ مو")
        state = SalesState(opening=sales.hello_for(card), value_line=sales.value_for(card))
        hello = plan_turn(state, "الو بفرمایید")
        note_spoken(state, hello.line or "")
        return state

    def test_quick_first_words_get_the_short_version_with_ai_and_address(self) -> None:
        import sales

        state = SalesState()
        first = plan_turn(state, "سرم شلوغه سریع بگو")
        self.assertFalse(first.hangup)
        self.assertEqual(first.line, sales.QUICK_OPEN_LINE)
        self.assertIn("هوش مصنوعی", first.line or "")
        self.assertLessEqual(len((first.line or "").split()), 25)
        self.assertNotRegex(first.line or "", r"[A-Za-z]")
        note_spoken(state, first.line or "")
        self.assertTrue(state.linked)
        done = plan_turn(state, "باشه یادداشت کردم بعداً میام")
        self.assertTrue(done.hangup)

    def test_no_time_first_words_name_the_ai_and_leave(self) -> None:
        import sales

        busy = plan_turn(SalesState(), "الان وقت ندارم")
        self.assertTrue(busy.hangup)
        self.assertEqual(busy.line, sales.BUSY_OPEN_LINE)
        self.assertIn("هوش مصنوعی", busy.line or "")

    def test_quick_after_the_opening_is_short_not_a_hangup(self) -> None:
        import sales

        state = self.opened()
        quick = plan_turn(state, "سریع بگید چی می‌خواید")
        self.assertFalse(quick.hangup)
        self.assertEqual(quick.line, sales.QUICK_PITCH_LINE)
        self.assertLessEqual(len((quick.line or "").split()), 25)
        self.assertIn("کُر", quick.line or "")
        address = plan_turn(self.opened(), "آدرس سایت رو سریع بگو")
        self.assertEqual(address.line, ADDRESS_LINE)
        # "No time" is still a polite exit, not a pitch.
        self.assertTrue(plan_turn(self.opened(), "الان وقت ندارم").hangup)

    def test_robot_question_is_never_answered_with_the_same_sentence(self) -> None:
        import sales

        state = self.opened()
        first = plan_turn(state, "رباتی تو یا آدم واقعی")
        self.assertEqual(first.line, sales.ROBOT_LINE)
        note_spoken(state, first.line or "")
        second = plan_turn(state, "واقعی هستی یا ربات")
        self.assertEqual(second.line, sales.ROBOT_AGAIN_LINE)
        self.assertIn("هوش مصنوعی", second.line or "")
        self.assertNotEqual(first.line, second.line)
        note_spoken(state, second.line or "")
        third = plan_turn(state, "جدی رباتی؟")
        self.assertEqual(third.kind, "model")
        # After the call moved on, the honest answer does not ask permission again.
        moved = self.opened()
        note_spoken(moved, plan_turn(moved, "آدرس سایتتون چیه").line or "")
        late = plan_turn(moved, "شما رباتی؟")
        self.assertEqual(late.line, sales.ROBOT_AGAIN_LINE)
        self.assertNotIn("اجازه", late.line or "")
        self.assertNotIn("وقت دارید", late.line or "")

    def test_how_much_is_a_price_question_but_how_long_is_not(self) -> None:
        for heard in ("قیمتش چنده", "چقدره؟", "ماهی چقدر میشه", "چقدر می‌گیرید"):
            self.assertTrue(read_signals(heard).price, heard)
        self.assertFalse(read_signals("چقدر طول می‌کشه").price)
        asked = plan_turn(self.opened(), "خب چنده؟")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", asked.line or "")

    def test_missing_catalog_price_line_is_honest(self) -> None:
        import sales

        def down():
            raise OSError("down")

        set_plans_fetcher(down)
        missed = plan_turn(self.opened(), "قیمتش چنده")
        self.assertEqual(missed.line, sales.PRICE_UNKNOWN_LINE)
        self.assertNotRegex(missed.line or "", r"[0-9۰-۹]|تومان|میلیون|هزار")
        self.assertIn("رایگان", missed.line or "")

    def test_model_tools_are_tags_the_gateway_speaks(self) -> None:
        import sales

        text, tags = sales.extract_tags("حق دارید! [قیمت] [ آدرس ] [زنگ‌نزن] [پایان] [هدیه]")
        self.assertEqual(text, "حق دارید!")
        self.assertEqual(tags, {"price", "address", "dnc", "end", "gift"})
        state = self.opened()
        lines, end, dnc = sales.tool_followups({"price", "address"}, state, "خب", "حق دارید!")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", lines[0])
        self.assertEqual(lines[1], ADDRESS_LINE)
        self.assertFalse(end or dnc)
        said, _end, _dnc = sales.tool_followups({"address"}, state, "خب", ADDRESS_LINE)
        self.assertEqual(said, [])
        stop, end, dnc = sales.tool_followups({"dnc", "price"}, state, "دیگه زنگ نزنید", "")
        self.assertEqual(stop, [sales.DNC_LINE])
        self.assertTrue(end and dnc)
        self.assertNotIn("کُر", sales.DNC_LINE)

    def test_new_fixed_lines_are_prerendered_and_spoken_persian(self) -> None:
        import sales

        lines = cached_sales_lines()
        for line in (
            sales.ROBOT_LINE,
            sales.ROBOT_AGAIN_LINE,
            sales.QUICK_OPEN_LINE,
            sales.QUICK_PITCH_LINE,
            sales.BUSY_OPEN_LINE,
            sales.BUSY_LINE,
            sales.DECLINE_LINE,
            sales.PRICE_UNKNOWN_LINE,
        ):
            self.assertIn(line, lines)
            self.assertNotIn("پیجت ", line)
            self.assertNotIn("…", line)
        # synthesize() speaks at most three sentences: a fourth (the permission question) would be cut off.
        cards = [None, ShopCard("x", "کیف چرم", name="گالری کیف آوا", signals=("dm_orders",)), ShopCard("x", "", sms_sent=True)]
        spoken = lines + [sales.hello_for(card) for card in cards] + [sales.value_for(card) for card in cards]
        spoken.append(plan_turn(SalesState(), "قیمتش چنده").line or "")
        for line in spoken:
            self.assertEqual(speakable(line, 3), speakable(line, 9), line)



class ReviewFindingsTest(unittest.TestCase):
    """Cases found by reviewing the busy/robot/price/tool changes: each one failed before its fix."""

    def setUp(self) -> None:
        set_plans_fetcher(lambda: PLAN_FIXTURE)
        set_payment_fetcher(lambda: False)

    def tearDown(self) -> None:
        reset_plan_cache()

    def opened(self, card: ShopCard | None = None) -> SalesState:
        import sales

        card = card or ShopCard("x", "کیف")
        state = SalesState(opening=sales.hello_for(card), value_line=sales.value_for(card), value_kind=sales.value_kind_for(card))
        note_spoken(state, plan_turn(state, "الو بفرمایید").line or "")
        return state

    def test_greetings_are_not_busy_and_names_are_not_prices(self) -> None:
        for heard in ("الو سلام، بعدازظهر بخیر", "سلام، بعد‌ازظهرتون بخیر، بفرمایید", "الو، بله، پروانه هستم"):
            first = plan_turn(SalesState(), heard)
            self.assertEqual(first.kind, "hello", heard)
            self.assertFalse(first.hangup, heard)
        self.assertFalse(read_signals("الان نهار می‌خوریم").later)
        self.assertFalse(read_signals("آره، پروفایلمو دیدید؟").price)
        self.assertFalse(read_signals("چقدر می‌شه بهتون اعتماد کرد؟").price)
        self.assertTrue(read_signals("ماهی چقدر میشه").price)
        self.assertTrue(read_signals("ماهی چند تومنه؟").price)

    def test_quick_is_only_an_imperative_and_never_hides_a_real_answer(self) -> None:
        import sales

        for heard in ("خلاصه بگم، من خودم سایت دارم", "کوتاه بگم، اعتماد ندارم", "می‌خوام مشتری‌ها جوابشون رو سریع بگیرن"):
            self.assertFalse(read_signals(heard).quick, heard)
        source = plan_turn(self.opened(), "سریع بگو شماره منو از کجا آوردی")
        self.assertIn("پیج‌های فروشگاهی", source.line or "")
        for heard in ("عجله دارم بعداً زنگ بزنید", "خلاصه بگم، وقت ندارم"):
            self.assertTrue(plan_turn(self.opened(), heard).hangup, heard)
            self.assertTrue(plan_turn(SalesState(), heard).hangup, heard)
        priced = plan_turn(SalesState(), "سریع بگو قیمتش چنده")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", priced.line or "")
        self.assertIn("هوش مصنوعی", priced.line or "")
        self.assertNotEqual(priced.line, sales.QUICK_OPEN_LINE)

    def test_robot_with_price_gets_both_and_an_echo_is_a_yes(self) -> None:
        import sales

        both = plan_turn(self.opened(), "شما رباتی؟ قیمتش چنده؟")
        self.assertIn("هوش مصنوعی", both.line or "")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", both.line or "")
        state = self.opened()
        echo = plan_turn(state, "آره بگید، هوش مصنوعی جالبه")
        self.assertEqual(echo.line, state.value_line)
        self.assertTrue(read_signals("صدای ضبط‌شده‌ست؟").robot)
        self.assertTrue(read_signals("شما هوش مصنوعی هستی؟").robot)

    def test_do_not_call_in_other_words_ends_the_call(self) -> None:
        import sales

        for heard in ("لطفاً دیگه با این شماره تماس نگیرید", "مزاحم نشید دیگه", "شماره منو از لیستتون پاک کنید", "دیگه زنگ‌نزنید"):
            plan = plan_turn(self.opened(), heard)
            self.assertTrue(plan.hangup and plan.signals.wrong, heard)
            self.assertEqual(plan.line, sales.DNC_LINE, heard)
        asked = self.opened()
        note_spoken(asked, plan_turn(asked, "شماره منو از کجا آوردید").line or "")
        after = plan_turn(asked, "نه، نمی‌خوام")
        self.assertTrue(after.hangup and after.dnc)
        self.assertEqual(after.line, sales.DNC_LINE)
        linked = self.opened()
        note_spoken(linked, plan_turn(linked, "آدرس سایتتون چیه").line or "")
        bye = plan_turn(linked, "دیگه به من زنگ نزنید، خداحافظ")
        self.assertTrue(bye.signals.wrong)
        self.assertNotIn("کُر", bye.line or "")
        self.assertNotIn("sozan", bye.line or "")

    def test_tools_are_robust_to_the_models_wording(self) -> None:
        import sales

        lines, _end, _dnc = sales.tool_followups({"address"}, SalesState(), "خب", "فقط دکمهٔ ورود رو بزنید.")
        self.assertEqual(lines, [ADDRESS_LINE])
        self.assertFalse(sales.mentions_address("دکمهٔ ورود رو بزنید."))
        sorry, _end, dnc = sales.tool_followups({"dnc"}, SalesState(), "نه", "ببخشید که مزاحم شدم!")
        self.assertTrue(dnc)
        self.assertNotIn("ببخشید", sorry[0])
        text, tags = sales.extract_tags("[قيمت] شروعش رایگانه. [نیاز:قیمت]")
        self.assertEqual(tags, {"price"})
        self.assertNotIn("[", text)
        # A made-up colloquial price is dropped, and the tool still speaks the catalog line.
        self.assertEqual(guard_reply("پرو ماهی پونصد هزار تومنه!", "ماهی چند"), "")
        priced, _end, _dnc = sales.tool_followups({"price"}, SalesState(), "ماهی چند", "حق دارید!")
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", priced[0])

    def test_trailing_and_tag_only_replies_reach_the_gateway(self) -> None:
        import brain as brain_module

        class FakeStream:
            def __init__(self, pieces: list[str]) -> None:
                lines = [json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False) for piece in pieces]
                self.body = ("".join(f"data: {line}\n" for line in lines) + "data: [DONE]\n").encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

            def read(self, size: int) -> bytes:
                chunk, self.body = self.body[:size], self.body[size:]
                return chunk

        brain = Brain.__new__(Brain)
        original = brain_module.open_llm
        try:
            brain_module.open_llm = lambda *_args, **_kw: FakeStream(["چشم، ممنون! ", "خوشحال شدم. ", "روزتون خوش. [پایان]"])
            bits = list(brain._sales_events("http://127.0.0.1:1/v1/chat/completions", "m", [], None, time.monotonic()))
            self.assertIn("[پایان]", bits[-1]["raw"])
            brain_module.open_llm = lambda *_args, **_kw: FakeStream(["[زنگ‌نزن]"])
            bits = list(brain._sales_events("http://127.0.0.1:1/v1/chat/completions", "m", [], None, time.monotonic()))
            self.assertEqual(bits[-1]["sentence"], "")
            self.assertIn("[زنگ‌نزن]", bits[-1]["raw"])
        finally:
            brain_module.open_llm = original

    def test_page_names_ships_pitch_and_objection_notes(self) -> None:
        import sales

        odd = ShopCard("x", "کیف؟ کفش", name="چی بپوشم؟", signals=("dm_orders",))
        opening = sales.hello_for(odd)
        self.assertEqual(speakable(opening, 3), speakable(opening, 9))
        self.assertIn("هوش مصنوعی", speakable(opening, 3))
        ships = self.opened(ShopCard("x", "کیف", signals=("ships",)))
        note_spoken(ships, plan_turn(ships, "بله بگید").line or "")
        again = plan_turn(ships, "با یه سایت دیگه می‌فروشیم")
        self.assertNotEqual(again.line, sales.SITE_LINE)
        state = self.opened()
        note_spoken(state, plan_turn(state, "قیمتش چنده").line or "")
        state.pain_asked = True
        later = plan_turn(state, "لحن منو از کجا یاد می‌گیری؟")
        self.assertNotIn("[قیمت]", later.cue)
        refuse = plan_turn(state, "نه بابا، بعداً هم نمی‌خوام")
        self.assertIn("[پایان]", refuse.cue)
        self.assertNotIn("آدرس sozan", refuse.cue)



class SecondReviewTest(unittest.TestCase):
    """Second to fourth review rounds of the phone marketer change: each case failed before its fix."""

    def setUp(self) -> None:
        set_plans_fetcher(lambda: PLAN_FIXTURE)
        set_payment_fetcher(lambda: False)

    def tearDown(self) -> None:
        reset_plan_cache()

    def opened(self) -> SalesState:
        import sales

        card = ShopCard("x", "کیف")
        state = SalesState(opening=sales.hello_for(card), value_line=sales.value_for(card), value_kind=sales.value_kind_for(card))
        note_spoken(state, plan_turn(state, "الو بفرمایید").line or "")
        return state

    def valued(self) -> SalesState:
        state = self.opened()
        note_spoken(state, plan_turn(state, "بله بگید").line or "")
        return state

    def test_punctuation_does_not_hide_words(self) -> None:
        import sales

        self.assertEqual(plan_turn(self.opened(), "الان نه، ممنون").line, sales.BUSY_LINE)
        for heard in ("خب چقدر میشه؟", "کلاً چقدر درمیاد؟", "پرو؟"):
            self.assertTrue(read_signals(heard).price, heard)
        self.assertEqual(plan_turn(self.opened(), "سریع بگید، وقت کمه").line, sales.QUICK_PITCH_LINE)

    def test_dnc_wordings_and_polite_lookalikes(self) -> None:
        import sales

        for heard in (
            "شماره‌مو پاک کنید",
            "شمارمو حذف کنید",
            "منو از لیست حذف کنید",
            "شماره منو حذف کنید لطفاً",
            "نمی‌خوام دیگه بهم زنگ بزنید",
        ):
            plan = plan_turn(self.opened(), heard)
            self.assertTrue(plan.dnc and plan.hangup, heard)
            self.assertEqual(plan.line, sales.DNC_LINE, heard)
            self.assertTrue(plan_turn(SalesState(), heard).dnc, heard)
        for heard in ("نه بابا مزاحم نشدید، بفرمایید", "شما از لیستتون زنگ زدید؟"):
            plan = plan_turn(self.opened(), heard)
            self.assertFalse(plan.dnc or plan.hangup, heard)

    def test_pain_answers_are_not_busy_or_goodbye(self) -> None:
        import sales

        yes = plan_turn(self.opened(), "آره بگید، من اصلاً وقت ندارم به دایرکتا برسم")
        self.assertFalse(yes.hangup)
        self.assertEqual(yes.line, sales.DM_YES_LINE)
        for heard in ("راستش وقت ندارم به همه‌شون جواب بدم", "فعلاً خودم جواب می‌دم", "تمام روز خودم پای گوشی‌ام"):
            plan = plan_turn(self.valued(), heard)
            self.assertFalse(plan.hangup, heard)
            self.assertNotIn("[پایان]", plan.cue, heard)
        for heard in ("باشه فعلاً", "فعلاً با اجازه", "همین، تمام"):
            self.assertTrue(wants_bye(heard), heard)
        self.assertEqual(plan_turn(SalesState(), "الو، فعلاً سرم شلوغه").line, sales.BUSY_OPEN_LINE)

    def test_robot_questions_with_yes_words_get_the_ai_answer(self) -> None:
        import sales

        for heard in ("جالبه، هوش مصنوعی‌ای یا آدم؟", "بله؟ هوش مصنوعی؟", "یعنی تو هوش مصنوعی هستی؟ بگو ببینم"):
            self.assertEqual(plan_turn(self.opened(), heard).line, sales.ROBOT_LINE, heard)
        self.assertFalse(read_signals("آره بگید، هوش مصنوعی جالبه").robot)
        for heard in ("رباتی؟ نه نمی‌خوام", "آدمی یا ربات؟ اگه رباتی لازم نیست"):
            plan = plan_turn(self.opened(), heard)
            self.assertTrue(plan.hangup, heard)
            self.assertIn("هوش مصنوعی", plan.line or "", heard)
        both = plan_turn(self.valued(), "رباتی؟ خب آدرس سایتتون چیه؟")
        self.assertEqual(both.line, f"{sales.ROBOT_SHORT} {ADDRESS_LINE}")

    def test_interested_questions_are_not_refusals_or_busy(self) -> None:
        import sales

        first = plan_turn(SalesState(), "سلام، ساختش چقدر طول می‌کشه؟")
        self.assertEqual(first.kind, "hello")
        self.assertFalse(plan_turn(self.opened(), "چقدر طول می‌کشه تا آماده بشه؟").hangup)
        for heard in ("یعنی لازم نیست کاری بکنم؟", "فروشگاه نمی‌خوام، فقط دایرکت‌هام مهمه", "پول زیادی نمی‌خوام بدم، چی داره؟", "لازم نیست تکرار کنید"):
            self.assertFalse(read_signals(heard).refuse, heard)
        asked = self.opened()
        note_spoken(asked, plan_turn(asked, "شماره منو از کجا آوردید").line or "")
        note_spoken(asked, "سؤال خوبیه!")
        self.assertFalse(plan_turn(asked, "یعنی لازم نیست کاری بکنم؟").dnc)
        linked = self.valued()
        note_spoken(linked, ADDRESS_LINE)
        self.assertNotEqual(plan_turn(linked, "من تو سایت نمی‌رم، شما برام بسازید").line, CLOSE_LINE)
        self.assertFalse(read_signals("نمی‌دونم، بگید").cant)
        for heard in ("ماهانه چقدر پول باید بدم", "هزینه‌ش پول زیادیه؟"):
            self.assertTrue(read_signals(heard).price, heard)
        self.assertEqual(plan_turn(SalesState(), "سرم شلوغه ولی بگید").line, sales.QUICK_OPEN_LINE)

    def test_plain_no_and_busy_wordings(self) -> None:
        import sales

        for heard in ("نه ممنون", "نه مرسی", "نه، نیازی نیست", "نه، علاقه‌ای ندارم", "نه"):
            plan = plan_turn(self.opened(), heard)
            self.assertEqual(plan.line, sales.DECLINE_LINE, heard)
            self.assertTrue(plan.hangup, heard)
        for heard in ("الان نمی‌تونم صحبت کنم", "تو جلسه‌ام", "الان درگیرم", "بعدازظهر زنگ بزنید"):
            self.assertEqual(plan_turn(self.opened(), heard).line, sales.BUSY_LINE, heard)
        self.assertEqual(plan_turn(SalesState(), "الو سلام، بعدازظهر بخیر").kind, "hello")
        self.assertEqual(plan_turn(SalesState(), "نه ممنون، لازم نیست، خداحافظ").line, sales.DECLINE_LINE)
        busy = plan_turn(self.valued(), "سرم شلوغه")
        self.assertIn("[آدرس]", busy.cue)
        self.assertNotIn("دعوت سایت نکن", busy.cue)

    def test_first_words_objection_is_answered_after_the_ai_line(self) -> None:
        import sales

        for heard in ("سریع بگو شماره منو از کجا آوردی", "الو سریع بگو من بلد نیستم"):
            plan = plan_turn(SalesState(), heard)
            self.assertTrue((plan.line or "").startswith(sales.FIRST_DISCLOSE), heard)
            self.assertNotEqual(plan.line, sales.QUICK_OPEN_LINE, heard)
        state = SalesState()
        note_spoken(state, plan_turn(state, "سلام، کلاهبرداری نیست؟").line or "")
        self.assertEqual(plan_turn(state, "کلاهبرداری نیست این؟ از کجا معلوم").kind, "model")

    def test_spoken_lines_and_prompt_stay_honest(self) -> None:
        import sales

        for line in (sales.BUSY_LINE, sales.BUSY_OPEN_LINE):
            self.assertNotIn("رایگان", line)
        self.assertTrue(sales.mentions_address("برید سوزان کر دات آی آر"))
        self.assertFalse(sales.mentions_address("گوشم کر شد"))
        for reply in ("پرو ماهی پونصد هزاره.", "پرو ماهی ۵۰۰ هزاره.", "من سال‌ها تجربهٔ فروش دارم.", "با تجربهٔ بیست‌ساله‌م می‌گم."):
            self.assertEqual(guard_reply(reply, "چنده"), "", reply)
        self.assertEqual(guard_reply("روزی هزار تا دایرکت جواب می‌دیم.", "خب"), "روزی هزار تا دایرکت جواب می‌دیم.")
        for row in sales_open().splitlines():
            if row.startswith("مشتری:") and "→" in row:
                said, _tags = sales.extract_tags(row.split("→", 1)[1])
                self.assertLessEqual(len(split_sentences(said)), 2, row)
        for line in cached_sales_lines():
            self.assertEqual(speakable(line, 3), speakable(line, 9), line)

    def test_trailing_tag_closes_an_unpunctuated_sentence(self) -> None:
        self.assertEqual(stream_tail("ممنون از وقتتون [پایان]"), "ممنون از وقتتون [پایان]")
        self.assertEqual(stream_tail("خدمتتون عرض کنم که [پایان]"), "")
        self.assertEqual(stream_tail("ممنون از وقتتون"), "")

    def test_busy_dnc_and_refusal_wordings_without_false_hits(self) -> None:
        import sales

        for heard in ("کل روز درگیرم با دایرکتا", "اگه مشتری شب زنگ بزنه کی جواب میده؟", "وقت ندارم دایرکتا رو جواب بدم", "خودم وقت ندارم، شوهرم جواب میده"):
            self.assertFalse(plan_turn(self.opened(), heard).hangup, heard)
        for heard in ("الو سلام، تو جلسه‌ام ولی بگید", "وقت ندارم، سریع بگو"):
            self.assertEqual(plan_turn(SalesState(), heard).line, sales.QUICK_OPEN_LINE, heard)
        self.assertEqual(plan_turn(self.opened(), "بعداً زنگ بزنید، سریع بگید").line, sales.BUSY_LINE)
        for heard in ("فعلاً نه", "فعلاً نه، ممنون", "عصر زنگ بزنید"):
            self.assertEqual(plan_turn(self.opened(), heard).line, sales.BUSY_LINE, heard)
        for heard in ("یعنی پیامای منو پاک کنه؟", "تموم که شد از لیست پاکش می‌کنم", "من نمی‌خوام خودم به مشتریا زنگ بزنم", "اگه مشتری زنگ نزنه چی"):
            self.assertFalse(read_signals(heard).dnc, heard)
        for heard in ("منو از لیستتون خارج کنید", "منو از لیستتون در بیارید", "دیگه زنگم نزنید", "میشه شماره منو پاک کنید؟"):
            self.assertTrue(read_signals(heard).dnc, heard)
        for heard in ("نه، ممنون", "نخیر، ممنون", "نمی‌خوام، ولی ممنون", "نه نمی‌خوام، فقط وقتمو گرفتی", "نمی‌خوامش"):
            self.assertEqual(plan_turn(self.opened(), heard).line, sales.DECLINE_LINE, heard)
        # The first words asked where the number came from: «نمی‌خوام» next holds Sozan to "we won't call again".
        state = SalesState()
        note_spoken(state, plan_turn(state, "شماره منو از کجا آوردید").line or "")
        self.assertTrue(plan_turn(state, "نه نمی‌خوام").dnc)
        self.assertEqual(plan_turn(SalesState(), "الو، صداتون نمیاد، سخته بشنوم").kind, "hello")

    def test_fourth_round_wordings(self) -> None:
        import main as main_module
        import sales

        for heard in (
            "منو از لیست‌تون حذف کنید",
            "منو از لیست بردارید",
            "لطفاً منو از لیست مخاطبینتون حذف کنید",
            "می‌خوام از لیست حذف بشم",
            "اسممو پاک کنید",
            "منو حذف کنید از لیستتون",
            "دیگه زنگ نزنی",
            "دیگه تماس نگیری",
            "شمارمو پاکش کنید",
        ):
            self.assertTrue(read_signals(heard).dnc, heard)
        self.assertFalse(read_signals("عکسای منو حذف کنی چی میشه").dnc)
        sourced = self.opened()
        note_spoken(sourced, plan_turn(sourced, "شماره منو از کجا آوردید").line or "")
        for heard in ("نمی‌خوام، ولی آدرستون چیه؟", "نه ممنون، ولی رایگانه؟", "نه، ممنون می‌شم بیشتر توضیح بدید"):
            self.assertFalse(read_signals(heard).refuse, heard)
        self.assertFalse(plan_turn(sourced, "لازم ندارم، ولی آدرستونو بدید").dnc)
        self.assertFalse(plan_turn(self.opened(), "آره بگید، فعلاً نه سایت دارم نه فروشگاه").hangup)
        for heard in ("الو، وقت ندارم، مشتری دارم", "سلام، الان نمی‌تونم صحبت کنم، پیام بدید", "تو جلسه‌ام، بعد بگید", "پشت فرمونم، فردا بگید"):
            self.assertEqual(plan_turn(self.opened(), heard).line, sales.BUSY_LINE, heard)
        self.assertTrue(plan_turn(SalesState(), "سلام، از كجا معلوم كلاهبرداری نيستين؟").line.startswith(sales.FIRST_DISCLOSE))
        for reply in ("پلنش دو میلیونه.", "پولش پونصد هزاره.", "سالیانه دو میلیون می‌شه."):
            self.assertEqual(guard_reply(reply, "خب"), "", reply)
        self.assertFalse(main_module.late_echo("درسته، ولی دیگه به من زنگ نزنید", ["درسته!"]))
        self.assertTrue(main_module.late_echo("جواب دایرکت‌ها رو من با لحن خودتون می‌نویسم", ["جواب دایرکت‌ها رو من با لحن خودتون می‌نویسم!"]))

    def test_counts_and_cut_off_replies(self) -> None:
        for reply in ("ماهی هزار تا سفارش، یعنی حسابی سرتون شلوغه!", "به هزار تا شهر ارسال دارید؟"):
            self.assertEqual(guard_reply(reply, "خب"), reply)
        self.assertEqual(guard_reply("پلنش سالی دو میلیونه.", "خب"), "")
        for tail in ("[آدرس] اگه سؤالی داشتید، من", "عالیه! [آدرس] [پای", "عالیه [آدرس] همین امروز ثبت"):
            self.assertEqual(stream_tail(tail), "", tail)

    def test_gateway_keeps_dnc_and_late_words(self) -> None:
        import queue
        import threading

        import main as main_module
        import sales

        saved: list[str] = []

        class Session:
            def __init__(self) -> None:
                self.playing = threading.Event()
                self._play = queue.Queue()
                self._speech = False
                self.last_was_barge = False
                self.played: list[str] = []

            def play(self, pcm: bytes, end: bool = False) -> None:
                if pcm:
                    self.played.append(pcm.decode("utf-8"))

            def wait_done(self, _seconds: float) -> None:
                pass

        class Voice:
            def __init__(self, replies: list[str]) -> None:
                self.replies = list(replies)

            def commit_assistant(self, _text: str) -> None:
                pass

            def pop_last_user(self) -> None:
                pass

            def synthesize(self, text: str, cloud: bool = True) -> tuple[bytes, float]:
                return text.encode("utf-8"), 0.0

            def sales_stream(self, _cue: str, _cancel=None):
                # Like brain._sales_events: an unfinished piece reaches the gateway only as raw text.
                for piece in self.replies.pop(0).split("|"):
                    said = piece if sales.sentence_done(piece) else sales.stream_tail(piece)
                    yield {"sentence": said, "raw": piece}

        class Phone:
            hung = False

            def hangup(self) -> None:
                Phone.hung = True

        def gateway(state: SalesState, replies: list[str], pending: list[str]):
            gw = main_module.Gateway.__new__(main_module.Gateway)
            gw._sales, gw._voice, gw.brain, gw.ua = state, {}, Voice(replies), Phone()
            gw._peer_number, gw._sales_turn_seq, gw._last_kind = "09120000000", 0, "wait"
            gw._call_generation, gw._sales_cancel, gw._sim_call = 1, None, True
            gw._last_line, gw._spoke_at, gw._step = "", 0.0, False
            gw._pending_heard = lambda _session: pending.pop(0) if pending else ""
            gw._end_call = lambda _call: setattr(gw, "_peer_number", "")
            gw._ahead_sales = lambda gen, _cancel, _generation: gen
            gw._log_sales_turn = lambda *_args, **_kw: None
            return gw

        original = main_module.remember_dnc
        main_module.remember_dnc = saved.append
        try:
            # «زنگ نزنید» said while the model was thinking: its own goodbye, and the number is saved.
            session = Session()
            gateway(self.valued(), ["الان براتون می‌گم.|بیشتر بگم؟"], ["", "نه، زنگ نزنید"])._sales_speak(session, 1, "خب، بیشتر بگید")
            self.assertEqual(session.played, [sales.DNC_LINE])
            self.assertEqual(saved, ["09120000000"])
            # Said over the first sentence: the next turn, not noise.
            saved.clear()
            session = Session()
            gateway(self.valued(), ["آهان، پس دایرکت زیاده!|الان کی جواب می‌ده؟"], ["", "", "زنگ نزنید دیگه"])._sales_speak(
                session, 1, "جالبه، بیشتر توضیح بدید"
            )
            self.assertEqual(session.played[-1], sales.DNC_LINE)
            self.assertEqual(saved, ["09120000000"])
            # A refusal answered with only [پایان] still gets thanks and ends the call.
            session = Session()
            Phone.hung = False
            gateway(self.valued(), ["[پایان]"], [])._sales_speak(session, 1, "نه ممنون، نیازی ندارم")
            self.assertEqual(session.played, [sales.DECLINE_LINE])
            self.assertTrue(Phone.hung)
            # The number is written before the goodbye plays, so hanging up during it loses nothing.
            saved.clear()
            gw = gateway(self.opened(), [], [])
            speak = gw._speak

            def hang_up_while_speaking(*args, **kwargs) -> None:
                gw._peer_number = ""
                speak(*args, **kwargs)

            gw._speak = hang_up_while_speaking
            gw._sales_speak(Session(), 1, "زنگ نزنید لطفاً")
            self.assertEqual(saved, ["09120000000"])
            # A cut-off reply is never spoken; the closing line ends the call instead.
            session = Session()
            gateway(self.valued(), ["خدمتتون عرض کنم که [پایان]"], [])._sales_speak(session, 1, "جالبه، بیشتر توضیح بدید")
            self.assertEqual(session.played, [CLOSE_LINE])
            # The line's own echo heard over the first sentence is not the caller's next turn.
            session = Session()
            echo = "جواب دایرکت‌ها رو من با لحن خودتون می‌نویسم!"
            gateway(self.valued(), [f"{echo}|الان کی جواب می‌ده؟"], ["", "", echo.rstrip("!")])._sales_speak(
                session, 1, "جالبه، بیشتر توضیح بدید"
            )
            self.assertEqual(session.played, [echo])
        finally:
            main_module.remember_dnc = original


class LiveSimTest(unittest.TestCase):
    """Live persona run on the home machine (real speech-to-text and model): each case failed before its fix."""

    def setUp(self) -> None:
        set_plans_fetcher(lambda: PLAN_FIXTURE)

    def opened(self) -> SalesState:
        import sales

        card = ShopCard("yasaman_kids", "اسباب‌بازی")
        state = SalesState(opening=sales.hello_for(card), value_line=sales.value_for(card))
        note_spoken(state, plan_turn(state, "الو بفرمایید").line or "")
        return state

    def test_refusal_written_with_a_space(self) -> None:
        import sales

        # Speech-to-text wrote «نمی خوام» with a plain space; the pitch went on after a clear no.
        for heard in ("لازم نیست ممنون نمی خوام", "نمی خوام", "نمی خوام ممنون", "نمی‌خواهم", "نمیخوایم"):
            self.assertTrue(read_signals(heard).refuse, heard)
        plan = plan_turn(self.opened(), "لازم نیست ممنون نمی خوام")
        self.assertEqual((plan.line, plan.hangup), (sales.DECLINE_LINE, True))
        self.assertFalse(read_signals("نمی خوام تا نصف شب بیدار بمونم").refuse)
        self.assertFalse(read_signals("فروشگاه نمی خوام، فقط دایرکت‌هام مهمه").refuse)
        self.assertFalse(read_signals("نه، ممنون می شم توضیح بدید").refuse)
        self.assertTrue(read_signals("دیگه نمی خوام زنگ بزنید").dnc)
        self.assertTrue(read_signals("الان نمی تونم صحبت کنم").later)

    def test_review_of_the_live_fix(self) -> None:
        import sales

        # Arabic letters from speech-to-text, plural and formal verbs, and «...م کنید» are a no or a DNC as well.
        for heard in ("نمي خوام", "نمي‌خوام", "لازم نداریم", "نه لازم نداریم ممنون", "علاقه‌ای نداریم", "نه نمی خواد ممنون", "نمی خوام ممنونم", "نه، خیلی ممنونم"):
            self.assertTrue(read_signals(heard).refuse, heard)
        for heard in ("نمي خوام ديگه زنگ بزنيد", "نمی خوایم دیگه زنگ بزنید", "نمی‌خواهم دیگر با من تماس بگیرید", "نمی‌خوام دیگه هیچوقت زنگ بزنید", "سلام، لازم نیست. حذفم کنید"):
            self.assertTrue(read_signals(heard).dnc, heard)
            self.assertTrue(plan_turn(SalesState(), heard).dnc, heard)
        # A denied no is not a no.
        self.assertEqual(plan_turn(self.opened(), "نه اینکه نمی خوام، الان سرم شلوغه").line, sales.BUSY_LINE)
        # «X نمی‌خواد»، «دیگه منشی لازم نداریم» and «مگه ... نمی‌خوایم» are a yes or the seller's own pain; a polite
        # call-back is not a DNC; and talk about their own orders, numbers or photos is not about this call.
        for heard in (
            "اجازه نمی‌خواد",
            "آره، توضیح نمی‌خواد، آدرس سایتتون چیه؟",
            "مشتری جواب ربات نمی‌خواد",
            "اونو نمی‌خواد، بذارش اونجا",
            "اگه این کارو بکنه دیگه منشی لازم نداریم",
            "مگه ما مشتری بیشتر نمی‌خوایم",
            "نه، ممنونم، خیلی هم خوبه",
            "نمی‌خوایم معطلتون کنیم، بعدا تماس بگیرید",
            "نمی خوام فراموش کنم، فردا زنگ بزنید",
            "نگفتم نمی خوام",
            "مشتری نمی خواد صبر کنه",
            "عکسامو حذف کنید",
            "سفارشو اشتباهی گرفتیم، مشتری ناراحت شد",
            "کد نیومد، شماره رو پاک کن دوباره بزن؟",
            "دیگه نمی تونم حرف شما رو رد کنم",
        ):
            signals = read_signals(heard)
            self.assertFalse(signals.refuse or signals.dnc or signals.wrong, heard)
        self.assertFalse(read_signals("دیگه نمی تونم حرف شما رو رد کنم").later)

    def test_no_before_the_pitch(self) -> None:
        import sales

        # «سلام، لازم نیست» got the whole opening; now one line with who is calling and the address, then goodbye.
        plan = plan_turn(SalesState(), "سلام لازم نیست")
        self.assertEqual(plan.line, sales.BUSY_OPEN_LINE)
        self.assertTrue(plan.hangup)
        self.assertIn("هوش مصنوعی", speakable(plan.line, 3))
        self.assertEqual(speakable(plan.line, 3), speakable(plan.line, 9))
        self.assertIn(plan.line, sales.cached_sales_lines())
        # A no said to someone in the shop before «الو؟» is not said to us.
        self.assertFalse(plan_turn(SalesState(), "الو سلام، یه لحظه... نه نمی‌خوام، الو؟").hangup)
        # «از کجا آوردید؟ نمی‌خوام» still gets the answer, and the next no goes to the DNC file.
        self.assertFalse(plan_turn(SalesState(), "از کجا شماره منو آوردید؟ نمی خوام").hangup)

    def test_cloud_voice_without_credit_stops_asking(self) -> None:
        import urllib.error
        from unittest import mock

        import brain as brain_module

        calls: list[int] = []

        def refuse(code: int):
            def open_(_req, timeout=0):
                calls.append(code)
                raise urllib.error.HTTPError("https://openrouter.ai", code, "no", {}, None)

            return open_

        with mock.patch.dict(os.environ, {"TTS_MODEL": "m", "LLM_API_KEY": "k"}):
            voice = Brain.__new__(Brain)
            voice._cloud_off_until = 0.0
            with mock.patch.object(brain_module._DIRECT, "open", refuse(402)):
                self.assertEqual(voice.cloud_pcm("سلام", 1.0), b"")
                self.assertEqual(voice.cloud_pcm("سلام", 1.0), b"")
            # One refused request, then Piper speaks without waiting on the cloud again.
            self.assertEqual(calls, [402])
            calls.clear()
            voice._cloud_off_until = 0.0
            with mock.patch.object(brain_module._DIRECT, "open", refuse(503)):
                voice.cloud_pcm("سلام", 1.0)
                voice.cloud_pcm("سلام", 1.0)
            # A passing server error is tried again.
            self.assertEqual(calls, [503, 503])

    def test_sales_lines_render_behind_the_call(self) -> None:
        import threading

        import main as main_module
        import sales

        lines = sales.cached_sales_lines()

        class Voice:
            """prefetch_cloud as in brain: a line on disk loads; a new line needs the cloud, which has no credit."""

            def __init__(self, on_disk: set[str], hold: threading.Event | None = None) -> None:
                self.on_disk, self.hold, self.asked, self.started = on_disk, hold, 0, threading.Event()

            def prefetch_cloud(self, line: str) -> bytes:
                self.asked += 1
                self.started.set()
                if self.hold:
                    self.hold.wait(5)
                return b"pcm" if line in self.on_disk else b""

        def run(voice: Voice) -> main_module.Gateway:
            gw = main_module.Gateway.__new__(main_module.Gateway)
            gw._voice, gw._prefetching, gw.brain = {}, threading.Event(), voice
            gw._prefetch_sales_lines()
            return gw

        def settle(gw: main_module.Gateway) -> None:
            deadline = time.monotonic() + 5
            while gw._prefetching.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)

        # One new line the cloud cannot make (402) does not keep the recordings after it on disk from loading.
        new_line = lines[len(lines) // 2]
        gw = run(Voice(set(lines) - {new_line}))
        settle(gw)
        self.assertEqual(set(gw._voice), set(lines) - {new_line})
        # The call does not wait on the pass, and a second call while it runs does not start another.
        hold = threading.Event()
        gw = run(Voice(set(lines), hold))
        self.assertTrue(gw.brain.started.wait(5))
        gw._prefetch_sales_lines()
        time.sleep(0.05)
        self.assertEqual(gw.brain.asked, 1)
        hold.set()
        settle(gw)
        self.assertEqual(set(gw._voice), set(lines))

    def test_live_turns_of_the_busy_and_price_first_callers(self) -> None:
        import sales

        # p39: «باشه، یادداشت کردم، بعداً میام» reached the gateway as «واسه یادداشت کردم بعدم میام»; the model
        # answered «چه خوب!» before the goodbye. Noting the address is a yes, so the closing line comes at once.
        state = SalesState()
        for heard in ("سرم شلوغه سری بگو", "سرم شلوغه سریع بگو چی می خوای"):
            plan = plan_turn(state, heard)
            note_spoken(state, plan.line or "متوجه‌ام، حق دارید!")
        plan = plan_turn(state, "واسه یادداشت کردم بعدم میام")
        self.assertEqual((plan.line, plan.hangup), (sales.CLOSE_LINE, True))
        for heard in (
            "یادداشت کردم",
            "آدرسو نوشتم",
            "حتما یه سر میزنم",
            "بعداً میام",
            "باشه سیوش کردم",
            "یاد داشت کردم ممنون",
            "حتما یه نگاه میندازم",
            "بعداً می‌آم",
            "آدرسو تو گوشیم ذخیره کردم",
        ):
            self.assertTrue(read_signals(heard).agree, heard)
        # Their own work, a question in the same breath, or a no is not a yes.
        for heard in (
            "من سفارشا رو یادداشت میکنم",
            "یادداشت نکردم",
            "نمیام",
            "بعدش میام",
            "کپشنا رو خودم نوشتم",
            "کپشنشو خودم نوشتمش",
            "خودم شبا به دایرکتا سر میزنم",
            "روزی پنجاه تا، شبا خودم بهشون سر میزنم",
            "سفارشا رو تو دفترم یادداشت کردم ولی گم میشه",
            "همه مشتریامو تو گوشی سیو کردم",
            "فردا میام مغازه",
            "یادداشت کردم، فقط این رایگانه دیگه؟",
            "من کی گفتم یادداشت کردم",
            "بعدا میام ولی فعلا علاقه ای ندارم",
        ):
            self.assertFalse(read_signals(heard).agree, heard)
        for heard in ("روزی پنجاه تا، شبا خودم بهشون سر میزنم", "باشه ولی علاقه ای ندارم"):
            self.assertNotEqual(plan_turn(state_after(sales.QUICK_OPEN_LINE), heard).line, sales.CLOSE_LINE, heard)
        # Noting the address in other words closes too, right after the address line.
        for heard in (
            "آدرستون رو یادداشت کردم",
            "آدرستونو نوشتم",
            "لینکتون رو سیو کردم",
            "آدرسو گرفتم ممنون",
            "مرسی گرفتم آدرسو",
            "آدرس‌تون رو یادداشت کردم",
            "سایت‌تون رو چک می‌کنم",
            "حتما یه سر بهش میزنم",
            "یه نگاهی بهش میندازم",
            "حتماً سر می‌زنم بهتون",
            "مرسی خانم یادداشت کردم",
        ):
            self.assertEqual(plan_turn(state_after(ADDRESS_LINE), heard).line, sales.CLOSE_LINE, heard)
        # But not as the answer to our own question about their work: «سفارش‌ها رو کجا ثبت می‌کنید؟»
        for last, heard in (
            (sales.ORDER_LINE, "تو گوشی یادداشت می‌کنم"),
            (sales.ORDER_LINE, "تو گوشي يادداشت مي‌كنم"),
            (sales.ORDER_LINE, "بله تو گوشی یادداشت می‌کنیم"),
            (sales.ORDER_LINE, "تو گوشی نوشتم"),
            (sales.PAIN_LINE, "تو گوشی چک میکنم"),
            (sales.PAIN_LINE, "آره سر میزنم"),
        ):
            state = state_after(sales.QUICK_OPEN_LINE)
            note_spoken(state, last)
            self.assertNotEqual(plan_turn(state, heard).line, sales.CLOSE_LINE, heard)
        # p39: the model added [آدرس] to the busy turn right after the line that gave the address.
        def address_for(heard: str, last: str = sales.QUICK_OPEN_LINE) -> list[str]:
            return sales.tool_followups({"address"}, state_after(last), heard, "حتماً!")[0]

        self.assertEqual(address_for("سرم شلوغه سریع بگو چی می خوای"), [])
        for heard in ("سوزان چی؟ دوباره بگو", "ببخشید نفهمیدم اسمش چی بود؟", "سرم شلوغه، اسمش چی بود؟", "خب چطوری ثبت نام کنم؟"):
            self.assertEqual(address_for(heard), [ADDRESS_LINE], heard)
        self.assertEqual(address_for("سرم شلوغه سریع بگو", sales.PAIN_LINE), [ADDRESS_LINE])
        for heard in ("اسمشو سریع بگو", "سرم شلوغه، تکرار کن", "سرم شلوغه، یه دور دیگه بگو", "سرم شلوغه، دات چی؟", "سرم شلوغه، چطوری ثبت نام کنم؟"):
            self.assertEqual(address_for(heard), [ADDRESS_LINE], heard)
        # «بعداً دوباره زنگ بزنید» asks for a call, not the address; a reply that is only [آدرس] still says it.
        self.assertEqual(address_for("سرم شلوغه، بعداً دوباره زنگ بزنید"), [])
        busy = sales.tool_followups({"address"}, state_after(sales.QUICK_OPEN_LINE), "سرم شلوغه سریع بگو چی می خوای", "")
        self.assertEqual(busy[0], [ADDRESS_LINE])
        # p44: «هزینه‌ش چقدر؟ گرون نباشه» after the price got the same sentence again.
        state = SalesState()
        first = plan_turn(state, "اول بگو چقدر می گیری")
        note_spoken(state, first.line or "")
        priced = first.line.replace(f"{sales.FIRST_DISCLOSE} ", "")
        again = plan_turn(state, "هزینه شین چقدر گروون نباشه")
        self.assertNotIn(again.line, first.line)
        self.assertIn("یک میلیون و چهارصد و چهارده هزار", again.line)
        # «رایگان» is the store, never the paid plan.
        self.assertIn("ساخت فروشگاه رایگانه", again.line)
        self.assertNotIn("شروعش رایگانه", again.line)
        self.assertIn(again.line, sales.cached_sales_lines())
        note_spoken(state, again.line or "")
        # A third ask, fixed or through the model's [قیمت], gets the first wording back, never nothing.
        self.assertEqual(plan_turn(state, "باز هم بگو قیمتش چنده").line, priced)
        self.assertEqual(sales.tool_followups({"price"}, state, "خب", "حق دارید!")[0], [priced])
        lines, _end, _dnc = sales.tool_followups({"price"}, state_after(first.line or ""), "چنده؟", "حق دارید!")
        self.assertEqual(lines, [again.line])
        for heard in ("قیمت", "پرو مکس"):
            line = sales.price_again_line(sales.price_spoken_line(heard) or "")
            self.assertLessEqual(len(line.split()), 21, line)
            self.assertLessEqual(len(f"{sales.ROBOT_SHORT} {line}".split()), 25, line)
        # With no price list, the second ask still names the site.
        set_plans_fetcher(lambda: None)
        state = state_after(sales.PRICE_UNKNOWN_LINE)
        self.assertEqual(plan_turn(state, "قیمتش چنده؟").line, sales.PRICE_AGAIN_UNKNOWN_LINE)
        self.assertTrue(sales.mentions_address(speakable(sales.PRICE_AGAIN_UNKNOWN_LINE, 3)))
        for line in (sales.PRICE_AGAIN_UNKNOWN_LINE, f"{sales.ROBOT_SHORT} {sales.PRICE_AGAIN_UNKNOWN_LINE}"):
            self.assertIn(line, sales.cached_sales_lines())


def state_after(line: str) -> SalesState:
    state = SalesState(greeted=True, intro_said=True, pain_asked=True, stage="pitch")
    note_spoken(state, line)
    return state


if __name__ == "__main__":
    unittest.main()
