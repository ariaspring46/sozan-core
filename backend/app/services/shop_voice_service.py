"""The shop assistant's own voice.

`say`: a short reply in the model's words for something the system already did or knows (a verified edit, the build state,
a gate answer). The facts come from the system; a reply that drops a quoted fact, a host or a number, claims a success that
did not happen, makes a promise the system cannot keep, or is not Persian is thrown away and the plain fallback is shown.
The shop-setup talk itself is in shop_interview_service; this module holds the shared checks and brief helpers.
"""

from __future__ import annotations

import re

from app.services.llm import complete_json, complete_text_chat
from app.services.router_text import fix_halfspace

SKINS = ("atelier", "street", "boutique")
BRIEF_TEXT_KEYS = ("colors", "features", "notes", "audience", "story", "tone", "brandName", "order", "reference", "avoid")
REPLY_MAX = 600

# Who this assistant is, and the features that matter. The about page and the landing capabilities are the source.
ABOUT_TEXT = (
    "من سوزانم، دستیار فروش فروشنده‌های ایرانی؛ تیم سوزان من را ساخته و سوزان محصول شرکت گهر شبکه کارمانیا است. "
    "با چند جمله فروشگاه می‌سازم، کالا را از پیج و کانال عمومی یا از حرف خودت به کاتالوگ می‌آورم، و در استودیو عکس و پست و کپشن آماده می‌کنم. "
    "پیام مشتری اینستاگرام و تلگرام را در یک صندوق جمع می‌کنم، با لحن تو پیش‌نویس می‌کنم، و سفارش و پرداخت را با درگاه خودت، کارت‌به‌کارت، یا کیف پول سوزان ثبت می‌کنم. "
    "کار مهم را اول به صورت کارت نشان می‌دهم و فقط با تأیید تو انجام می‌دهم، و شروع رایگان است."
)
_ABOUT_MUST = ("فروشگاه", "استودیو", "صندوق")


def about_text() -> str:
    return ABOUT_TEXT


def covers_about(reply: str) -> bool:
    """A self-introduction names the shop, the studio, the inbox, and payment."""
    text = reply or ""
    return all(word in text for word in _ABOUT_MUST) and any(word in text for word in ("پرداخت", "درگاه", "کارت"))


VOICE = """تو «سوزان» هستی، دستیار فروش فروشنده‌های ایرانی، ساختهٔ تیم سوزان و محصول شرکت گهر شبکه کارمانیا.
کارهای مهمت این‌هاست: ساخت فروشگاه با چند جمله، آوردن کالا از پیج و کانال عمومی، استودیو برای عکس و پست و کپشن، صندوق پیام مشتری، سفارش و پرداخت، و کارت تأیید قبل از هر کار مهم. شروع رایگان است.
وقتی فروشنده پرسید تو کیستی، سوزان چیست، یا چه کارهایی می‌کنی، همین کارها را بگو. در جواب بقیهٔ سؤال‌ها به همان سؤال جواب بده.
مثل یک آدم واقعی و دلسوز حرف بزن: خودمانی، با «تو»، فارسی روان و محاوره‌ای، نه اداری و نه ربات‌وار.
کوتاه بنویس (یک تا چهار جمله). جملهٔ قالبی و تکراری نگو؛ هر بار طور دیگری حرف بزن. فهرست، شماره‌گذاری و ایموجی پشت‌سرهم نه.
به حرف و کلمه‌های خود فروشنده اشاره کن (اسم کالا، شهر، حسی که گفت). کاری را که انجام نشده انجام‌شده نگو.
اصطلاح فنی و نشانی (docker، next، API، پورت، IP) نگو. قولی نده که سیستم انجام نمی‌دهد (مثل «بعداً خبرت می‌کنم»)."""

SAY_SYSTEM = (
    VOICE
    + """
سیستم کاری کرده یا وضعیتی را تأیید کرده و «واقعیت‌ها» همان است. همان را با لحن خودت بگو.
فقط از واقعیت‌ها استفاده کن؛ قیمت، رنگ، اسم، کار یا قول تازه نساز. «حرف فروشنده» فقط برای فهمیدن لحن اوست: هیچ اسمی از آن در « » نگذار. هر چه در واقعیت‌ها در « » آمده عیناً بیاید.
اگر کار انجام نشده، صادقانه بگو و یک قدم بعدی مشخص پیشنهاد بده.
نگو به اینستاگرام یا تلگرام دسترسی نداری؛ پیج عمومی اینستاگرام و کانال عمومی تلگرام خوانده می‌شود.
فقط JSON: {"reply":"…"}"""
)

_FA = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")
_URL = re.compile(r"https?://|www\.|127\.0\.0\.1|localhost", re.I)
_QUOTED = re.compile(r"«([^»]{1,80})»")
_FAILED = re.compile(r"نشد|نیست|نمی‌شود|نمی‌توان|ممکن نیست|ناموفق|پیدا نشد")
# nothing in the system tells the seller later, so the model must not promise it
_PROMISE = re.compile(r"خبر(?:ت)?\s*می‌?(?:کنم|دم)|بهت\s*(?:می‌?گم|خبر)|اطلاع\s*می‌?دم")
# a success verb that is not negated («نشد»، «نکردم»)
_SUCCESS = re.compile(r"(?<![نم])(?:شد|کردم|گذاشتم|ساختم|فرستادم|نوشتم|دادم|زدم|نشست|رسید|اعمال)(?![\u0600-\u06FF])")


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬,", "01234567890123456789  ")
_DOMAIN = re.compile(r"(?<![\w.-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![\w-])", re.I)


def _hosts(text: str) -> set[str]:
    spaced = str(text or "").translate(_DIGITS)
    return {item.lower() for item in _DOMAIN.findall(spaced)}


def _number_gap(reply: str, facts: str, seller_text: str) -> bool:
    """A reply may repeat numbers from the facts or from the seller's own sentence. A new number, or a dropped one, fails."""
    from app.services.number_span import voice_amounts

    known = voice_amounts(facts)
    allowed = known | voice_amounts(seller_text)
    said = voice_amounts(reply)
    return bool(known - said) or bool(said - allowed)


# markup and code words are the model's inner vocabulary («تیتر h1»); the seller never sees them
_TECH = re.compile(r"\b(?:h[1-6]|div|span|css|html|tsx|jsx|json|className|href|src)\b", re.I)


# a template slot the model left unfilled: «بوتیک [نام شما]»، «{brand}»
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,24}\]|\{[^}\n]{1,24}\}|<[^>\n]{1,24}>|\bxxx+\b|\.{4,}", re.I)


def _persian(text: str) -> bool:
    fa = len(_FA.findall(text))
    return fa >= 4 and fa >= len(_LATIN.findall(text))


def clean_reply(text: object) -> str:
    """A model reply shaped for a chat bubble: no markdown, no stray quotes, bounded."""
    value = str(text or "").strip()
    value = re.sub(r"[*`#>]+", "", value)
    # a markdown underscore goes, the one inside a page name («pink_shop», «mahsoo__beauty») stays
    value = re.sub(r"_+", lambda m: m.group() if 0 < m.start() and m.end() < len(value) and value[m.start() - 1].isascii() and value[m.start() - 1].isalnum() and value[m.end()].isascii() and value[m.end()].isalnum() else "", value)
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return fix_halfspace(value.strip(" \"'"))[:REPLY_MAX]


def acceptable(
    reply: str,
    *,
    must_keep: list[str] | None = None,
    patched: bool | None = None,
    facts: str | None = None,
    seller_text: str = "",
) -> bool:
    if not reply or len(reply) < 8 or not _persian(reply) or _URL.search(reply) or _TECH.search(reply) or _PLACEHOLDER.search(reply):
        return False
    if patched is not False:
        # a done thing keeps its quoted result («نقره»); a thing not done may only paraphrase its example sentences
        for fragment in must_keep or []:
            if fragment and fragment not in reply:
                return False
    if _PROMISE.search(reply):
        return False
    if facts is not None:
        # a name or phrase in « » must come from the facts, never from the seller's own words or the model's imagination
        for quoted in _QUOTED.findall(reply):
            if quoted not in facts:
                return False
        flat = reply.translate(_DIGITS).replace(" ", "").lower()
        for token in _hosts(facts):
            if token not in flat:
                return False
        if _number_gap(reply, facts, seller_text):
            return False
    if patched is False and _SUCCESS.search(reply):
        return False
    if patched is True and re.search(r"نشد|نتوانستم|نمی‌شود", reply):
        return False
    return True


def _capped(surface: str) -> bool:
    """A tenant over its AI budget gets the plain text at once: the budget fallback would be the slow local model."""
    from app.services.llm import _budget_capped

    try:
        return bool(_budget_capped(surface))
    except Exception:
        return False


def _note_plain(reason: str) -> None:
    """A spoken reply fell back to the plain sentence. The reason is how often this check refuses the model."""
    try:
        from app.services.observe_client import emit_later
        from app.services.turn_clock import turn_id

        emit_later(
            kind="llm",
            title="voice-plain",
            surface="voice",
            status="ok",
            turn_id=turn_id(),
            payload={"reason": (reason or "plain")[:40]},
        )
    except Exception:
        return


def _recent_lines(recent: list[dict] | None) -> str:
    lines = []
    for row in (recent or [])[-8:]:
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()[:160]
        if text:
            lines.append(f"{'سوزان' if row.get('role') == 'assistant' else 'فروشنده'}: {text}")
    return "\n".join(lines)


async def say(
    situation: str,
    facts: list[str],
    *,
    seller_text: str = "",
    fallback: str,
    patched: bool | None = None,
    surface: str = "shop",
    recent: list[dict] | None = None,
) -> str:
    """The same news in the model's words; the plain `fallback` when the model fails or bends a fact.

    `seller_text=""` for a refusal: the model then sees only the facts, never the words that might be an attack."""
    facts = [str(item).strip() for item in facts if str(item or "").strip()]
    seller = seller_text.strip()
    if _capped(surface):
        _note_plain("budget")
        return fallback
    from app.services import turn_clock

    if turn_clock.expired():
        _note_plain("budget")
        return fallback
    if patched is None and _FAILED.search(" ".join(facts)):
        patched = False  # the system says it did not work: the reply may not sound like it did
    must_keep = [item for fact in facts for item in _QUOTED.findall(fact)]
    facts_text = " ".join(facts)
    earlier = _recent_lines(recent)
    user = (
        f"وضعیت: {situation}\n"
        + (f"گفتگوی اخیر:\n{earlier}\n" if earlier else "")
        + f"حرف فروشنده: {seller[:300] or '—'}\n"
        "واقعیت‌ها:\n" + "\n".join(f"- {fact}" for fact in facts)
    )
    if situation == "about_self":
        user += "\nاین معرفی است: فروشگاه، استودیو، صندوق و پرداخت را در جواب نام ببر."
    parsed = await complete_json(
        SAY_SYSTEM, user, surface=surface, max_tokens=420 if situation == "about_self" else 260, temperature=0.7
    )
    reply = clean_reply(parsed.get("reply")) if not parsed.get("error") else ""
    reason = "error" if parsed.get("error") or not reply else ""
    if reply and not acceptable(reply, must_keep=must_keep, patched=patched, facts=facts_text, seller_text=seller):
        reason = "numbers" if _number_gap(reply, facts_text, seller) else "shape"
        reply = ""
    if situation == "about_self" and not covers_about(reply):
        _note_plain(reason or "about")
        return fallback
    if not reply:
        _note_plain(reason or "empty")
        return fallback
    from app.services.claims_guard import check, needs_claims_model

    backed_by = f"{facts_text}\n{seller}"
    if needs_claims_model(reply, backed_by):
        if turn_clock.expired():
            _note_plain("budget")
            return fallback
        hits = await check(reply, backed_by)
        if hits:
            _note_plain("claims")
            return fallback
    return reply


def _brief_lines(brief: dict) -> str:
    labels = (
        ("style", "حس سایت"),
        ("colors", "رنگ‌ها"),
        ("features", "بخش‌های سایت"),
        ("audience", "مشتری‌ها"),
        ("story", "داستان برند"),
        ("brandName", "اسم و شعار"),
        ("order", "سفارش و ارسال"),
        ("reference", "طرح موردعلاقه"),
        ("avoid", "نباید باشد"),
        ("tone", "لحن"),
        ("notes", "نکته‌های فروشنده"),
    )
    lines = [f"- {label}: {brief.get(key)}" for key, label in labels if str(brief.get(key) or "").strip()]
    return "\n".join(lines) or "- هنوز چیزی ثبت نشده"


def _catalog_lines() -> str:
    from app.services import channel_scan_service, storefront_service

    rows = [row for row in storefront_service.list_products().get("products") or [] if isinstance(row, dict)]
    if not rows:
        return "کالایی در کاتالوگ نیست.\n" + channel_scan_service.brief_for_shop()
    cats: list[str] = []
    for row in rows:
        cat = str(row.get("category") or "").strip()
        if cat and cat not in cats:
            cats.append(cat)
    prices = [int(row.get("price") or 0) for row in rows if int(row.get("price") or 0) > 0]
    titles = "، ".join(str(row.get("title") or "") for row in rows[:8] if row.get("title"))
    spread = f" قیمت‌ها از {min(prices):,} تا {max(prices):,} تومان." if prices else " قیمتی ثبت نشده."
    return (
        f"{len(rows)} کالا در کاتالوگ: {titles}. دسته‌ها: {'، '.join(cats[:6]) or '—'}.{spread}\n"
        + channel_scan_service.brief_for_shop()
    )


def clean_brief(raw: object) -> dict:
    """What the model may write into the brief: a known style, short texts, nothing else."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    style = str(raw.get("style") or "").strip().lower()
    if style in SKINS:
        out["style"] = style
    for key in BRIEF_TEXT_KEYS:
        value = raw.get(key)
        if isinstance(value, list):
            value = "، ".join(str(item).strip() for item in value if str(item).strip())
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text and not _URL.search(text):
            out[key] = text[:300]
    return out


def brief_facts(brief: dict) -> list[str]:
    """What the build will use, as facts for a reply (so the news names the seller's own choices)."""
    names = {"atelier": "لوکس و خلوت", "street": "خیابانی و پرانرژی", "boutique": "بوتیک گرم و خانوادگی"}
    facts = ["پیشرفت ساخت را در صفحهٔ «فروشگاه» همین اپ می‌بیند."]
    if brief.get("style"):
        facts.append(f"حس سایت: {names.get(str(brief['style']), brief['style'])}")
    if brief.get("colors"):
        facts.append(f"رنگ‌ها: {brief['colors']}")
    return facts
