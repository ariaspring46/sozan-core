"""Small text helpers for the chat router.

Two jobs, both free of any model call:
- sentences the gate can answer on its own (hello, thanks, "where do I change the plan");
- the clean-up applied to what a model wrote before a seller reads it (markdown that the
  chat bubble cannot render, missing half-spaces, a reply cut in the middle of a sentence).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_TO_FA = str.maketrans("0123456789", _FA_DIGITS)
_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_INVISIBLE = re.compile(r"[​‍‎‏‪-‮⁦-⁩﻿]")
_ARABIC_LETTERS = str.maketrans({"ك": "ک", "ي": "ی", "ى": "ی", "ة": "ه", "ۀ": "ه"})
_PUNCT = re.compile(r"[\s،؛؟٪-٭۔.,:;!?\-_/\\()\[\]{}«»\"'…~*|<>=+^%$#@&]+")
_HAS_LETTER = re.compile(r"[A-Za-z0-9ء-ۓ]")


def fa_digits(value: object) -> str:
    """۱۲۳ for 123."""
    return str(value).translate(_TO_FA)


def fa_money(amount: object) -> str:
    """۲٬۵۰۰٬۰۰۰ — Persian digits and the Persian thousands mark."""
    try:
        number = int(amount or 0)
    except (TypeError, ValueError):
        number = 0
    return fa_digits(f"{number:,}".replace(",", "٬"))


def fold(text: str) -> str:
    """One spelling per letter and digit, no half-spaces: the form every pattern below is written for."""
    value = (text or "").translate(_ARABIC_LETTERS).translate(_TO_ASCII)
    value = value.replace("‌", " ")
    value = _INVISIBLE.sub("", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def squeeze(text: str) -> str:
    """Newlines and runs of spaces become one space, so «قیمت‌ها\\nرا مخفی کن» parses like one line."""
    return re.sub(r"\s+", " ", text or "").strip()


# ---------------------------------------------------------------- hello, thanks, goodbye

_GREET = {"سلام", "درود", "های", "هی", "hi", "hello", "hey", "salam", "سلام علیکم", "علیک"}
_GREET_FILL = {
    "علیکم", "خوبی", "خوبین", "خوبید", "چطوری", "چطورید", "چطوره", "حالت", "حالتون", "خسته", "نباشید", "نباشی",
    "وقت", "بخیر", "جان", "عزیزم", "عزیز", "سوزان", "خانم", "جناب", "دوست", "صبح", "عصر", "ظهر", "شب", "روز",
    "شما", "سلام", "درود", "چه", "خبر", "ممنون", "مرسی", "و", "هم",
}
_THANKS = {"ممنون", "ممنونم", "مرسی", "مرسیی", "تشکر", "سپاس", "مچکرم", "thanks", "thx", "دمت", "دستت", "متشکرم"}
_THANKS_FILL = {
    "خیلی", "عالی", "بود", "شد", "از", "شما", "تو", "همه", "چیز", "لطف", "لطفتون", "کردی", "کمکت", "کمک", "ممنون",
    "مرسی", "تشکر", "دمت", "گرم", "دستت", "درد", "نکنه", "سپاس", "ممنونم", "عزیزم", "سوزان", "جان", "عالیه",
    "قشنگ", "حله", "خوب", "خب", "واقعا", "واقعاً", "بابت", "کمکتون", "زحمت", "زحماتت", "ها", "دوست", "خیلیی",
}
_BYE = {"خداحافظ", "خدانگهدار", "فعلا", "بای", "bye", "خداحافظی"}
_BYE_FILL = {"شب", "بخیر", "موفق", "باشی", "باشید", "میبینمت", "بعدا", "بعداً", "تا", "فردا", "سوزان", "جان", "عزیزم", "فعلا", "خداحافظ"}

HELLO_REPLY = "سلام! بگو چه کاری انجام بدهم: وضعیت فروشگاه، کالا، پست یا صندوق."
HOW_ARE_YOU_REPLY = "سلام! خوبم، ممنون. بگو چه کاری انجام بدهم: وضعیت فروشگاه، کالا، پست یا صندوق."
THANKS_REPLY = "خواهش می‌کنم! کار دیگری هست؟"
BYE_REPLY = "خداحافظ! هر وقت خواستی همین‌جا هستم."
EMOJI_REPLY = "😊 چه کاری انجام بدهم؟"


def _words(text: str) -> list[str]:
    return [word for word in _PUNCT.split(fold(text)) if word and _HAS_LETTER.search(word)]


def social_reply(text: str) -> str:
    """A whole message that is only a greeting, thanks or goodbye gets a fixed answer (no model, no cost)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    words = _words(raw)
    if not words:
        # nothing but emoji or punctuation
        return EMOJI_REPLY if len(raw) <= 12 and not re.search(r"[A-Za-z0-9؀-ۿ]", raw) else ""
    if len(words) > 5:
        return ""
    first = words[0]
    if first in _GREET and all(word in _GREET_FILL or word in _GREET for word in words):
        asks = any(word in {"خوبی", "خوبین", "خوبید", "چطوری", "چطورید", "حالت", "حالتون"} for word in words)
        return HOW_ARE_YOU_REPLY if asks else HELLO_REPLY
    if any(word in _THANKS for word in words) and all(word in _THANKS_FILL or word in _THANKS for word in words):
        return THANKS_REPLY
    if any(word in _BYE for word in words) and all(word in _BYE_FILL or word in _BYE for word in words):
        return BYE_REPLY
    return ""


# ---------------------------------------------------------------- "that is not done in chat, it is done there"


@lru_cache(maxsize=1)
def _redirects() -> list[tuple[re.Pattern[str], str]]:
    rows = json.loads((_DATA / "router_redirects.json").read_text(encoding="utf-8"))
    out = []
    for row in rows:
        out.append((re.compile(str(row["re"])), str(row["reply"])))
    return out


def redirect_reply(text: str) -> str:
    """Requests the chat cannot do, answered with the page that can (data/router_redirects.json)."""
    folded = fold(text)
    if not folded:
        return ""
    for pattern, reply in _redirects():
        if pattern.search(folded):
            return reply
    return ""


# ---------------------------------------------------------------- what a model wrote

_FENCE = re.compile(r"```[a-z]*\n?|```")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*[-*•]\s+", re.M)
_BLANKS = re.compile(r"\n{3,}")


def strip_markdown(text: str) -> str:
    """The chat bubble shows plain text: **bold**, # headings and ``` fences would be shown as symbols."""
    value = _FENCE.sub("", text or "")
    value = value.replace("`", "")
    value = _BOLD.sub(r"\2", value)
    value = _ITALIC.sub(r"\1", value)
    value = _HEADING.sub("", value)
    value = _BULLET.sub("• ", value)
    return _BLANKS.sub("\n\n", value).strip()


# "می" / "نمی" glued to a verb stem with no half-space: نمیکنم، میتوانم، میخوام، میشه، میدانم ...
# Only stems that cannot start another word are listed: میز، میوه، میدان، میگو، میدیا، میگرن stay untouched.
# letters only: «؛ ، ؟» sit inside \u0600-\u06FF too, and «نمیکنه؛» must still be repaired
_LETTERS = "\u0621-\u064A\u0670-\u06D3"
_L = rf"(?![{_LETTERS}])"
_STEMS = (
    r"توان\w*", rf"تون(?:م|ی|ه|یم|ید|ن){_L}", r"خواه\w*", rf"خوا(?:م|ی|د|ه|یم|ید|ن){_L}", r"خوان\w*", r"خور\w*",
    rf"کن(?:م|ی|ه|د|یم|ید|ند|ن){_L}", rf"کش(?:م|ی|ه|د|یم|ید|ند){_L}", r"شو\w*", rf"ش(?:ه|م|ی|یم|ید|ن){_L}",
    rf"گوی(?:د|م|ی|یم|ید|ند){_L}", rf"گ(?:م|ی|ه|یم|ید|ن){_L}", rf"رو(?:م|د|ی|یم|ید|ند){_L}", rf"ر(?:م|ی|ه|یم|ید|ن){_L}",
    rf"ده(?:م|د|ی|یم|ید|ند){_L}", rf"د(?:م|ی|ه|یم|ید|ن){_L}", r"بین\w*", r"باش\w*", r"گیر\w*", r"گذار\w*",
    r"پذیر\w*", r"فرست\w*", r"شناس\w*", r"نویس\w*", rf"دان(?:م|د|یم|ید|ند){_L}", rf"دون(?:م|ی|ه|یم|ید|ن){_L}",
    r"پرس\w*", r"ساز\w*", r"سپار\w*", r"یاب\w*", r"افت\w*", r"ماند\w*", rf"بر(?:م|ی|ه|د|یم|ید|ن){_L}",
    rf"زن(?:م|ی|ه|د|یم|ید|ن){_L}",
)
_MI_VERB = re.compile(rf"(?<![{_LETTERS}\u200c])(ن?می)(?=(?:" + "|".join(_STEMS) + "))")
_COMPOUND = {
    "قیمتگذاری": "قیمت‌گذاری",
    "پیشنویس": "پیش‌نویس",
    "دستساز": "دست‌ساز",
    "ویترینها": "ویترین‌ها",
}
# a word of three or more letters ending in a joining letter, then ها with no half-space: کیفها، باتریها
_PLURAL = re.compile(rf"([{_LETTERS}]{{3,}})ها(?![{_LETTERS}])")
_JOINERS = set("بتثجحخسشصضطظعغفقکگلمنهیپچ")


def fix_halfspace(text: str) -> str:
    """Models often drop the half-space (نمیکنم، کیفها). Only patterns that cannot be another word are touched."""
    value = _MI_VERB.sub(lambda m: m.group(1) + "\u200c", text or "")
    for wrong, right in _COMPOUND.items():
        value = value.replace(wrong, right)
    return _PLURAL.sub(lambda m: m.group(1) + ("\u200c" if m.group(1)[-1] in _JOINERS else "") + "ها", value)


_SENTENCE_END = re.compile(r"[.!؟?؛\n]")


def trim_to_sentence(text: str, *, minimum: int = 16) -> str:
    """A reply cut by the token limit is kept up to its last whole sentence instead of being thrown away."""
    value = (text or "").rstrip()
    ends = [m.end() for m in _SENTENCE_END.finditer(value)]
    if ends and ends[-1] >= minimum:
        return value[: ends[-1]].rstrip()
    cut = value.rsplit(" ", 1)[0] if " " in value else value
    return cut.rstrip(" ،,:;") + "…" if len(value) >= minimum else ""


# ---------------------------------------------------------------- card and sheba typed into the chat

_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){15}\d(?!\d)")
_SHEBA = re.compile(r"\bir\s*(?:\d\s*){24}", re.I)
SENSITIVE_REPLY = "شمارهٔ کارت یا شبا را در چت ننویس؛ من آن‌ها را نگه نمی‌دارم. شبا را از بیشتر ← کیف پول ثبت کن."


def has_payment_number(text: str) -> bool:
    folded = fold(text).replace(" ", " ")
    return bool(_CARD.search(folded) or _SHEBA.search(folded))


def mask_payment(text: str) -> str:
    """The seller's own card or sheba never stays in the saved chat."""
    value = str(text or "")
    if not has_payment_number(value):
        return value
    ascii_value = value.translate(_TO_ASCII)
    ascii_value = _SHEBA.sub("[شبا]", ascii_value)
    return _CARD.sub("[کارت]", ascii_value)


def price_problem(text: str, price: int) -> str:
    """A price the catalog must not take: negative, or beyond ten billion toman."""
    folded = fold(text)
    if "منفی" in folded or re.search(r"(?<![\w])-\s*\d", folded):
        return "قیمت باید بیشتر از صفر باشد."
    if int(price or 0) > 10_000_000_000:
        return "این قیمت خیلی بالاست؛ عدد را دوباره بنویس."
    return ""


# ---------------------------------------------------------------- what is (not) a shop build, what answers a question

_NOT_LETTER = r"(?<![\u0621-\u064A\u0670-\u06D3])"
_CONTENT = re.compile(_NOT_LETTER + r"(?:پست|کپشن|استوری|ریلز|بنر|تبلیغ)(?![\u0621-\u064A\u0670-\u06D3])")
_CONTENT_SKIP = re.compile(r"پست\s*(?:پیشتاز|سفارشی|ایران)|با\s*پست|ارسال")
_STORE_WORD = r"(?:فروشگاه|ویترین|سایت|وب.?سایت)"
_NOT_CONTENT = r"(?:(?!پست|کپشن|استوری|ریلز|بنر|تبلیغ).){0,24}"
_STORE_BUILD = re.compile(rf"{_STORE_WORD}{_NOT_CONTENT}(?:بساز|درست\s*کن|طراحی)|(?:بساز|درست\s*کن|طراحی){_NOT_CONTENT}{_STORE_WORD}")


def is_content_request(text: str) -> bool:
    """A post / caption / story request is never a shop build, even when the seller has no shop yet:
    «برای انگشتر یک پست بساز» builds a post. «فروشگاه بساز، ارسال با پست پیشتاز» is still a shop."""
    value = text or ""
    if not _CONTENT.search(_CONTENT_SKIP.sub(" ", value)):
        return False
    return _STORE_BUILD.search(value) is None


_COMPLAINT = re.compile(r"بد[یه]|هیچ|نمی.?کن|چرا|احمق|بی.?فایده|خراب|مزخرف|ضعیف|اشتباه")
_BARE = {"بله", "آره", "نه", "نخیر", "باشه", "اوکی", "ok", "خب", "خوب", "آهان", "هوم"}


def answers_ask(asked: str, spoken: str) -> bool:
    """Whether `spoken` can be the answer to Sozan's own question, not a bare yes/no or a complaint
    that only happens to be short (those are new turns; gluing them to the old request invents a command)."""
    compact = re.sub(r"[\s؟?!.،]+", " ", spoken or "").strip().lower()
    if not compact or compact in _BARE or _COMPLAINT.search(compact):
        return False
    if ("قیمت" in asked or "تومان" in asked) and not re.search(r"[\d۰-۹]", compact):
        return False
    return True


_ACTION_CHIP = re.compile(r"(?:کن|بزن|بساز|بنویس|حذف|پاک|بفرست|منتشر|عوض|پنهان)(?![\u0621-\u064A\u0670-\u06D3])")


def clean_options(question: str, options: list[str]) -> list[str]:
    """Tap answers under a question must be answers: short, not commands («قیمت را پنهان کن»), and numbers for a price question.
    A tap sends the text as the seller's next message, so a chip that is really a command would run something the seller never meant."""
    price_question = "قیمت" in question or "تومان" in question
    kept: list[str] = []
    for item in options:
        text = re.sub(r"\s+", " ", str(item)).strip()
        if not text or len(text.split()) > 5 or len(text) > 40 or text in kept or _ACTION_CHIP.search(text):
            continue
        if price_question and not re.search(r"[\d۰-۹٠-٩]", text):
            continue
        kept.append(text)
    return kept[:5]
