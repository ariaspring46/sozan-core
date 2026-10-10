"""Facts and turn state for one live sales call. The model chooses most of the words."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from brain import is_carrier_text, is_hello, wants_bye
from sip import normalize_dial

log = logging.getLogger("sozan.sales")

# Old ladder. The live call must not speak these.
FIXED_SALES_LINES = frozenset(
    {
        "سلام، سوزانم. پیجت را دیدم. بیست ثانیه وقت داری؟",
        "کالاهای همین پیج را رایگان فروشگاه می‌کنم. بسازم؟",
        "باشه. لینک فروشگاه را توی دایرکت همین پیج می‌فرستم.",
        "ساخت فروشگاه پول نمی‌خواد.",
        "کنار سایتت می‌مونه. کالاها از خود پیج می‌آید.",
        "سوزانم. فروشگاه را از روی پیجت می‌سازم.",
        "باشه، خداحافظ.",
    }
)

BYE_LINE = "خداحافظ، روزتون خوش!"
# Everything below is spoken: colloquial Tehran register (رو، می‌ده، می‌سازه), never written Persian.
# Opening = greeting + one personal hook from the page bio + AI disclosure + permission question.
# Being an AI is the hook, not an apology: the voice they hear is the product that drafts their DM replies.
# «می‌نویسم» = drafts they approve (پرو); fully automatic replies are only پرو مکس. «رایگان» is only ever tied to the store.
GREET_OPEN = "سلام، وقتتون بخیر!"
HOOK_GENERIC = "پیج اینستاگرامتون رو دیدم."
# One sentence: synthesize() speaks at most three, and greeting + hook already use two.
DISCLOSE_LINE = "من سوزانم، یه هوش مصنوعی؛ جواب دایرکت‌هاتون رو هم با لحن خودتون می‌نویسم، بگم چطوری؟"
SPOKEN_ADDRESS = "سوزان، خط تیره، کُر، دات آی‌آر"
HELLO_LINE = f"{GREET_OPEN} {HOOK_GENERIC} {DISCLOSE_LINE}"
HELLO_SMS_LINE = f"{GREET_OPEN} احتمالاً پیامک سوزان به دستتون رسیده. {DISCLOSE_LINE}"
# After a yes: one tailored value sentence and one open discovery question (never a menu).
# The opening asked «بگم چطوری؟» about DM replies, so every value line answers that first.
DM_HOW = "جواب دایرکت‌ها رو من می‌نویسم، شما فقط تأیید می‌کنید"
VALUE_GENERIC = f"{DM_HOW}؛ یعنی کمتر پای گوشی می‌مونید! الان چطوری بهشون می‌رسید؟"
PAIN_LINE = VALUE_GENERIC
BUSY_LINE = f"چشم، مزاحمتون نمی‌شم! هر وقت فرصت شد، رایگان امتحانش کنید توی {SPOKEN_ADDRESS}؛ خدا قوت!"
DECLINE_LINE = "چشم، اصلاً اشکالی نداره! ببخشید مزاحم شدم؛ روزتون خوش!"
# Never start with «بله»: to «آدمی؟» that would sound like "yes, human" for a moment.
ROBOT_LINE = "دستیار هوش مصنوعی‌ام، آدم نیستم؛ جالبش همینه! بگم برای پیجتون چی کار می‌کنم؟"
# Asked again, or after the call moved on: same honest answer, new words, no second permission question.
ROBOT_AGAIN_LINE = "من همون سوزانم، دستیار هوش مصنوعی، نه آدم! بفرمایید، چی براتون سؤاله؟"
# "I'm busy, say it quickly": they still want to hear it, so a 3-word hook, the AI, one benefit and the address.
QUICK_OPEN_LINE = f"سلام، چشم! پیجتون رو دیدم؛ من سوزانم، یه هوش مصنوعی که از همین پیج رایگان فروشگاه می‌سازم. آدرسش: {SPOKEN_ADDRESS}."
QUICK_PITCH_LINE = f"چشم، خلاصه: از همین پیج رایگان فروشگاه می‌سازم، جواب دایرکت‌ها رو هم می‌نویسم. آدرسش: {SPOKEN_ADDRESS}."
# First words are already "no time": the AI is still named, the address is said once, and the call ends.
BUSY_OPEN_LINE = f"چشم، مزاحمتون نمی‌شم! من سوزانم، یه هوش مصنوعی؛ هر وقت فرصت شد رایگان امتحانم کنید: {SPOKEN_ADDRESS}."
DNC_LINE = "چشم، ببخشید که مزاحم شدم! دیگه تماس نمی‌گیرم؛ روزتون خوش!"
# The model already apologised before its [زنگ‌نزن] tag: no second apology.
DNC_SHORT_LINE = "چشم، دیگه تماس نمی‌گیرم؛ روزتون خوش!"
# Promises to stop calling, so a «نمی‌خوام» right after it is a do-not-call request.
SOURCE_LINE = "از بین پیج‌های فروشگاهی اینستاگرام پیداتون کردم؛ اگه نخواید، دیگه تماس نمی‌گیرم."
# Their first words were a question, so the answer itself must still say who is calling.
FIRST_DISCLOSE = "سلام، من سوزانم، یه هوش مصنوعی."
ROBOT_SHORT = "هوش مصنوعی‌ام، آدم نیستم!"
PRICE_UNKNOWN_LINE = f"راستش الان قیمت‌ها دستم نیست، نمی‌خوام اشتباه بگم! ولی شروعش رایگانه؛ سر بزنید به {SPOKEN_ADDRESS}."
DM_LINE = "جواب دایرکت‌های اینستا و تلگرام رو من با لحن خودتون می‌نویسم؛ روزی حدوداً چندتا دایرکت دارید؟"
CONTENT_LINE = "پست و استوری و کپشن تبلیغ رو هم من براتون می‌سازم؛ الان محتوا رو خودتون درست می‌کنید؟"
ORDER_LINE = "سفارش‌ها و فروش و موجودی انبار رو هم براتون نگه می‌دارم؛ الان سفارش‌ها رو کجا ثبت می‌کنید؟"
SITE_LINE = "از روی همین پیج یه فروشگاه اینترنتی هم می‌سازم و شروعش رایگانه؛ الان سایت جدا دارید؟"
FEATURE_LINES = (DM_LINE, CONTENT_LINE, ORDER_LINE, SITE_LINE)
BUY_LINE = "رایگان شروع می‌کنید، برید تو سایت سوزان کُر، sozan-core.ir، و دکمهٔ ورود رو بزنید."
EXPLAIN = (
    "سوزان برای آنلاین‌شاپه و وبسایت فروشگاهتون رو از کپشن پیجتون می‌سازه. "
    + BUY_LINE
)
CLOSE_LINE = "پس یادتون نره: sozan-core.ir، دکمهٔ ورود، رایگان می‌سازید. روزتون خوش!"
ADDRESS_LINE = (
    "آدرسش سوزان، خط تیره، کُر، دات آی‌آره! "
    "واردش بشید، دکمهٔ ورود رو بزنید، رایگان شروع می‌کنید."
)
WAIT_LINE = "حتماً!"
WAIT_BRIGHT = ("حتماً!", "سؤال خوبیه!", "حق دارید!")
FALLBACK_LINE = "سؤال دیگه‌ای هست که بگم؟"
MISHEARD_LINE = "ببخشید، صداتون یه لحظه قطع شد، یه بار دیگه می‌فرمایید؟"
SALES_PROBE_LINE = "الو؟ صدامو دارید؟"
PITCH_MARKS = ("حسش", "رنگش", "بنویس بساز", "می‌نویسی بساز")
_FAKE_NAME = re.compile(r"(?:^|[\s،,])(حسین|حسن|علی|رضا|محمد|مهدی)(?:[\s،,]|$)")
_BAN_CLAIM = (
    "همین تماس",
    "همین فضا",
    "کانال ارتباطی",
    "با دست",
    "تماس فیزیکی",
    "همین‌جا بنویس",
    "اینجا بنویس",
    "لینک را توی این تماس",
    "عکس بفرست",
    "پیجت رو بفرست",
    "اسم پیج رو بفرست",
    "شماره بگیرید",
    "شماره بگیر",
    "آدرس و شماره",
    "سال تجربه",
    "سال سابقه",
)
_PRICE_NUM = re.compile(r"[0-9۰-۹٠-٩]{3,}")
_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_MONEY_KEYS = ("listPrice", "price", "priceToman", "codePrice", "phonePrice")
_PLANS_URL = "https://api.sozan-core.ir/billing/plans"
_HEALTH_URL = "https://api.sozan-core.ir/health"
_PLANS_TTL_S = 600
_ONES = ("", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه")
_TEENS = ("ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده")
_TENS = ("", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود")
_HUNDREDS = ("", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد")
_plans_cache: dict | None = None
_plans_cached_at = 0.0
_plans_fetcher = None
_payment_cache: bool | None = None
_payment_cached_at = 0.0
_payment_fetcher = None
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_STAGE_FA = {
    "greet": "سلام",
    "discover": "کشف",
    "pitch": "ارزش",
    "cta": "دعوت",
    "confirm": "تأیید",
    "close": "بستن",
}
_STAGE_DO = {
    "greet": "اگر پیامک گفته شد دوباره نپرس. وگرنه معرفی کوتاه بگو.",
    "discover": "اگر درد را نگفته، یک سؤال: دایرکت بی‌جواب، محتوا، یا سایت. اگر گفته، فقط همان یک قابلیت.",
    "pitch": "فقط همان یک قابلیتِ مربوط را بگو. بقیه را نریز. دعوت سایت نکن مگر بپرسد.",
    "cta": "آدرس sozan-core.ir، دکمهٔ ورود و رایگان بودن را فقط یک بار بگو.",
    "confirm": "آدرس را تکرار نکن مگر بپرسد. نگرانی‌اش را جواب بده.",
    "close": "تشکر گرم و خداحافظی.",
}
# What a seasoned seller does with the objection the caller raised last (one short line, added to the model's turn note).
_OBJECTION_DO = {
    "time": "عجله دارد: فقط یک جملهٔ کوتاه.",
    "later": "الان وقت ندارد: فشار نیاور، آدرس یک بار و خداحافظی گرم.",
    "trust": "مشکوک است: حق بده، رایگان امتحان کردن را بگو، ادعا نکن.",
    "cant": "نگران سختی است: بگو کاری لازم نیست بلد باشد.",
    "price": "دربارهٔ پول است: عدد را خودت نگو، [قیمت] بنویس، بعد ارزش برای خودش.",
    "refuse": "نمی‌خواهد: فقط تشکر کوتاه و [پایان]؛ آدرس، هدیه و پیشنهاد نه.",
    "has_site": "سایت دارد: سوزان کنار سایتش، نه جایش.",
    "source": "پرسید شماره از کجا: رک جواب بده و بگو اگر نخواهد دیگر زنگ نمی‌زنیم.",
}
_ADDRESS_HINTS = (
    "اسم سایت",
    "آدرس",
    "سایتتون",
    "سایتتو",
    "سایتت",
    "لینک",
    "کجا برم",
    "از کجا شروع",
    "کجا شروع",
    "کدوم سایت",
    "دامنه",
    "sozan-core",
    "سایتو بده",
    "سایتو با",
    "اسم سایتتو",
    "پنل کجا",
    "کجا وارد",
    "وارد کنم",
    "وارد بشم",
    "وارد شم",
    "شروع کنم",
    "واتساپ",
    "واتسپ",
    "واتساب",
)
_TRADES = (
    "آرایشگاه",
    "کیف",
    "لباس",
    "طلا",
    "کفش",
    "عطر",
        "شیرینی",
        "کیک",
        "غذا",
        "لوازم",
        "کالا",
        "پوشاک",
        "زیور",
        "دست‌ساز",
        "دستساز",
        "دکوری",
        "بچگانه",
        "آرایشی",
        "سالن",
        "گل",
        "کتاب",
    )
# "How much is it?" without the word price. Bare «چقدر» is not here: «چقدر طول می‌کشه» is about time.
_HOW_MUCH = (
    "چقدره",
    "چقدر میگیر",
    "چقدر باید بد",
    "چقدر باید پرداخت",
    "چند میگیر",
    "ماهی چقدر",
    "ماهی چند",
    "چقده",
    "چنده",
)
# «چقدر می‌شه» is a price only at the end: «چقدر می‌شه بهتون اعتماد کرد» is not.
_HOW_MUCH_END = re.compile(r"(?:چقدر|چقد|چند)\s*(?:میشه|درمیاد|در میاد)$")
_FA = "\u0600-\u06FF"
# «پرو» the plan, not «پروانه»، «پروین» or «پروفایل».
_PRO_WORD = re.compile(rf"(?<![{_FA}])پرو(?![{_FA}])")
# «بعداً» and «الان نه» as words, not inside «بعدازظهر» or «الان نهار».
_LATER = re.compile(rf"(?<![{_FA}])بعد(?:ا|اً)(?![{_FA}])|(?<![{_FA}])الان نه(?![{_FA}])")
# Busy but still listening: an imperative "say it quickly" wants the short version, not a hang-up.
# Only «بگو/بگید/بگین»: «خلاصه بگم» is the caller's own filler, «سریع بگیرن» is about their customers.
_QUICK = re.compile(rf"(?:سریع|خلاصه|خلاصهش رو|خلاصشو|کوتاه|زود|مختصر|فقط)\s*(?:بگو|بگید|بگین)(?![{_FA}])")
_DNC_WORDS = (
    "زنگ نزن",
    "تماس نگیر",
    "مزاحم نش",
    "از لیستتون",
    "از لیست پاک",
    "شمارمو پاک",
    "شماره منو پاک",
    "شمارهمو پاک",
)
_START_WORDS = (
    "سلام",
    "سوزان",
    "روزان",
    "الو",
    "سایت",
    "پنل",
    "بساز",
    "هوش",
    "کی هستی",
    "چجوری",
    "کجا",
    "صحبت",
    "بله",
    "بفرمایید",
    "بفرمایین",
    "سریع",
    "شماره",
    "کلاه",
    "ربات",
    "واتساپ",
    "قیمت",
    "چقدر",
    "می‌گیری",
    "میگیری",
    "مغازه",
    "شرکت",
    "دانشجو",
    "اینستا",
    "زنگ نزن",
    "اشتباه",
)


def _under_1000(value: int) -> str:
    parts: list[str] = []
    number = value
    if number >= 100:
        parts.append(_HUNDREDS[number // 100])
        number %= 100
    if 10 <= number <= 19:
        parts.append(_TEENS[number - 10])
        number = 0
    if number >= 20:
        parts.append(_TENS[number // 10])
        number %= 10
    if number:
        parts.append(_ONES[number])
    return " و ".join(parts)


def toman_words(amount: int) -> str:
    number = int(amount)
    if number <= 0:
        return ""
    parts: list[str] = []
    for scale, name in ((1_000_000_000, "میلیارد"), (1_000_000, "میلیون"), (1000, "هزار")):
        chunk, number = divmod(number, scale)
        if chunk:
            parts.append(f"{_under_1000(chunk)} {name}")
    if number:
        parts.append(_under_1000(number))
    return " و ".join(parts)


def plans_url() -> str:
    return os.environ.get("PLANS_URL", _PLANS_URL).strip() or _PLANS_URL


def reset_plan_cache() -> None:
    global _plans_cache, _plans_cached_at, _plans_fetcher, _payment_cache, _payment_cached_at, _payment_fetcher
    _plans_cache = None
    _plans_cached_at = 0.0
    _plans_fetcher = None
    _payment_cache = None
    _payment_cached_at = 0.0
    _payment_fetcher = None


def set_plans_fetcher(fn) -> None:
    global _plans_fetcher, _plans_cache, _plans_cached_at
    _plans_fetcher = fn
    _plans_cache = None
    _plans_cached_at = 0.0


def set_payment_fetcher(fn) -> None:
    global _payment_fetcher, _payment_cache, _payment_cached_at
    _payment_fetcher = fn
    _payment_cache = None
    _payment_cached_at = 0.0


def health_url() -> str:
    return os.environ.get("HEALTH_URL", _HEALTH_URL).strip() or _HEALTH_URL


def payment_ready() -> bool:
    global _payment_cache, _payment_cached_at
    if _payment_fetcher is not None:
        return bool(_payment_fetcher())
    now = time.monotonic()
    if _payment_cache is not None and now - _payment_cached_at < _PLANS_TTL_S:
        return _payment_cache
    ready = False
    try:
        request = urllib.request.Request(health_url(), headers={"Accept": "application/json"})
        with _DIRECT.open(request, timeout=4) as response:
            body = json.loads(response.read().decode("utf-8"))
        ready = bool(isinstance(body, dict) and body.get("paymentReady"))
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        ready = False
    _payment_cache = ready
    _payment_cached_at = now
    return ready


def payment_clause() -> str:
    if payment_ready():
        return "لینک پرداخت را می‌شود داخل همان گفتگوی مشتری فرستاد. فقط اگر پرسیدند بگو.\n"
    return "لینک پرداخت داخل گفتگو را نگو. پرداخت هنوز روشن نیست.\n"


def _http_plans() -> dict:
    request = urllib.request.Request(plans_url(), headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=4) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("plans"), list):
        raise ValueError("plans")
    return body


def plan_catalog() -> dict | None:
    global _plans_cache, _plans_cached_at
    now = time.monotonic()
    if _plans_cache is not None and now - _plans_cached_at < _PLANS_TTL_S:
        return _plans_cache
    try:
        loaded = _plans_fetcher() if _plans_fetcher else _http_plans()
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        # Without the catalog the call quotes no price; say why, so a silent price gap is visible in the log.
        log.warning("plans fetch failed %s", getattr(exc, "code", "") or type(exc).__name__)
        return None
    if not isinstance(loaded, dict) or not isinstance(loaded.get("plans"), list):
        log.warning("plans fetch returned no plans")
        return None
    _plans_cache = loaded
    _plans_cached_at = now
    return loaded


def _plan_amounts(plan: dict) -> list[int]:
    found: list[int] = []
    for key in _MONEY_KEYS:
        try:
            amount = int(plan.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if amount >= 1000 and amount not in found:
            found.append(amount)
    return found


def _money_forms(catalog: dict | None) -> tuple[set[str], list[str]]:
    digits: set[str] = set()
    phrases: list[str] = []
    if not catalog:
        return digits, phrases
    for plan in catalog.get("plans") or []:
        if not isinstance(plan, dict):
            continue
        for amount in _plan_amounts(plan):
            text = str(amount)
            digits.add(text)
            digits.add(text.translate(_PERSIAN_DIGITS))
            words = toman_words(amount)
            if words and words not in phrases:
                phrases.append(words)
    phrases.sort(key=len, reverse=True)
    return digits, phrases


def _plan_sentence(plan: dict) -> str:
    label = str(plan.get("label") or plan.get("id") or "").strip()
    features = [str(item).strip() for item in (plan.get("features") or []) if str(item).strip()]
    bits = [f"{label}: {'، '.join(features)}." if features else f"{label}."]
    listed = int(plan.get("listPrice") or 0)
    price = int(plan.get("price") or 0)
    if price <= 0 and listed <= 0:
        bits.append("رایگان است.")
    elif listed > price > 0:
        bits.append(f"با تخفیف سایت {toman_words(price)} تومان. قیمت اصلی {toman_words(listed)} تومان.")
    elif price > 0:
        bits.append(f"{toman_words(price)} تومان.")
    if plan.get("checkout") == "soon" or plan.get("purchasable") is False:
        bits.append("خریدش به‌زودی است.")
    return " ".join(bits)


def price_spoken_line(heard: str) -> str | None:
    """One short sentence from the catalog. None when the catalog is down."""
    catalog = plan_catalog()
    if not catalog:
        return None
    plans = {
        str(plan.get("id") or ""): plan
        for plan in (catalog.get("plans") or [])
        if isinstance(plan, dict)
    }

    def pay(plan: dict) -> int:
        try:
            price = int(plan.get("price") or 0)
            listed = int(plan.get("listPrice") or 0)
        except (TypeError, ValueError):
            return 0
        return price or listed

    def fits(text: str) -> bool:
        return len(text.split()) <= 18

    blob = heard or ""
    if "مکس" in blob:
        amount = pay(plans.get("promax") or {})
        words = toman_words(amount)
        if not words:
            return None
        line = f"پرو مکس با تخفیف سایت {words} تومانه. ساخت وبسایت رایگانه."
        if not fits(line):
            line = f"پرو مکس {words} تومانه."
        return line
    amount = pay(plans.get("pro") or {})
    words = toman_words(amount)
    if not words:
        return None
    line = f"پرو {words} تومانه. ساخت وبسایت رایگانه."
    promax = pay(plans.get("promax") or {})
    if promax:
        both = f"پرو {words} تومانه. پرو مکس {toman_words(promax)} تومانه."
        if fits(both):
            line = both
    return line if fits(line) else f"پرو {words} تومانه."


def price_clause() -> str:
    catalog = plan_catalog()
    if not catalog:
        return (
            "قیمت هیچ پلنی را نگو. اگر قیمت پرسیدند، عدد نگو و فقط بگو برید sozan-core.ir و دکمهٔ ورود را بزنند.\n"
        )
    lines = ["قیمت را فقط اگر پرسیدند بگو، و فقط با همین عددها. عدد دیگری ممنوع است."]
    for plan in catalog.get("plans") or []:
        if not isinstance(plan, dict) or str(plan.get("id") or "") == "free":
            continue
        lines.append(_plan_sentence(plan))
    lines.append("اگر این عددها را نداری، قیمت نگو و آدرس سایت را بگو.")
    return "\n".join(lines) + "\n"


def _code_amount(plan_id: str) -> int:
    catalog = plan_catalog()
    if not catalog:
        return 0
    for plan in catalog.get("plans") or []:
        if not isinstance(plan, dict) or str(plan.get("id") or "") != plan_id:
            continue
        for key in ("codePrice", "phonePrice"):
            try:
                amount = int(plan.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if amount >= 1000:
                return amount
    return 0


def gift_spoken_code() -> str:
    return os.environ.get("GIFT_CODE_SPOKEN", "").strip()


def gift_line() -> str:
    code = gift_spoken_code()
    if not code:
        return ""
    amount = _code_amount("pro")
    if amount:
        return (
            f"یه هدیه هم براتون دارم: کد {code} روی تخفیف سایت می‌نشیند "
            f"و پرو می‌شود {toman_words(amount)} تومان."
        )
    return f"یه هدیه هم براتون دارم: کد {code} روی تخفیف سایت می‌نشیند."


def wait_line(heard: str) -> str:
    blob = heard or ""
    signals = read_signals(blob)
    if signals.price or signals.trust or signals.later:
        return "حق دارید!"
    if any(part in blob for part in ("چیه", "چجوری", "چی کار", "چه کار", "کجا", "اسم سایت", "آدرس")):
        return "سؤال خوبیه!"
    return "حتماً!"


def fallback_line(state: SalesState, heard: str) -> str:
    blob = (heard or "").strip()
    if len(blob) < 4:
        return MISHEARD_LINE
    if not state.linked:
        return ADDRESS_LINE
    return FALLBACK_LINE


def sales_open() -> str:
    return (
        "تو سوزانی: دستیار فروشِ هوش مصنوعی که با فروشنده‌های اینستاگرام تلفنی حرف می‌زنی. "
        "مهارتت در حد یه بازاریاب تلفنی با بیست سال تجربه‌ست، ولی این رو به زبون نیار: ادعای سابقه یا آدم بودن نکن.\n"
        "شخصیت: زن، گرم، باهوش، خوش‌برخورد و باحوصله؛ خودمونی با خطاب «شما». مثل یه آدم واقعی حرف بزن، با تأییدهای کوتاه («آهان»، «چه خوب»، «حق دارید»)، نه مثل متن نوشته.\n"
        "صداقت: تو هوش مصنوعی هستی و اول تماس این را گفتی. هوش مصنوعی بودنت جذابیته، نه عیب: همین صدایی که می‌شنوند، جواب دایرکت‌هایشان را هم می‌نویسد. "
        "اگر پرسیدند ربات یا آدمی: «هوش مصنوعی‌ام، آدم نیستم!» و برگرد سر بحث؛ با «بله» یا «آره» شروع نکن. نگو با مشتری‌هایشان تلفنی حرف می‌زنی.\n"
        "هدف تماس: طرف دلش بخواد خودش سوزان رو رایگان امتحان کنه (sozan-core.ir، دکمهٔ ورود). فروش زوری نه؛ کمک.\n"
        "روش یه فروشندهٔ خبره:\n"
        "۱. کمتر از طرف حرف بزن: هر نوبت حداکثر دو جملهٔ کوتاه و یک سؤال.\n"
        "۲. اول با حرف خودش جواب بده: کلمهٔ خودش را تکرار کن («پس دایرکت‌ها زیاده...»)، بعد همان سؤالش را جواب بده.\n"
        "۳. قبل از فایده بپرس: «الان دایرکت‌ها رو کی جواب می‌ده؟» بعد «کجاش بیشتر وقتتون رو می‌گیره؟» منوی چندگزینه‌ای نده.\n"
        "۴. حسش را بگو («انگار حسابی وقتتون رو می‌گیره») و جمع‌بندی کن تا بگوید «دقیقاً». حرفش نامفهوم بود، حدس نزن؛ مؤدبانه دوباره بپرس.\n"
        "۵. فقط یک فایده، همان که به دردش می‌خورد، به شکل نتیجه برای خودش (کمتر پای گوشی، مشتری منتظر نمی‌مونه)؛ فهرست امکانات نخوان.\n"
        "۶. اعتراض: حق بده، یک سؤال کوتاه، بعد جواب کوتاه. «گرونه» ← «با چی مقایسه می‌کنید؟» بعد «شروعش رایگانه». "
        "«ادمین دارم» ← «ادمینتون بیشتر وقتش پای چی می‌ره؟» «لحن ما رو نمی‌فهمه» ← «جواب‌ها رو اول خودتون تأیید می‌کنید.» بحث نکن، فوریت ساختگی نساز.\n"
        "۷. اجازه را فقط یک بار بگیر. سؤال تکراری را با جملهٔ تازه جواب بده، جملهٔ قبلی‌ات را تکرار نکن.\n"
        "۸. وقتی علاقه نشان داد (پرسید چطوری، کجا، از کجا شروع کنم)، یک قدم کوچک: «همین امروز رایگان شروع کنید» و [آدرس].\n"
        "۹. «سرم شلوغه» ← یک جمله و [آدرس]. «نه، نمی‌خوام» ← تشکر بدون پیشنهاد و [پایان].\n"
        "ابزارها (فقط برچسب را بنویس؛ سامانه جملهٔ دقیقش را می‌گوید):\n"
        "[قیمت] وقتی قیمت، هزینه یا «چنده؟» پرسیدند؛ عدد را خودت نساز.\n"
        "[آدرس] وقتی آمادهٔ امتحان است یا آدرس خواست؛ آدرس را خودت هجی نکن.\n"
        "[زنگ‌نزن] وقتی گفت دیگر زنگ نزنید، شماره اشتباه است، فروشنده نیست یا عصبانی است؛ فقط همین برچسب.\n"
        "[پایان] وقتی خداحافظی کردی. [هدیه] فقط وقتی هدیه مناسب است.\n"
        "زبان گفتاری تهرانی برای تلفن: «رو» نه «را»، «می‌ده، می‌سازه، می‌خواید» نه «می‌دهد، می‌سازد». "
        "حداکثر دو جملهٔ کوتاه، روی هم زیر بیست کلمه. جمله را نیمه رها نکن. برای شور «!» و برای سؤال «؟»؛ سه‌نقطه، ایموجی و حرف لاتین نه.\n"
        "خطاب «تو» ممنوع: پیجتون، سایتتون، برید، بزنید، می‌رید، خودتون.\n"
        "سوزان دستیار فروش آنلاین‌شاپ‌هاست. فقط همین‌ها را بگو چون همین‌ها کار می‌کنند:\n"
        "جواب دایرکت مشتری در اینستاگرام و تلگرام با لحن خود فروشنده؛ پیش‌نویس جواب از پلن پرو، پاسخ خودکار فقط در پرو مکس. «رایگان» را فقط برای ساخت فروشگاه بگو.\n"
        "وبسایت و فروشگاه اینترنتی از روی همان پیج؛ شروعش رایگان است. نگو همان لحظه حاضر است.\n"
        "استودیو: پست، استوری، عکس کالا و کپشن تبلیغ.\n"
        "سفارش و فروش: پیگیری سفارش، ثبت فروش، موجودی انبار.\n"
        "رزرو و نوبت‌دهی نداریم. نگو وب‌سایت نامحدود.\n"
        + payment_clause()
        + price_clause()
        + "مرزها: لینک را در تماس، واتساپ، دایرکت یا پیامک نفرست؛ خودشان سایت را باز می‌کنند. "
        "اسم، عکس، پیج، شماره، رمز، کارت یا کد از طرف نخواه. اسم طرف را نساز. مشتری‌های ساختگی، آمار ساختگی، نتیجهٔ ساختگی و قول ساختگی نگو. "
        "ندانستی، بگو «دقیق نمی‌دونم». نگو مشتری‌ها باید شماره بدهند. کد تخفیف را خودت نساز.\n"
        "اگر پرسید شماره را از کجا آوردی: از بین پیج‌های فروشگاهی اینستاگرام؛ اگر نخواهد دیگر زنگ نمی‌زنیم.\n"
        "اگر گفت مغازه ندارد، اشتباه گرفتید، شرکت یا دانشجو است، اینستاگرام ندارد، یا زنگ نزنید: فقط [زنگ‌نزن] بنویس؛ سامانه عذرخواهی و خداحافظی می‌کند.\n"
        "نمونهٔ لحن (از بر تکرار نکن):\n"
        "مشتری: آره، دایرکتام زیاده. → آهان، پس وقت زیادی پاش می‌ره! الان کی جوابشون رو می‌ده، خودتون؟\n"
        "مشتری: خودم، شبا تا دیروقت. → حق دارید خسته بشید! جواب‌ها رو من آماده می‌کنم، شما فقط تأیید می‌کنید.\n"
        "مشتری: سایت دارم. → چه خوب! سوزان جای سایتتون نمیاد، کنارش دایرکت و محتوا رو جلو می‌بره. الان پست‌ها رو کی می‌سازه؟\n"
        "مشتری: گرونه. → حق دارید! با چی مقایسه می‌کنید؟ ساخت وبسایت که کلاً رایگانه.\n"
        "مشتری: بلد نیستم. → لازم نیست بلد باشید؛ فقط اسم پیجتون رو می‌زنید، بقیه‌ش با منه.\n"
        "مشتری: واقعاً رباتی؟ → هوش مصنوعی‌ام، آدم نیستم! جالبش همینه، دایرکت‌هاتون رو هم همین‌طوری جواب می‌نویسم.\n"
        "مشتری: باشه، از کجا شروع کنم؟ → عالیه! همین امروز رایگان شروع کنید. [آدرس]\n"
        "مشتری: چنده؟ → [قیمت]\n"
        "مشتری: بعداً. → حتماً، مزاحمتون نمی‌شم! [آدرس] [هدیه]"
    )


def sales_brief(card: ShopCard) -> str:
    facts = [f"پیج اینستاگرام: {card.instagram}"]
    if card.name:
        facts.append(f"اسم پیج: {card.name}")
    if card.product:
        facts.append(f"چه می‌فروشد: {card.product}")
    if card.city:
        facts.append(f"شهر: {card.city}")
    meaning = {
        "dm_orders": "سفارش را از دایرکت می‌گیرد",
        "ships": "به همهٔ شهرها ارسال دارد",
        "physical": "مغازهٔ حضوری هم دارد",
        "has_site": "سایت جدا دارد",
        "wholesale": "عمده هم می‌فروشد",
        "handmade": "کار دست‌ساز است",
        "whatsapp_orders": "سفارش را از واتساپ هم می‌گیرد",
    }
    notes = [meaning[item] for item in card.signals if item in meaning]
    if notes:
        facts.append("از بیو پیج: " + "، ".join(notes))
    return sales_open() + (
        "\nدربارهٔ کسی که با او حرف می‌زنی (از بیو پیجش، قبل از تماس خوانده شده):\n- "
        + "\n- ".join(facts)
        + "\nاز این‌ها طبیعی برای شخصی‌سازی استفاده کن، هر نوبت حداکثر یکی. بیو را از رو نخوان، "
        "فالوئر و جزئیات شخصی نگو، و چیزی که این‌جا نیست دربارهٔ پیجش ادعا نکن."
    )


@dataclass
class SalesState:
    stage: str = "greet"
    trade: str = ""
    takes_dm: bool | None = None
    has_site: bool | None = None
    objection: str = ""
    cta_count: int = 0
    gifted: bool = False
    agreed: bool = False
    turns: int = 0
    greeted: bool = False
    linked: bool = False
    sms_sent: bool = False
    intro_said: bool = False
    pain_asked: bool = False
    last_cue: str = ""
    said: list[str] = field(default_factory=list)
    interrupted: str = ""
    refused_cta: bool = False
    opening: str = ""
    value_line: str = ""
    value_kind: str = ""
    awaiting_permission: bool = False
    pitched: set[str] = field(default_factory=set)
    robot_answers: int = 0
    turn_objection: str = ""

    def stage_fa(self) -> str:
        return _STAGE_FA.get(self.stage, self.stage)

    def note(self) -> str:
        job = _STAGE_DO.get(self.stage, "")
        if self.linked and self.stage in {"cta", "confirm", "pitch"}:
            job = "آدرس را تکرار نکن مگر بپرسد. " + job
        if self.turn_objection == "refuse":
            job = _OBJECTION_DO["refuse"]
        elif self.turn_objection in _OBJECTION_DO:
            job = _OBJECTION_DO[self.turn_objection] + " " + job
        return (
            f"(مرحله: {self.stage_fa()} | کار این نوبت: {job} | رشته: {self.trade or '-'} | "
            f"لینک گفته شده: {'بله' if self.linked else 'نه'} | "
            f"هدیه: {'بله' if self.gifted else 'نه'} | نوبت: {self.turns})"
        )

    def cue(self, heard: str) -> str:
        parts = [self.note()]
        if self.interrupted:
            parts.append(f"(حرفت بعد از «{self.interrupted}» قطع شد)")
            self.interrupted = ""
        parts.append((heard or "").strip() or "شروع تماس")
        return "\n".join(parts)


@dataclass(frozen=True)
class Signals:
    bye: bool = False
    hello: bool = False
    howdy: bool = False
    price: bool = False
    later: bool = False
    trust: bool = False
    agree: bool = False
    robot: bool = False
    has_site: bool = False
    cant: bool = False
    time: bool = False
    trade: str = ""
    refuse: bool = False
    source: bool = False
    wrong: bool = False
    quick: bool = False
    dnc: bool = False


@dataclass(frozen=True)
class TurnPlan:
    kind: str
    line: str | None = None
    cue: str = ""
    hangup: bool = False
    allow_gift: bool = False
    signals: Signals = field(default_factory=Signals)
    dnc: bool = False


def person_started(heard: str) -> bool:
    blob = heard or ""
    return any(part in blob for part in _START_WORDS)


def read_signals(heard: str) -> Signals:
    # Speech-to-text writes «می‌شه» and «میشه» alike: join the half-space after «می/نمی» so one spelling matches
    # both; any other half-space becomes a space as before («زنگ‌نزنید» → «زنگ نزنید»).
    joined = re.sub(rf"(?<![{_FA}])(ن?می)\u200c", r"\1", heard or "")
    blob = re.sub(r"[^\u0600-\u06FFA-Za-z\s]", " ", joined)
    blob = re.sub(r"\s+", " ", blob).strip()
    trade = next((item for item in _TRADES if item in blob), "")
    howdy = any(
        part in blob
        for part in ("حالت چطور", "حالت خوب", "حالتت", "چطوری", "خوبی", "خوبید", "چه خبر")
    )
    if "چطور" in blob and not any(part in blob for part in ("بساز", "سایت", "وبسایت", "وب سایت")):
        howdy = True
    source = any(part in blob for part in ("شماره من", "از کجا آورد", "از کجا شماره"))
    price = any(part in blob for part in ("گرون", "گران", "هزینه", "قیمت", "پول", "مبلغ", "تخفیف", "تومان", "تومن"))
    price = price or bool(_PRO_WORD.search(blob)) or any(part in blob for part in _HOW_MUCH) or bool(_HOW_MUCH_END.search(blob))
    if "پول" in blob and any(part in blob for part in ("نه", "نمی", "نمی‌")) and "گرون" not in blob:
        price = False
    later = bool(_LATER.search(blob)) or any(part in blob for part in ("وقت ندارم", "سردم"))
    trust = any(part in blob for part in ("اعتماد", "کلاه", "مطمئن", "درست میگی"))
    agree = any(part in blob for part in ("باشه", "چشم", "اوکی", "میرم", "می‌رم", "باز کردم", "زدم ورود", "آره میام"))
    robot = any(part in blob for part in ("ربات", "ماشینی", "واقعی هستی", "آدمی", "آدم هستی", "ضبط شده"))
    # The opening itself says «هوش مصنوعی»: echoing it with a yes («آره بگید، هوش مصنوعی جالبه») is not the question.
    if "هوش مصنوعی" in blob and not any(part in blob for part in ("آره", "بله", "بگید", "بگو", "باشه", "بفرمایید", "جالبه")):
        robot = True
    has_site = any(part in blob for part in ("سایت دارم", "سایتم هست", "وبسایت دارم"))
    cant = any(part in blob for part in ("بلد نیست", "نمی‌دونم", "نمیدونم", "سخته", "سختِ"))
    time = any(part in blob for part in ("وقت ندار", "سرم شلوغ", "طول می‌کشه", "طول میکشه", "عجله دارم"))
    refuse = any(part in blob for part in ("نمیخوام", "نمی‌خوام", "لازم نیست", "ولش کن"))
    quick = bool(_QUICK.search(blob))
    dnc = any(part in blob for part in _DNC_WORDS)
    wrong = dnc or any(
        part in blob for part in ("مغازه ندار", "اشتباه گرفت", "فروشنده نیست", "فروشگاهی ندار", "اینستاگرام ندار")
    )
    return Signals(
        bye=wants_bye(blob),
        hello=is_hello(blob),
        howdy=howdy,
        price=price,
        later=later,
        trust=trust,
        agree=agree,
        robot=robot,
        has_site=has_site,
        cant=cant,
        time=time,
        trade=trade,
        refuse=refuse,
        source=source,
        wrong=wrong,
        quick=quick,
        dnc=dnc,
    )


def pain_kind(heard: str) -> str:
    blob = heard or ""
    if any(part in blob for part in ("دایرکت", "بی‌جواب", "بی جواب", "پیام مشتری")):
        return "dm"
    if any(part in blob for part in ("استوری", "کپشن", "محتوا", "عکس کالا", "پست")):
        return "content"
    if any(part in blob for part in ("سفارش", "موجودی", "انبار")):
        return "order"
    if any(part in blob for part in ("سایت دارم", "سایتم هست", "وبسایت دارم")):
        return ""
    if any(part in blob for part in ("سایت", "فروشگاه", "وبسایت", "وب‌سایت")):
        return "site"
    return ""


def feature_line(kind: str) -> str:
    return {
        "dm": DM_LINE,
        "content": CONTENT_LINE,
        "order": ORDER_LINE,
        "site": SITE_LINE,
    }.get(kind, "")


def cached_sales_lines() -> list[str]:
    lines = [
        HELLO_LINE,
        HELLO_SMS_LINE,
        PAIN_LINE,
        *FEATURE_LINES,
        BYE_LINE,
        CLOSE_LINE,
        ADDRESS_LINE,
        BUY_LINE,
        EXPLAIN,
        FALLBACK_LINE,
        MISHEARD_LINE,
        SALES_PROBE_LINE,
        WAIT_LINE,
        *WAIT_BRIGHT,
        ROBOT_LINE,
        ROBOT_AGAIN_LINE,
        QUICK_OPEN_LINE,
        QUICK_PITCH_LINE,
        BUSY_OPEN_LINE,
        BUSY_LINE,
        DECLINE_LINE,
        DNC_LINE,
        DNC_SHORT_LINE,
        PRICE_UNKNOWN_LINE,
        f"{FIRST_DISCLOSE} {PRICE_UNKNOWN_LINE}",
        f"{ROBOT_SHORT} {PRICE_UNKNOWN_LINE}",
    ]
    for heard in ("قیمت", "پرو مکس"):
        priced = price_spoken_line(heard)
        if priced:
            lines.extend((priced, f"{FIRST_DISCLOSE} {priced}", f"{ROBOT_SHORT} {priced}"))
    for signals, heard in (
        (Signals(trust=True), "اعتماد ندارم"),
        (Signals(cant=True), "بلد نیستم"),
        (Signals(has_site=True), "سایت دارم"),
        (Signals(source=True), "شماره من از کجا"),
        (Signals(), "تو واتساپ بفرست"),
    ):
        line = objection_line(signals, heard)
        if line:
            lines.append(line)
    gift = gift_line()
    if gift:
        lines.append(gift)
    return [line for line in dict.fromkeys(lines) if (line or "").strip()]


_PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")


def spoken_name(card: ShopCard | None) -> str:
    """A page name the TTS can say: Persian letters only, short; else empty."""
    name = re.sub(r"[^\u0600-\u06FF\u200c\s]|[؟؛،]", " ", (card.name if card else "") or "")
    name = re.sub(r"\s+", " ", name).strip()
    if not name or len(name.split()) > 4 or not _PERSIAN_RE.search(name):
        return ""
    return name


def hook_for(card: ShopCard | None) -> str:
    """One true, specific sentence from the page bio. Never invented: only facts enrich_campaign found."""
    if card is None:
        return HOOK_GENERIC
    page = f"پیج {spoken_name(card)} رو دیدم" if spoken_name(card) else "پیج اینستاگرامتون رو دیدم"
    signals = set(card.signals or ())
    if "dm_orders" in signals:
        return f"{page}؛ سفارش‌ها رو از دایرکت می‌گیرید."
    if "ships" in signals:
        return f"{page}؛ به همه‌جای ایران ارسال دارید."
    if "physical" in signals:
        return f"{page}؛ فروشگاه حضوری هم دارید."
    product = re.sub(r"[^\u0600-\u06FF\u200c\s]|[؟؛،]", " ", card.product or "").strip()
    if product and len(product.split()) <= 3:
        return f"{page}؛ {product} کار می‌کنید."
    return f"{page}."


def hello_for(card: ShopCard | None) -> str:
    """Opening: greeting, the personal hook, then the AI disclosure and a permission question."""
    if card is None:
        return HELLO_LINE
    if card.sms_sent and not (card.name or card.signals):
        return HELLO_SMS_LINE
    return f"{GREET_OPEN} {hook_for(card)} {DISCLOSE_LINE}"


def value_kind_for(card: ShopCard | None) -> str:
    """Features the value line already pitched (comma-separated), so the same pitch is never repeated.
    Every value line answers the DM «چطوری؟»; the ships line also pitches the store."""
    signals = set((card.signals if card else ()) or ())
    return "dm,site" if "ships" in signals else "dm"


def value_for(card: ShopCard | None) -> str:
    """After they say yes: the one benefit that fits what their page shows, then an open question."""
    signals = set((card.signals if card else ()) or ())
    if "dm_orders" in signals:
        return f"{DM_HOW}! الان روزی چندتا سفارش از دایرکت میاد؟"
    if "ships" in signals:
        return f"{DM_HOW}؛ از همین پیج فروشگاه هم می‌سازم. مشتری شهرهای دیگه الان چطوری سفارش می‌ده؟"
    if "has_site" in signals:
        return f"{DM_HOW}؛ کنار سایتتون هم می‌مونم، نه جاش. الان دایرکت‌ها رو کی جواب می‌ده؟"
    if "physical" in signals:
        return f"{DM_HOW}؛ یعنی وقتی تو مغازه‌اید، پیج منتظر نمی‌مونه! الان دایرکت‌ها رو کی جواب می‌ده؟"
    return VALUE_GENERIC


def wants_address(heard: str) -> bool:
    blob = heard or ""
    if any(part in blob for part in ("بلد نیست", "اعتماد", "سایت دارم", "ربات", "فرقش", "فرق ")):
        return False
    return any(part in blob for part in _ADDRESS_HINTS)


def turn_objection(signals: Signals) -> str:
    """The objection raised in this very turn, for the model's note; an old one must not steer later turns."""
    if signals.refuse:
        return "refuse"
    for name in ("price", "later", "time", "trust", "cant", "source", "has_site"):
        if getattr(signals, name):
            return name
    return ""


def robot_line(state: SalesState) -> str:
    """Honest yes-AI every time, never the same sentence twice; the permission question only before the pitch."""
    if state.robot_answers == 0 and state.awaiting_permission:
        return ROBOT_LINE
    if ROBOT_AGAIN_LINE not in state.said:
        return ROBOT_AGAIN_LINE
    return ""


def objection_line(signals: Signals, heard: str) -> str | None:
    """Acknowledge, reframe, hand the turn back. The address comes when they lean in, not on every objection."""
    blob = heard or ""
    if "واتس" in blob:
        return "تو تماس لینک نمی‌فرستم، ولی آدرسش راحته: سوزان کُر دات آی‌آر، دکمهٔ ورود."
    if signals.trust:
        return "حق دارید، منم بودم همینو می‌پرسیدم. برای همین شروعش رایگانه که اول خودتون امتحانش کنید."
    if signals.cant:
        return "اصلاً لازم نیست بلد باشید؛ فقط اسم پیجتون رو می‌زنید، بقیه‌ش با سوزانه."
    if signals.has_site:
        return "چه خوب! سوزان جای سایتتون نمیاد؛ دایرکت و محتوای پیج رو جلو می‌بره، محصولات رو هم از خود پیج برمی‌داره."
    if signals.source:
        return SOURCE_LINE
    return None


def gift_allowed(state: SalesState, signals: Signals) -> bool:
    if state.gifted:
        return False
    if not os.environ.get("GIFT_CODE_SPOKEN", "").strip():
        return False
    if state.stage not in {"cta", "confirm", "close", "pitch"}:
        return False
    if signals.price or signals.later or state.objection in {"price", "later"} or state.refused_cta:
        return True
    return False


def plan_turn(state: SalesState, heard: str) -> TurnPlan:
    signals = read_signals(heard)
    state.last_cue = heard or ""
    state.turn_objection = turn_objection(signals)
    if signals.trade:
        state.trade = signals.trade
    if signals.has_site:
        state.has_site = True
        state.objection = state.objection or "has_site"
    if signals.price:
        state.objection = "price"
        if state.stage in {"greet", "discover", "pitch"}:
            state.stage = "cta"
    if signals.later:
        state.objection = "later"
        if state.stage in {"greet", "discover", "pitch"}:
            state.stage = "cta"
    if signals.time:
        state.objection = state.objection or "time"
    if signals.trust:
        state.objection = state.objection or "trust"
    if signals.cant:
        state.objection = state.objection or "cant"
    if signals.source:
        state.objection = state.objection or "source"
    if signals.refuse and state.linked:
        state.refused_cta = True
    carrier = is_carrier_text(heard)
    if not state.greeted:
        if signals.wrong:
            return TurnPlan(kind="close", line=DNC_LINE if signals.dnc else BYE_LINE, hangup=True, signals=signals, dnc=True)
        if signals.bye:
            return TurnPlan(kind="close", line=CLOSE_LINE, hangup=True, signals=signals)
        busy_first = (signals.time or signals.later) and not carrier
        if not (signals.hello or signals.howdy or signals.quick or busy_first or person_started(heard)):
            return TurnPlan(kind="hold", signals=signals)
        state.greeted = True
        state.stage = "discover"
        if signals.price:
            state.intro_said = True
            priced = price_spoken_line(heard)
            if priced:
                state.stage = "cta"
                return TurnPlan(kind="address", line=f"{FIRST_DISCLOSE} {priced}", signals=signals)
            return TurnPlan(kind="address", line=f"{FIRST_DISCLOSE} {PRICE_UNKNOWN_LINE}", signals=signals)
        if signals.quick and not signals.later:
            # The short version still names the AI and ends with the address.
            state.intro_said = True
            state.pain_asked = True
            state.stage = "cta"
            return TurnPlan(kind="feature", line=QUICK_OPEN_LINE, signals=signals)
        if busy_first:
            return TurnPlan(kind="close", line=BUSY_OPEN_LINE, hangup=True, signals=signals)
        state.awaiting_permission = True
        state.intro_said = True
        opening = state.opening or (HELLO_SMS_LINE if state.sms_sent else HELLO_LINE)
        return TurnPlan(kind="hello", line=opening, signals=signals)
    if signals.wrong:
        # "Don't call me" is promised back in words; a wrong number just gets a goodbye. Both go to the DNC file.
        return TurnPlan(kind="close", line=DNC_LINE if signals.dnc else BYE_LINE, hangup=True, signals=signals, dnc=True)
    if signals.refuse and SOURCE_LINE in state.said:
        # We just said "if you don't want it, we won't call again": hold to it.
        return TurnPlan(kind="close", line=DNC_LINE, hangup=True, signals=signals, dnc=True)
    if signals.bye:
        line = BYE_LINE if (state.refused_cta or not state.linked or signals.refuse) else CLOSE_LINE
        return TurnPlan(kind="close", line=line, hangup=True, signals=signals)
    if len((heard or "").strip()) < 4:
        return TurnPlan(kind="fallback", line=MISHEARD_LINE, signals=signals)
    if signals.robot and not (signals.price or signals.refuse):
        robot = robot_line(state)
        if robot:
            state.robot_answers += 1
            if not state.awaiting_permission:
                state.stage = "confirm"
            return TurnPlan(kind="feature", line=robot, signals=signals)
        # Both fixed answers are spent: the model answers in fresh words (its prompt keeps it honest).
        state.awaiting_permission = False
        return TurnPlan(kind="model", cue=state.cue(heard), signals=signals)
    if (
        signals.quick
        and not (state.linked or signals.refuse or signals.price or signals.later)
        and not wants_address(heard)
        and objection_line(signals, heard) is None
    ):
        state.awaiting_permission = False
        state.intro_said = True
        state.pain_asked = True
        state.stage = "cta"
        return TurnPlan(kind="address", line=QUICK_PITCH_LINE, signals=signals)
    if state.awaiting_permission:
        if signals.refuse:
            state.awaiting_permission = False
            return TurnPlan(kind="close", line=DECLINE_LINE, hangup=True, signals=signals)
        if (signals.later or signals.time) and not signals.price:
            state.awaiting_permission = False
            return TurnPlan(kind="close", line=BUSY_LINE, hangup=True, signals=signals)
        if not signals.price and objection_line(signals, heard) is None and not wants_address(heard):
            state.awaiting_permission = False
            kind = pain_kind(heard)
            line = feature_line(kind) or state.value_line or VALUE_GENERIC
            state.pitched.update([kind] if kind else state.value_kind.split(","))
            state.intro_said = True
            state.pain_asked = True
            state.stage = "pitch" if kind else "discover"
            return TurnPlan(kind="feature", line=line, signals=signals)
        state.awaiting_permission = False
    if signals.price:
        priced = price_spoken_line(heard) or PRICE_UNKNOWN_LINE
        state.stage = "cta"
        if signals.robot:
            # «رباتی؟ چنده؟»: the AI answer is never skipped for the price.
            state.robot_answers += 1
            priced = f"{ROBOT_SHORT} {priced}"
        return TurnPlan(kind="address", line=priced, signals=signals)
    fixed = objection_line(signals, heard)
    if fixed:
        state.stage = "confirm"
        return TurnPlan(kind="address", line=fixed, signals=signals)
    if signals.agree and (state.linked or state.cta_count > 0):
        state.agreed = True
        state.stage = "close"
        return TurnPlan(kind="close", line=CLOSE_LINE, hangup=True, signals=signals)
    if wants_address(heard):
        if signals.trust or signals.cant or signals.has_site or signals.robot:
            state.stage = "confirm"
        else:
            state.stage = "cta"
            return TurnPlan(kind="address", line=ADDRESS_LINE, signals=signals)
    kind = pain_kind(heard)
    line = feature_line(kind) if kind not in state.pitched else ""
    if line:
        state.pitched.add(kind)
        state.intro_said = True
        state.pain_asked = True
        state.stage = "pitch"
        return TurnPlan(kind="feature", line=line, signals=signals)
    if not state.intro_said:
        state.intro_said = True
        state.stage = "discover"
        return TurnPlan(kind="hello", line=HELLO_LINE, signals=signals)
    if not state.pain_asked:
        state.pain_asked = True
        return TurnPlan(kind="feature", line=PAIN_LINE, signals=signals)
    return TurnPlan(
        kind="model",
        cue=state.cue(heard),
        allow_gift=gift_allowed(state, signals),
        signals=signals,
    )


def note_spoken(state: SalesState, spoken: str) -> None:
    text = spoken or ""
    if not text:
        return
    state.turns += 1
    state.said.append(text)
    if mentions_address(text):
        state.linked = True
        state.cta_count += 1
        if state.stage in {"greet", "discover", "pitch"}:
            state.stage = "cta"
        elif state.stage == "cta":
            state.stage = "confirm"
    if state.turns >= 1 and state.stage == "discover":
        state.stage = "pitch"


# Tools the model calls by writing a tag; the gateway speaks the exact line, so prices and the address are never improvised.
_TAGS = {
    "هدیه": "gift",
    "هديه": "gift",
    "پایان": "end",
    "پايان": "end",
    "قیمت": "price",
    "آدرس": "address",
    "زنگ‌نزن": "dnc",
    "زنگ نزن": "dnc",
    "زنگنزن": "dnc",
}
_TAG_RE = re.compile(r"\[\s*(" + "|".join(re.escape(name) for name in _TAGS) + r")\s*\]")


_STRAY_TAG = re.compile(r"\[[^\]\n]{0,24}\]")


def extract_tags(raw: str) -> tuple[str, set[str]]:
    text = (raw or "").replace("ي", "ی").replace("ك", "ک")
    tags = {_TAGS[match.group(1)] for match in _TAG_RE.finditer(text)}
    # An unknown or misspelled tag is still a tag: never read brackets aloud.
    text = _STRAY_TAG.sub(" ", _TAG_RE.sub(" ", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text, tags


def mentions_address(text: str) -> bool:
    """The domain itself was spoken; «دکمهٔ ورود» alone does not tell them where to go."""
    blob = text or ""
    return any(part in blob for part in ("sozan-core", "سوزان کور", "سوزان کُر", "کُر، دات", "کُر دات"))


def tool_followups(tags: set[str], state: SalesState, heard: str, spoken: str) -> tuple[list[str], bool, bool]:
    """Lines the gateway adds for the model's tool tags: (lines, hang up, do-not-call)."""
    if "dnc" in tags:
        sorry = any(part in (spoken or "") for part in ("ببخشید", "مزاحم", "عذر"))
        return [DNC_SHORT_LINE if sorry else DNC_LINE], True, True
    lines: list[str] = []
    _digits, phrases = _money_forms(plan_catalog()) if "price" in tags else (set(), [])
    if "price" in tags and not any(phrase in (spoken or "") for phrase in phrases):
        lines.append(price_spoken_line(heard if read_signals(heard).price else "قیمت") or PRICE_UNKNOWN_LINE)
    if "address" in tags and not mentions_address(spoken) and not any(mentions_address(line) for line in lines):
        lines.append(ADDRESS_LINE)
    return lines, False, False


def split_sentences(text: str) -> list[str]:
    blob = re.sub(r"\s+", " ", text or "").strip()
    if not blob:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[.!?؟])\s+", blob) if part.strip()]
    out: list[str] = []
    for part in parts:
        out.extend(_split_comma(part))
    return [item for item in out if item]


def _split_comma(part: str) -> list[str]:
    if "،" not in part and "," not in part:
        return [part]
    chunks = re.split(r"[،,]\s*", part)
    if len(chunks) <= 1:
        return [part]
    kept: list[str] = []
    buf = ""
    for chunk in chunks:
        buf = f"{buf}، {chunk}".strip(" ،") if buf else chunk
        if len(buf.split()) >= 16:
            kept.append(buf)
            buf = ""
    if buf:
        if kept:
            kept[-1] = f"{kept[-1]}، {buf}".strip(" ،")
        else:
            kept.append(buf)
    return kept


_DOMAIN_DOT = re.compile(r"(?<=[A-Za-z0-9])\.(?=[A-Za-z])")


def take_ready_sentences(buf: str) -> tuple[list[str], str]:
    blob = _DOMAIN_DOT.sub("\u0001", buf or "")
    ready: list[str] = []
    while True:
        match = re.search(r"[.!?؟]", blob)
        comma = None
        words = blob.replace("،", " ").replace(",", " ").split()
        if ("," in blob or "،" in blob) and len(words) >= 16:
            comma = re.search(r"[،,]", blob)
        cut = None
        if match:
            cut = match.end()
        if comma and (cut is None or comma.end() < cut) and len(blob[: comma.end()].split()) >= 16:
            cut = comma.end()
        if cut is None:
            break
        piece = blob[:cut].strip().replace("\u0001", ".")
        blob = blob[cut:].lstrip()
        if piece:
            ready.append(piece)
    return ready, blob.replace("\u0001", ".")


def too_alike(left: str, right: str) -> bool:
    a = _words(left)
    b = _words(right)
    if not a or not b:
        return False
    if left.strip() == right.strip():
        return True
    if left.strip() in right.strip() or right.strip() in left.strip():
        if min(len(a), len(b)) >= 4:
            return True
    inter = len(set(a) & set(b))
    return inter / max(len(set(a)), len(set(b))) >= 0.85


def _words(text: str) -> list[str]:
    blob = re.sub(r"[^\u0600-\u06FFA-Za-z0-9]+", " ", text or "")
    return [word for word in blob.split() if word]


_YOU_PATTERNS = (
    (re.compile(r"پیجت(?!ون)"), "پیجتون"),
    (re.compile(r"سایتت(?!ون)"), "سایتتون"),
    (re.compile(r"سالنت(?!ون)"), "سالنتون"),
    (re.compile(r"خودت(?!ون)"), "خودتون"),
    (re.compile(r"برات(?!ون)"), "براتون"),
    (re.compile(r"می(?:‌)?ری(?!د)"), "می‌رید"),
    (re.compile(r"می(?:‌)?زنی(?!د)"), "می‌زنید"),
    (re.compile(r"می(?:‌)?نویسی(?!د)"), "می‌نویسید"),
    (re.compile(r"می(?:‌)?بینی(?!د)"), "می‌بینید"),
    (re.compile(r"(^|[^\u0600-\u06FFa-zA-Z])برو(?!ید|ن)"), r"\1برید"),
    (re.compile(r"(^|[^\u0600-\u06FFa-zA-Z])بزن(?!ید|ن)"), r"\1بزنید"),
    (re.compile(r"(^|[^\u0600-\u06FFa-zA-Z])بگو(?!ید|ن)"), r"\1بگید"),
    (re.compile(r"نباش(?!ید)"), "نباشید"),
    (re.compile(r"دستته"), "دستتونه"),
    (re.compile(r"می‌ذاری(?!د)"), "می‌ذارید"),
    (re.compile(r"(?<!ن)میذاری(?!د)"), "می‌ذارید"),
)


def formalize_you(text: str) -> str:
    blob = text or ""
    for pattern, repl in _YOU_PATTERNS:
        blob = pattern.sub(repl, blob)
    return blob


def strip_invented_names(reply: str, heard: str) -> str:
    spoken = heard or ""
    cleaned = reply or ""
    for match in _FAKE_NAME.finditer(cleaned):
        name = match.group(1)
        if name not in spoken:
            cleaned = cleaned.replace(name, "")
    return re.sub(r"\s+", " ", cleaned).strip(" ،,")


_TOMAN = re.compile(r"توم[اآ]?ن")


def _price_sentence_ok(sent: str) -> bool:
    has_toman = bool(_TOMAN.search(sent))
    long_nums = []
    for num in _PRICE_NUM.findall(sent):
        latin = num.translate(_LATIN_DIGITS)
        if len(latin) >= 4:
            long_nums.append(latin)
    if not has_toman and not long_nums:
        return True
    digits, phrases = _money_forms(plan_catalog())
    allowed = {item.translate(_LATIN_DIGITS) for item in digits}
    if not allowed:
        return False
    if any(latin not in allowed for latin in long_nums):
        return False
    if not has_toman:
        return True
    scrubbed = sent
    for phrase in phrases:
        scrubbed = scrubbed.replace(phrase, " ")
    for token in digits:
        scrubbed = scrubbed.replace(token, " ")
    scrubbed = _TOMAN.sub(" ", scrubbed)
    return re.search(r"میلیون|هزار|[0-9۰-۹٠-٩]{3,}", scrubbed) is None


def guard_reply(reply: str, heard: str) -> str:
    text = formalize_you(strip_invented_names(reply or "", heard or ""))
    kept: list[str] = []
    allowed_code = gift_spoken_code()
    for sent in split_sentences(text) or ([text] if text else []):
        if any(mark in sent for mark in PITCH_MARKS):
            continue
        if any(part in sent for part in _BAN_CLAIM):
            continue
        if "رزرو" in sent or "نوبت‌دهی" in sent or "نوبت دهی" in sent:
            continue
        if any(part in sent for part in ("شماره بده", "رمز", "کارت", "کد پیامک", "otp")):
            continue
        if "تخفیف" in sent and any(part in sent for part in ("نیست", "نمی‌تونم", "نمیتونم", "نمی‌توانم")):
            continue
        if re.search(r"کد\s+\S+", sent) and (not allowed_code or allowed_code not in sent):
            continue
        if not _price_sentence_ok(sent):
            continue
        kept.append(sent.strip())
    return shorten_reply(" ".join(kept).strip())


def sentence_done(text: str) -> bool:
    return bool(re.search(r"[.!?؟]$", (text or "").strip()))


def stream_tail(buf: str) -> str:
    """Only a finished sentence may be spoken after the token stream stops."""
    tail = (buf or "").strip()
    if tail and sentence_done(tail):
        return tail
    return ""


def shorten_reply(text: str, limit: int = 18) -> str:
    blob = re.sub(r"\s+", " ", text or "").strip()
    if not blob:
        return ""
    parts = split_sentences(blob) or [blob]
    kept: list[str] = []
    count = 0
    for part in parts:
        words = part.split()
        if not words:
            continue
        # Never cut a sentence in the middle and invent a period.
        if not sentence_done(part):
            if len(words) > 8:
                break
        elif not count and len(words) > 28:
            break
        elif count and count + len(words) > limit:
            break
        kept.append(part)
        count += len(words)
        if count >= 12 and sentence_done(part):
            break
    return " ".join(kept).strip()


REPEAT_FREE = frozenset({ADDRESS_LINE})


def drop_repeats(spoken: str, said: list[str]) -> str:
    kept: list[str] = []
    for sent in split_sentences(spoken) or ([spoken] if spoken else []):
        if sent not in REPEAT_FREE and any(too_alike(sent, prev) for prev in said + kept):
            continue
        kept.append(sent)
    return " ".join(kept[:2]).strip()


def finish_spoken(raw: str, state: SalesState, heard: str) -> tuple[str, set[str]]:
    text, tags = extract_tags(raw)
    text = guard_reply(text, heard)
    text = drop_repeats(text, state.said)
    return text, tags


def sales_kind(heard: str) -> str:
    """Narrow signal for tests and logs. The live call uses read_signals."""
    signals = read_signals(heard)
    blob = heard or ""
    if not blob.strip() or blob.strip() == "شروع تماس":
        return "open"
    if signals.bye:
        return "bye"
    if signals.howdy:
        return "howdy"
    if any(part in blob for part in ("کجا", "وارد", "پنل", "کدوم", "شروع", "بفرست")):
        return "where"
    if any(part in blob for part in ("پیجمو", "پیجم", "اسم پیج", "پیدامو", "پیج را")):
        return "page"
    if "آنلاین" in blob or "انلاین" in blob:
        return "shop"
    if any(part in blob for part in ("اسمت", "اسم چیه", "اسمت چیه")) and "سوزان" not in blob:
        return "name"
    if any(part in blob for part in ("پرو", "تومان")):
        return "price"
    if any(part in blob for part in ("عکس", "فیلم", "ویدیو", "استودیو", "پست", "پوستر")):
        return "studio"
    if any(part in blob for part in ("کارایی دیگه", "کارهای دیگه", "چه کار دیگه", "دیگه چی")):
        return "more"
    if any(part in blob for part in ("شغل", "مشاغل", "برای چه کار", "به درد")):
        return "who"
    if signals.price:
        return "cost"
    if any(part in blob for part in ("چجوری", "چگونه", "کار کن", "کی هستی", "سایت دار")):
        return "how"
    if any(part in blob for part in ("سوزان چیست", "سوزان چیه", "سوزن چیه", "کارت چیه", "چه کار", "چه کاری")):
        return "what"
    if signals.hello:
        return "hello"
    return "other"


def sales_ended(heard: str, spoken: str) -> bool:
    return read_signals(heard).bye or wants_bye(spoken) or spoken.strip() == CLOSE_LINE


def utterance_open(heard: str) -> bool:
    return False


@dataclass(frozen=True)
class ShopCard:
    instagram: str
    product: str
    sms_sent: bool = False
    # From enrich_campaign.py (the page bio, read before the campaign). Empty when not enriched.
    name: str = ""
    city: str = ""
    signals: tuple[str, ...] = ()
    bio: str = ""


PROFILE_SIGNALS = frozenset({"dm_orders", "ships", "physical", "has_site", "wholesale", "handmade", "whatsapp_orders"})

DNC_PATH = Path.home() / "local-ai" / "config" / "sozan-dnc.txt"
CAMPAIGN_PATH = Path.home() / "local-ai" / "config" / "sozan-campaign.json"


def remember_dnc(number: str) -> None:
    digits = normalize_dial(number)
    if not digits:
        return
    DNC_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if DNC_PATH.is_file():
        existing = {normalize_dial(line) for line in DNC_PATH.read_text(encoding="utf-8").splitlines()}
    if digits in existing:
        return
    with DNC_PATH.open("a", encoding="utf-8") as fh:
        fh.write(digits + "\n")


def load_campaign(path: Path) -> dict[str, ShopCard]:
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    targets = raw.get("targets", raw.get("contacts", raw if isinstance(raw, list) else []))
    found: dict[str, ShopCard] = {}
    for row in targets:
        phone = normalize_dial(str(row.get("phone", "")))
        handle = str(row.get("instagram", "")).strip().lstrip("@")
        product = str(row.get("product", "")).strip()
        sms_sent = bool(row.get("smsSent"))
        profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        if not profile.get("ok"):
            profile = {}
        if phone and handle:
            found[phone] = ShopCard(
                instagram=handle,
                product=product or str(profile.get("product") or "").strip(),
                sms_sent=sms_sent,
                name=str(profile.get("name") or "").strip()[:60],
                city=str(profile.get("city") or "").strip()[:30],
                signals=tuple(str(item) for item in (profile.get("signals") or []) if str(item) in PROFILE_SIGNALS),
                bio=str(profile.get("bio") or "").strip()[:240],
            )
    return found
