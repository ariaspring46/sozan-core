"""The shop-setup interview as a loop: assess, decide, speak.

Each seller message goes through three steps:
1. `assess`: a cold read of the whole talk fills the brief, keeps the seller's own wishes word for word, scores how well
   the site could now match what the seller imagines (0-100) and lists what is still missing, as questions.
2. `decide` (plain code, not the model): ASK while there is too little to go on, PROPOSE a concrete plan when there is enough
   (or the seller is in a hurry, or the talk has gone on long), BUILD only when the seller confirms a proposal made on the
   previous turn.
3. `speak`: the model words the next message (the questions, or the proposal) in its own voice.

The seller is never stuck: «هر چی خودت صلاح می‌دانی» makes the model propose, and anything said while a proposal is open
reopens the loop. What the seller wished for is kept as `wishes` and reaches the factory prompt.
"""

from __future__ import annotations

import re
import time

from app.services import onboard_service, shop_voice_service as voice
from app.services.pii_mask import mask_pii
from app.state_store import read_json, write_json

STATE_FILE = "shop-interview.json"
KEEP_TURNS = 16
MIN_TURNS = 3  # seller messages before the model may propose on its own judgement
MAX_TURNS = 9  # after this many, a proposal is made as soon as style and colours are known
MIN_CONFIDENCE = 30  # the model's own score is only a veto («I am lost»); what is known is counted from the brief
ENOUGH_OPTIONAL = 3  # besides style and colours: audience, story, name, sections, order, tone, reference
OPTIONAL_KEYS = ("audience", "story", "brandName", "features", "order", "tone", "reference")
MAX_ASKED = 40
PROPOSAL_TTL = 30 * 60  # seconds a proposal stays open; a «آره» an hour later is not an answer to it
MAX_STALLS = 2  # seller turns in a row that taught nothing: stop asking and propose

SKIN_FA = {"atelier": "لوکس و خلوت", "street": "خیابانی و پرانرژی", "boutique": "بوتیک گرم و خانوادگی"}

# slot -> (what it means for the site, the brief key it fills)
SLOTS: dict[str, tuple[str, str]] = {
    "style": ("حس سایت: لوکس و خلوت، خیابانی و پرانرژی، یا بوتیک گرم و خانوادگی", "style"),
    "colors": ("رنگ‌های دوست‌داشتنی و رنگ‌هایی که نمی‌خواهد", "colors"),
    "audience": ("مشتری‌ها چه کسانی‌اند", "audience"),
    "story": ("چه چیز برند خاص است و داستانش", "story"),
    "name": ("اسم و شعار فروشگاه", "brandName"),
    "sections": ("چه بخش‌هایی روی سایت باشد (داستان برند، پرسش‌های متداول، لینک شبکه‌ها…)", "features"),
    "order": ("مشتری چطور سفارش می‌دهد و ارسال چطور است", "order"),
    "reference": ("طرح یا سایتی که فروشنده در ذهن دارد", "reference"),
    "avoid": ("چیزهایی که نباید در سایت باشد", "avoid"),
}

ASSESS_SYSTEM = """گفتگوی «سوزان» (دستیار) با یک فروشنده را بخوان؛ هدف ساخت سایتی است که تا حد ممکن به تصویر ذهنی خود فروشنده نزدیک باشد.
فقط یک JSON بده:
{"brief":{"style":"atelier|street|boutique","colors":"","features":"","audience":"","story":"","tone":"","brandName":"","order":"","reference":"","avoid":"","notes":""},
 "wishes":["هر خواستهٔ مشخص فروشنده تقریباً با همان کلمه‌ها"],
 "coverage":{"style":"known|unknown","colors":"","audience":"","story":"","name":"","sections":"","order":"","reference":"","avoid":""},
 "confidence":0,
 "missing":[{"slot":"colors","question":"یک سؤال کوتاه و مشخص به فارسی"}],
 "hurry":false,"confirms_build":false,"wants_change":false,
 "suggest":{"style":"","colors":"","brandName":""}}
قواعد:
- brief و wishes فقط از حرف خود فروشنده است؛ حدس نزن. style را فقط وقتی بنویس که روشن باشد: atelier = لوکس، شیک، خلوت، ساده، مینیمال، سفید؛ street = خیابانی، شلوغ، رنگارنگ، جوان و پرانرژی؛ boutique = گرم، صمیمی، خانوادگی، سنتی، دست‌ساز. اگر مطمئن نیستی خالی بگذار.
- اگر فروشنده چیزی را عوض کرد («نارنجی نه، سبز»)، مقدار جدید جایگزین قبلی است: در brief فقط وضعیت نهایی را بنویس، نه ترکیب قدیم و جدید.
- wishes: فقط درخواست‌هایی که دربارهٔ خود سایت است و باید اجرا شود یا نباید (مثلاً «بالای صفحه ویدیو باشد»، «شبیه سایت زارا»، «لوگو بزرگ»، «هیچ پاپ‌آپی نباشد»)؛ کوتاه و بدون تغییر معنا. واقعیت‌هایی مثل شهر، مشتری، رنگ، اسم، سفارش که جای دیگری در brief می‌آید و جملهٔ معمولی گفتگو wish نیست.
- coverage: برای هر موضوع known اگر فروشنده یا داده روشنش کرده، وگرنه unknown.
- confidence از ۰ تا ۱۰۰: چقدر مطمئنی با همین اطلاعات سایتی می‌سازی که فروشنده بگوید «همین را می‌خواستم». بدون حس و رنگ هرگز بالای ۴۰ نده؛ پاسخ‌های مبهم یا کوتاه اطمینان را بالا نمی‌برد.
- missing: حداکثر ۳ چیزی که اگر ندانی سایت با تصور فروشنده فرق می‌کند، به ترتیب اهمیت، هر کدام با یک سؤال طبیعی. سؤال‌هایی که قبلاً پرسیده شده و جواب گرفته را دوباره نیاور؛ اگر جواب مبهم بود دقیق‌تر بپرس.
- hurry=true اگر فروشنده می‌خواهد پرسیدن تمام شود و کار شروع شود: «شروع کن»، «بساز»، «همین کافیه»، «هر چه خودت صلاح می‌دانی»، «عجله دارم».
- confirms_build=true فقط اگر آخرین پیام فروشنده صریحاً خواسته همان طرح پیشنهادیِ سوزان ساخته شود (بله، بساز، شروع کن، اوکی).
- wants_change=true اگر آخرین پیام چیزی از طرح را عوض یا اضافه می‌کند.
- suggest: همیشه پرش کن: پیشنهاد خودت برای style و رنگ‌ها و اسم، بر پایهٔ آنچه می‌دانی؛ حتی اگر فروشنده نگفته."""

SPEAK_SYSTEM = (
    voice.VOICE
    + """
داری با فروشنده گپ می‌زنی تا فروشگاهش را بسازی. مشخص شده این نوبت چه کاری بکنی؛ فقط همان را بکن و جملهٔ قالبی نگو.
قول نده کاری را که سیستم نمی‌کند. هرگز نگو سایت ساخته شد یا شروع به ساخت کردی؛ ساخت فقط بعد از تأیید خود فروشنده شروع می‌شود.
نام‌های داخلی atelier و street و boutique را هرگز نگو؛ بگو «لوکس و خلوت»، «خیابانی و پرانرژی»، «بوتیک گرم و خانوادگی».
خروجی فقط خود پیام به فارسی است، بدون JSON و بدون فهرست شماره‌دار."""
)

ASK_TASK = """کار این نوبت: از سؤال‌های «کم‌ترین‌های مهم» یکی یا دو تا را (نه بیشتر) با لحن خودت بپرس. سؤال‌ها فقط پیشنهادند؛ بازنویسی‌شان کن و به حرف‌های خود فروشنده وصلشان کن.
اگر فروشنده چیزی خواسته، اول کوتاه نشان بده که شنیده‌ای. چیزی که قبلاً پرسیده‌ای و جواب گرفته را دوباره نپرس.
اگر فروشنده سؤالی پرسیده (مثل قیمت پلن) و جوابش را در داده نداری، همین را صادقانه بگو و بگو کجا باید نگاه کند («بیشتر ← پرداخت و پیامک» برای پلن)؛ سؤالش را بی‌جواب نگذار. جای خالی مثل «[نام شما]» ننویس؛ اگر اسم نمی‌دانی، خودت یک اسم مشخص پیشنهاد بده."""

PROPOSE_TASK = """کار این نوبت: یک طرح پیشنهادی مشخص بده (نه کلی)؛ هر چه فروشنده گفته را همان‌طور رعایت کن و پیشنهادهای خودت را فقط برای جاهای خالی بیاور: حس سایت، پالت رنگ (اگر فروشنده نگفته خودت پیشنهاد بده و بگو پیشنهاد توست)،
بخش‌های سایت، اسم و شعار، لحن، و هر «خواستهٔ ویژه»ای که فروشنده گفته و می‌گذاری. کوتاه و گرم، یک تا شش جمله.
بعد فقط یک سؤال بپرس: همین را بسازم یا چیزی را عوض کنم؟ سؤال تازهٔ دیگری نپرس؛ جاهای خالی را خودت پیشنهاد بده و بگو پیشنهاد توست. اگر فروشنده سؤالی پرسیده اول جواب بده."""


_ACK_WORDS = frozenset(
    "آره اره بله بلی باشه باش اوکی اوکه ok okay خوبه خوب عالیه عالی همینه همین درسته موافقم بساز بسازش شروع کن بکن بزن بریم حله تمام قبول هست".split()
)


_DELEGATE = re.compile(r"هر\s*چ[یه]|صلاح|فرق(?:ی)?\s*(?:نمی|ندار)|خودت\s*(?:انتخاب|تصمیم|بساز|ببین)|عجله|همین\s*کافی|فقط\s*بساز")


def is_delegate(text: object) -> bool:
    """«هرچی صلاح می‌دانی»، «فرقی نداره»، «عجله دارم»: the seller hands the choice to the model."""
    return bool(_DELEGATE.search(str(text or "")))


def is_ack(text: object) -> bool:
    """A bare «آره / باشه / خوبه / شروع کن»: the answer to «همین را بسازم؟», which the model cannot tell from small talk."""
    words = [word for word in _PUNCT.sub(" ", str(text or "")).split() if word]
    return 0 < len(words) <= 3 and all(word.lower() in _ACK_WORDS for word in words)


def _last_seller_text(rows: list[dict]) -> str:
    return next((str(row.get("text") or "") for row in reversed(rows) if row.get("role") == "user"), "")


def _state() -> dict:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    write_json(STATE_FILE, state)


def _squash(text: object) -> str:
    return re.sub(r"[\s\u200c]+", "", str(text or ""))


def proposal_open(state: dict, rows: list[dict]) -> bool:
    """A proposal is only answered by the very next seller message: still fresh, and Sozan's last line in this talk is that proposal
    (a reload hours later, or other messages in between, make a bare «آره» an ordinary line)."""
    if state.get("mode") != "propose":
        return False
    at = float(state.get("at") or 0)
    if at and time.time() - at > PROPOSAL_TTL:
        return False
    said = _squash(state.get("said"))
    if not said:
        return True
    earlier = [row for row in rows[:-1] if row.get("role") == "assistant" and str(row.get("id") or "") != "shop-build-live"]
    return bool(earlier) and said in _squash(earlier[-1].get("text"))


def _transcript(rows: list[dict]) -> str:
    lines = []
    for row in [item for item in rows if str(item.get("id") or "") != "shop-build-live"][-KEEP_TURNS:]:
        who = "سوزان" if row.get("role") == "assistant" else "فروشنده"
        text = re.sub(r"\s+", " ", mask_pii(str(row.get("text") or ""))).strip()[:500]
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def clean_assessment(raw: object) -> dict:
    """The model's assessment, shaped: known slots, a bounded confidence, at most three questions, plain flags."""
    data = raw if isinstance(raw, dict) else {}
    try:
        confidence = max(0, min(100, int(float(data.get("confidence") or 0))))
    except (TypeError, ValueError):
        confidence = 0
    missing = []
    for item in data.get("missing") or []:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("slot") or "").strip()
        question = re.sub(r"\s+", " ", str(item.get("question") or "")).strip()[:200]
        if slot in SLOTS and question:
            missing.append({"slot": slot, "question": question})
    wishes = []
    for item in data.get("wishes") or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()[:200]
        if text and not voice._URL.search(text) and text not in wishes:
            wishes.append(text)
    return {
        "brief": voice.clean_brief(data.get("brief")),
        "wishes": wishes[:8],
        "confidence": confidence,
        "missing": missing[:3],
        "hurry": bool(data.get("hurry")),
        "confirms_build": bool(data.get("confirms_build")),
        "wants_change": bool(data.get("wants_change")),
        "suggest": voice.clean_brief(data.get("suggest")),
    }


_PUNCT = re.compile(r"[\s\u200c.,،؛:!؟?«»\"'()-]+")


def _flat(text: object) -> str:
    return _PUNCT.sub("", str(text or ""))


def merge_wishes(old: object, new: list[str], brief: dict | None = None) -> list[str]:
    """The seller's requests for the site, without repeats and without facts that already sit in another brief field."""
    merged = [str(item) for item in (old if isinstance(old, list) else []) if str(item).strip()]
    captured = [_flat(brief.get(key)) for key in ("colors", "audience", "brandName", "story", "order", "tone", "features") if brief and brief.get(key)]
    captured = [item for item in captured if len(item) >= 4]
    for item in new:
        flat = _flat(item)
        if len(flat) < 4 or any(flat == _flat(other) or flat in _flat(other) for other in merged):
            continue
        if any(flat in field or field in flat for field in captured):
            continue
        merged = [other for other in merged if _flat(other) not in flat] + [item]
    return merged[-12:]


def decide(brief: dict, assessment: dict, state: dict, seller_turns: int) -> str:
    """ask | propose | build. Plain code: the model reports, the loop's exit is decided here."""
    ready = onboard_service.brief_ready(brief)
    was_proposal = state.get("mode") == "propose"
    if assessment["confirms_build"] and was_proposal and not assessment["wants_change"]:
        return "build"
    if assessment["wants_change"]:
        return "ask"
    suggestion = assessment["suggest"]
    can_assume = bool(suggestion.get("style") and suggestion.get("colors"))
    if was_proposal and ready:
        return "propose"  # a question or a remark while the proposal is open: answer it and offer again
    stalled = int(state.get("stalls") or 0) >= MAX_STALLS and seller_turns >= MIN_TURNS  # «سلام» and a first vague line are not stalling
    if (assessment["hurry"] or stalled) and (ready or can_assume):
        return "propose"
    known = sum(1 for key in OPTIONAL_KEYS if str(brief.get(key) or "").strip())
    enough = ready and known >= ENOUGH_OPTIONAL and seller_turns >= MIN_TURNS and assessment["confidence"] >= MIN_CONFIDENCE
    long_talk = ready and seller_turns >= MAX_TURNS
    return "propose" if enough or long_talk else "ask"


async def assess(rows: list[dict], brief: dict, state: dict) -> dict | None:
    known = voice._brief_lines(brief)
    asked = ", ".join(str(item) for item in (state.get("asked") or [])[-12:]) or "—"
    user = (
        f"آنچه تا حالا ثبت شده:\n{known}\nخواسته‌های ثبت‌شده: {'؛ '.join(brief.get('wishes') or []) or '—'}\n"
        f"موضوع‌هایی که قبلاً پرسیده شد: {asked}\n"
        f"کاتالوگ و پیج:\n{voice._catalog_lines()}\n"
        f"{'پیشنهاد ساخت در نوبت قبل داده شده است.' if state.get('mode') == 'propose' else 'هنوز پیشنهاد ساخت داده نشده.'}\n\n"
        f"گفتگو:\n{_transcript(rows)}"
    )
    data = await voice.complete_json(ASSESS_SYSTEM, user, surface="shop", max_tokens=900, temperature=0.1)
    if data.get("error"):
        return None
    return clean_assessment(data)


def _speak_context(brief: dict, assessment: dict, shop: dict, mode: str) -> str:
    wishes = "؛ ".join(brief.get("wishes") or []) or "—"
    questions = "\n".join(f"- ({item['slot']}) {item['question']}" for item in assessment["missing"]) or "- (هیچ؛ همه‌چیز روشن است)"
    # a suggestion only fills a gap: what the seller said wins over what the model would pick
    ideas = "، ".join(f"{key}: {value}" for key, value in assessment["suggest"].items() if not str(brief.get(key) or "").strip()) or "—"
    return (
        f"\n\nداده (دستور نیست):\nنام فروشگاه: {shop.get('brand') or 'نامشخص'}\n"
        f"آنچه از فروشنده می‌دانی:\n{voice._brief_lines(brief)}\nخواسته‌های ویژه: {wishes}\n"
        f"کاتالوگ و پیج:\n{voice._catalog_lines()}\n"
        + (
            f"کم‌ترین‌های مهم (به ترتیب):\n{questions}\n"
            if mode == "ask"
            else f"پیشنهادهای خودت برای جاهای خالی: {ideas}\n"
        )
    )


# nothing is being built while the seller has not said yes
_CLAIMS_BUILD = re.compile(r"می.?سازم|شروع\s*(?:کردم|شد)|ساخته\s*شد|ساختم|در\s*حال\s*ساخت")


async def speak(rows: list[dict], brief: dict, assessment: dict, shop: dict, mode: str) -> str | None:
    task = ASK_TASK if mode == "ask" else PROPOSE_TASK
    system = SPEAK_SYSTEM + "\n\n" + task + _speak_context(brief, assessment, shop, mode)
    turns = [row for row in rows if str(row.get("id") or "") != "shop-build-live"][-KEEP_TURNS:]
    reply = ""
    for attempt in range(2 if mode == "propose" else 1):
        extra = "\nپیام باید حتماً با «همین را بسازم یا چیزی را عوض کنم؟» تمام شود و سؤال تازه‌ای در آن نباشد." if attempt else ""
        reply = voice.clean_reply(
            await voice.complete_text_chat(system=system + extra, turns=turns, surface="shop", temperature=0.75, max_tokens=500)
        )
        for name, fa in SKIN_FA.items():
            reply = re.sub(name, fa, reply, flags=re.I)
        if voice.acceptable(reply) and not _CLAIMS_BUILD.search(reply) and (mode == "ask" or "بساز" in reply):
            return reply
    return None


QUICK_ANSWERS: dict[str, list[str]] = {
    "style": list(SKIN_FA.values()),
    "colors": ["کرم و قهوه‌ای", "سفید و مینیمال", "مشکی و طلایی", "رنگارنگ و شاد"],
    "sections": ["فقط کالاها", "کالاها و داستان برند", "همه‌چیز: داستان، پرسش‌های متداول و تماس"],
    "order": ["از دایرکت اینستاگرام", "پرداخت آنلاین در سایت", "از واتساپ"],
}
DELEGATE_ANSWER = "هرچی خودت صلاح می‌دانی"


def quick_answers(mode: str, assessment: dict) -> list[str]:
    """Taps under the model's message: a few likely answers to the question just asked, and always a way to hand the choice over."""
    if mode == "propose":
        return ["آره، بساز", "چیزی را عوض کنم"]
    first = assessment["missing"][0]["slot"] if assessment["missing"] else ""
    options = QUICK_ANSWERS.get(first)
    return [*options, DELEGATE_ANSWER] if options else []


def _fallback_reply(brief: dict, assessment: dict, mode: str) -> str | None:
    """The model could not word the turn: its own question (ask) or a plain summary (propose) still moves the talk on."""
    if mode == "ask":
        return assessment["missing"][0]["question"] if assessment["missing"] else None
    ideas = {key: value for key, value in assessment["suggest"].items() if value}
    facts = voice.brief_facts({**ideas, **{k: v for k, v in brief.items() if v}})[1:]
    if not facts:
        return None
    return "جمع‌بندی من: " + "؛ ".join(facts) + ". همین را بسازم یا چیزی را عوض کنم؟"


async def turn(rows: list[dict], brief: dict, shop: dict) -> dict | None:
    """One loop step. None when the model could not assess (the caller falls back to its fixed script)."""
    if voice._capped("shop"):
        return None
    state = _state()
    if state.get("mode") == "build":
        return {"reply": "", "build": False, "mode": "build", "skip": True}  # the build was started from here; the rest is the shop chat
    seller_turns = int(state.get("turns") or 0) + 1
    if state.get("mode") == "propose" and not proposal_open(state, rows):
        state = {**state, "mode": "ask"}  # stale proposal: nothing to confirm any more
    assessment = await assess(rows, brief, state)
    if assessment is None:
        return None
    last = _last_seller_text(rows)
    if state.get("mode") == "propose" and is_ack(last):
        assessment = {**assessment, "confirms_build": True, "wants_change": False}
    if is_delegate(last):
        assessment = {**assessment, "hurry": True}
    patch = dict(assessment["brief"])
    wishes = merge_wishes(brief.get("wishes"), assessment["wishes"], {**brief, **assessment["brief"]})
    if wishes:
        patch["wishes"] = wishes
    taught = any(str(patch.get(key) or "") != str(brief.get(key) or "") for key in patch) or bool(
        set(assessment["wishes"]) - set(brief.get("wishes") or [])
    )
    state = {**state, "stalls": 0 if taught else int(state.get("stalls") or 0) + 1}
    merged = onboard_service.save_brief(patch)
    mode = decide(merged, assessment, state, seller_turns)
    if mode == "build":
        proposal = state.get("proposal") if isinstance(state.get("proposal"), dict) else {}
        fill = {key: value for key, value in proposal.items() if key in ("style", "colors", "brandName") and value and not merged.get(key)}
        if fill:
            merged = onboard_service.save_brief({**fill, "assumed": [key for key in fill]})
        offered = str(proposal.get("colors") or "").strip()
        if offered and merged.get("colors") and offered != merged.get("colors") and offered not in str(merged.get("notes") or ""):
            # the seller said yes to a palette that is wider than what they named: the factory should see both
            note = f"{merged.get('notes') or ''} پالت پیشنهادیِ تأییدشده: {offered}".strip()
            merged = onboard_service.save_brief({"notes": note})
        if not onboard_service.brief_ready(merged):
            mode = "ask"
        else:
            _save_state({**state, "mode": "build", "turns": seller_turns})
            onboard_service.save_brief({"proposed": False})
            return {"reply": "", "build": True, "mode": "build", "assessment": assessment}
    asked = list(state.get("asked") or [])
    if mode == "ask":
        asked = (asked + [item["slot"] for item in assessment["missing"][:2]])[-MAX_ASKED:]
    new_state = {
        "mode": mode,
        "turns": seller_turns,
        "confidence": assessment["confidence"],
        "stalls": 0 if mode == "propose" else state["stalls"],
        "asked": asked,
        "proposal": assessment["suggest"] if mode == "propose" else state.get("proposal") or {},
        "at": time.time(),
    }
    _save_state(new_state)
    onboard_service.save_brief({"proposed": mode == "propose"})
    reply = await speak(rows, merged, assessment, shop, mode) or _fallback_reply(merged, assessment, mode)
    if not reply:
        return None
    if mode == "propose":
        _save_state({**new_state, "said": _squash(reply)[:24]})
    return {"reply": reply, "build": False, "mode": mode, "assessment": assessment, "options": quick_answers(mode, assessment)}


def reset() -> None:
    """A fresh interview (the shop was rebuilt from scratch or the seller started over)."""
    _save_state({})
    onboard_service.save_brief({"proposed": False})

