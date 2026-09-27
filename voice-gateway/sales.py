"""Facts and turn state for one live sales call. The model chooses most of the words."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from brain import is_hello, wants_bye
from sip import normalize_dial

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
HELLO_LINE = (
    "سلام، وقتتون بخیر! سوزانم. "
    "برای پیج اینستا رایگان وبسایت می‌سازیم. پیجتون چی می‌فروشه؟"
)
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
)
_PRICE_NUM = re.compile(r"[0-9۰-۹٠-٩]{3,}")
_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_MONEY_KEYS = ("listPrice", "price", "priceToman", "codePrice", "phonePrice")
_PLANS_URL = "https://api.sozan-core.ir/billing/plans"
_PLANS_TTL_S = 600
_ONES = ("", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه")
_TEENS = ("ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده")
_TENS = ("", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود")
_HUNDREDS = ("", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد")
_plans_cache: dict | None = None
_plans_cached_at = 0.0
_plans_fetcher = None
_STAGE_FA = {
    "greet": "سلام",
    "discover": "کشف",
    "pitch": "ارزش",
    "cta": "دعوت",
    "confirm": "تأیید",
    "close": "بستن",
}
_STAGE_DO = {
    "greet": "فقط سلام گرم بگو و بپرس پیجتون چی می‌فروشه.",
    "discover": "فقط بپرس پیجتون چی می‌فروشه. آدرس سایت نگو.",
    "pitch": "یک فایدهٔ مخصوص همان کسب‌وکار بگو. دعوت سایت نکن مگر بپرسد.",
    "cta": "آدرس sozan-core.ir، دکمهٔ ورود و رایگان بودن را فقط یک بار بگو.",
    "confirm": "آدرس را تکرار نکن مگر بپرسد. نگرانی‌اش را جواب بده.",
    "close": "تشکر گرم و خداحافظی.",
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
    global _plans_cache, _plans_cached_at, _plans_fetcher
    _plans_cache = None
    _plans_cached_at = 0.0
    _plans_fetcher = None


def set_plans_fetcher(fn) -> None:
    global _plans_fetcher, _plans_cache, _plans_cached_at
    _plans_fetcher = fn
    _plans_cache = None
    _plans_cached_at = 0.0


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
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict) or not isinstance(loaded.get("plans"), list):
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
        "تو سوزان هستی، زن، گرم، پرانرژی، کاملاً خودمونی با خطاب «شما». "
        "زنگ زدی خود سوزان را معرفی کنی.\n"
        "سوزان دقیقاً برای آنلاین‌شاپ اینستاگرام ساخته شده. "
        "وبسایت فروشگاه را از کپشن پیج می‌سازد. ساختنش رایگان است. "
        "استودیو از روی عکس پست و فیلم هم می‌سازد، ولی اصل کار آنلاین‌شاپ است.\n"
        "رایگان یعنی یک وب‌سایت، انبار، و چت دستی. نگو سایت همان لحظه حاضر است. بگو رایگان شروع می‌کنید.\n"
        "رزرو و نوبت‌دهی نداریم. نگو مشتری از سایت رزرو می‌کند.\n"
        "نگو درگاه پرداخت روشن است. نگو وب‌سایت نامحدود. لینک را در واتساپ و دایرکت و پیامک نفرست.\n"
        "هر نوبت یک جمله، حداکثر هجده کلمه. "
        "اول همان سؤال را جواب بده، بعد فقط یک قدم جلوتر برو، هر بار فقط یک سؤال.\n"
        "خطاب تو ممنوع: نگو پیجت، سایتت، برو، بزن، می‌ری، می‌زنی، خودت. "
        "بگو پیجتون، سایتتون، برید، بزنید، می‌رید، می‌زنید، خودتون.\n"
        "بگو می‌سازه، رو، برید، بزنید. رسمی حرف نزن. جمله را وسطش رها نکن.\n"
        "برای شور از ! و برای سؤال از ؟ استفاده کن. سه‌نقطه نگذار.\n"
        "نوبت سوم حتماً sozan-core.ir و دکمهٔ ورود و رایگان بودن را بگو اگر هنوز نگفتی. "
        "اگر قبلاً گفتی تکرار نکن مگر بپرسند آدرس کجاست.\n"
        "اگر گفت بلد نیستم، بگو لازم نیست بلد باشید، فقط اسم پیج را در سایت می‌نویسید.\n"
        "اگر گفت اعتماد ندارم، بگو خودتان سایت را باز کنید و ببینید، رایگان است.\n"
        "اگر گفت سایت دارم، بگو فرق این است که محصولات از خود پیج اینستا می‌آید.\n"
        "اگر گفت رباتی، راست بگو دستیار صوتی سوزانی و بعد کار را بگو.\n"
        "لینک را توی این تماس نخواه. نگو همین‌جا بنویسد. نگو این تماس خود پنل است. "
        "عکس و اسم پیج را پشت تلفن نخواه. اسم طرف را نساز. دروغ نگو. شماره و رمز و کارت نخواه. "
        "واتساپ و دایرکت و پیامک نفرست؛ بگو تو تماس لینک نمی‌فرستم، خودتان سایت را باز کنید.\n"
        "نگو مشتری‌ها باید شماره بدهند.\n"
        "اگر پرسید شماره را از کجا آوردی، راست بگو: از بین پیج‌های فروشگاهی اینستاگرام زنگ می‌زنم، جزئیات لیست را نمی‌گویم. "
        "اگر دوباره همان را پرسید، همان جواب را بده و بعد آدرس سایت را بگو.\n"
        "اگر گفت مغازه ندارم، اشتباه گرفتید، شرکت است، دانشجو است، اینستاگرام ندارد، یا زنگ نزنید، عذرخواهی کن و فقط خداحافظی کن. سایت را پیشنهاد نکن.\n"
        + price_clause()
        + "اگر مستقیم پرسید رباتی، راست بگو: دستیار صوتی سوزانم.\n"
        "وقتی کار تمام است فقط بنویس [پایان]. وقتی هدیه مناسب است فقط بنویس [هدیه]. "
        "کد تخفیف را خودت نساز.\n"
        "نمونه‌های زیر فقط لحن‌اند، از بر تکرارشان نکن:\n"
        "مشتری: من آرایشگاه دارم. → سوزان واسه پیج اینستاگرام شماست. از کپشن پیج، سایت محصولات رو می‌سازه.\n"
        "مشتری: پیجمو چجوری بدم؟ → تو تماس نمی‌خواد. برید sozan-core.ir، ورود رو بزنید، اونجا اسم پیج رو می‌نویسید.\n"
        "مشتری: گرونه. → ساخت وبسایت کلاً رایگانه؛ پول فقط برای پرو، اونم اگه بخواید.\n"
        "مشتری: بعداً. → باشه. یادتون باشه sozan-core.ir، دکمه ورود. [هدیه]\n"
        "مشتری: رباتی؟ → دستیار صوتی سوزانم. خود سایت رو که باز کنید دست خودتونه.\n"
        "مشتری: لینکو بفرست. → تو تماس لینک نمی‌فرستم. خودتون sozan-core.ir رو باز کنید و ورود رو بزنید.\n"
        "مشتری: تو واتساپ بفرست. → تو تماس لینک نمی‌فرستم. خودتون sozan-core.ir رو باز کنید و ورود رو بزنید.\n"
        "مشتری: سایت دارم. → سوزان مخصوص پیج اینستاست؛ محصولات رو خودش از پیجتون می‌آره.\n"
        "مشتری: بلد نیستم. → لازم نیست بلد باشید، فقط اسم پیجتون رو تو سایت می‌زنید.\n"
        "اعتراض‌ها: نگرانی را قبول کن، یک زاویهٔ تازه بگو، دعوت کوچک بکن. فوریت ساختگی نگو."
    )


def sales_brief(card: ShopCard) -> str:
    product = card.product or "کالا"
    return sales_open() + (
        f"\nفقط بدان با که حرف می‌زنی: پیج {card.instagram}، فروش {product}. این را تعریف نکن."
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
    last_cue: str = ""
    said: list[str] = field(default_factory=list)
    interrupted: str = ""
    refused_cta: bool = False

    def stage_fa(self) -> str:
        return _STAGE_FA.get(self.stage, self.stage)

    def note(self) -> str:
        job = _STAGE_DO.get(self.stage, "")
        if self.linked and self.stage in {"cta", "confirm", "pitch"}:
            job = "آدرس را تکرار نکن مگر بپرسد. " + job
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


@dataclass(frozen=True)
class TurnPlan:
    kind: str
    line: str | None = None
    cue: str = ""
    hangup: bool = False
    allow_gift: bool = False
    signals: Signals = field(default_factory=Signals)


def person_started(heard: str) -> bool:
    blob = heard or ""
    return any(part in blob for part in _START_WORDS)


def read_signals(heard: str) -> Signals:
    blob = re.sub(r"[^\u0600-\u06FFA-Za-z\s]", " ", heard or "")
    blob = re.sub(r"\s+", " ", blob).strip()
    trade = next((item for item in _TRADES if item in blob), "")
    howdy = any(
        part in blob
        for part in ("حالت چطور", "حالت خوب", "حالتت", "چطوری", "خوبی", "خوبید", "چه خبر")
    )
    if "چطور" in blob and not any(part in blob for part in ("بساز", "سایت", "وبسایت", "وب سایت")):
        howdy = True
    source = any(part in blob for part in ("شماره من", "از کجا آورد", "از کجا شماره"))
    price = any(part in blob for part in ("گرون", "گران", "هزینه", "قیمت", "پول", "مبلغ", "پرو", "تخفیف", "تومان"))
    if "پول" in blob and any(part in blob for part in ("نه", "نمی", "نمی‌")) and "گرون" not in blob:
        price = False
    later = any(part in blob for part in ("بعدا", "بعداً", "الان نه", "وقت ندارم", "سردم"))
    trust = any(part in blob for part in ("اعتماد", "کلاه", "مطمئن", "درست میگی"))
    agree = any(part in blob for part in ("باشه", "چشم", "اوکی", "میرم", "می‌رم", "باز کردم", "زدم ورود", "آره میام"))
    robot = any(part in blob for part in ("ربات", "هوش مصنوعی", "ماشینی", "واقعی هستی"))
    has_site = any(part in blob for part in ("سایت دارم", "سایتم هست", "وبسایت دارم"))
    cant = any(part in blob for part in ("بلد نیست", "نمی‌دونم", "نمیدونم", "سخت"))
    time = any(part in blob for part in ("وقت ندار", "سرم شلوغ", "طول می‌کشه", "طول میکشه"))
    refuse = any(part in blob for part in ("نمیخوام", "نمی‌خوام", "لازم نیست", "ولش کن"))
    wrong = any(
        part in blob
        for part in ("مغازه ندار", "اشتباه گرفت", "فروشنده نیست", "فروشگاهی ندار", "اینستاگرام ندار", "زنگ نزن")
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
    )


def wants_address(heard: str) -> bool:
    blob = heard or ""
    if any(part in blob for part in ("بلد نیست", "اعتماد", "سایت دارم", "ربات", "فرقش", "فرق ")):
        return False
    return any(part in blob for part in _ADDRESS_HINTS)


def objection_line(signals: Signals, heard: str) -> str | None:
    tail = "برید sozan-core.ir، دکمهٔ ورود رو بزنید، رایگانه."
    blob = heard or ""
    if "واتس" in blob:
        return f"تو تماس لینک نمی‌فرستم. خودتون {tail}"
    if signals.trust:
        return f"حق دارید. خودتون سایت رو باز کنید و ببینید. {tail}"
    if signals.cant:
        return f"لازم نیست بلد باشید. فقط اسم پیجتون رو تو سایت می‌نویسید. {tail}"
    if signals.has_site:
        return f"فرق سوزان اینه که محصولات از خود پیج اینستاگرام می‌آد. {tail}"
    if signals.robot:
        return "دستیار صوتی سوزانم. " + tail
    if signals.source:
        return f"از بین پیج‌های فروشگاهی اینستاگرام زنگ می‌زنم. {tail}"
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
    if not state.greeted:
        if signals.wrong:
            return TurnPlan(kind="close", line=BYE_LINE, hangup=True, signals=signals)
        if signals.bye:
            return TurnPlan(kind="close", line=CLOSE_LINE, hangup=True, signals=signals)
        if not (signals.hello or signals.howdy or person_started(heard)):
            return TurnPlan(kind="hold", signals=signals)
        state.greeted = True
        state.stage = "discover"
        if signals.price:
            priced = price_spoken_line(heard)
            if priced:
                state.stage = "cta"
                return TurnPlan(kind="address", line=priced, signals=signals)
            return TurnPlan(kind="address", line=ADDRESS_LINE, signals=signals)
        return TurnPlan(kind="hello", line=HELLO_LINE, signals=signals)
    if signals.bye:
        line = BYE_LINE if (state.refused_cta or not state.linked) else CLOSE_LINE
        return TurnPlan(kind="close", line=line, hangup=True, signals=signals)
    if len((heard or "").strip()) < 4:
        return TurnPlan(kind="fallback", line=MISHEARD_LINE, signals=signals)
    if signals.wrong:
        return TurnPlan(kind="close", line=BYE_LINE, hangup=True, signals=signals)
    if signals.price:
        priced = price_spoken_line(heard)
        state.stage = "cta"
        if priced:
            return TurnPlan(kind="address", line=priced, signals=signals)
        return TurnPlan(kind="address", line=ADDRESS_LINE, signals=signals)
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
    if state.turns >= 2 and not state.linked:
        state.stage = "cta"
        blocked = (
            signals.price
            or signals.later
            or signals.trust
            or signals.cant
            or signals.has_site
            or signals.robot
            or signals.source
        )
        if not blocked:
            return TurnPlan(kind="address", line=ADDRESS_LINE, signals=signals)
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
    if any(part in text for part in ("sozan-core", "سوزان کور", "سوزان کُر", "ورود")):
        state.linked = True
        state.cta_count += 1
        if state.stage in {"greet", "discover", "pitch"}:
            state.stage = "cta"
        elif state.stage == "cta":
            state.stage = "confirm"
    if state.turns >= 1 and state.stage == "discover":
        state.stage = "pitch"


def extract_tags(raw: str) -> tuple[str, set[str]]:
    text = raw or ""
    tags: set[str] = set()
    if "[هدیه]" in text or "[هديه]" in text:
        tags.add("gift")
    if "[پایان]" in text or "[پايان]" in text:
        tags.add("end")
    text = text.replace("[هدیه]", " ").replace("[هديه]", " ")
    text = text.replace("[پایان]", " ").replace("[پايان]", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text, tags


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


def _price_sentence_ok(sent: str) -> bool:
    has_toman = "تومان" in sent
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
    scrubbed = scrubbed.replace("تومان", " ")
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


def shorten_reply(text: str, limit: int = 18) -> str:
    blob = re.sub(r"\s+", " ", text or "").strip()
    if not blob:
        return ""
    parts = split_sentences(blob) or [blob]
    kept: list[str] = []
    count = 0
    for part in parts:
        words = part.split()
        if count and count + len(words) > limit:
            break
        if not count and len(words) > limit:
            kept.append(" ".join(words[:limit]).rstrip("،,") + ".")
            break
        kept.append(part)
        count += len(words)
        if count >= 12:
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
        if phone and handle:
            found[phone] = ShopCard(instagram=handle, product=product)
    return found
