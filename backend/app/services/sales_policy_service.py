"""Shop shipping and return policy.

The panel and the inbox agent share sales-policy.json. Empty fields mean the
seller has not set them, so that topic is handed to the seller.
"""

from __future__ import annotations

from app.state_store import read_json, write_json
import re
from app.state_store import read_json
TEXT_FIELDS = (
    "shippingMethod",
    "shippingDays",
    "shippingCities",
    "returnNote",
    "returnPayer",
    "hours",
    "sizeExchange",
    "invoice",
    "cod",
    "cardToCard",
    "cardNumber",
    "sheba",
    "accountHolder",
)
INT_FIELDS = ("shippingCost", "freeShippingFrom", "returnDays", "minOrder")


def public_policy() -> dict:
    raw = read_json("sales-policy.json", {})
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key in TEXT_FIELDS:
        value = str(raw.get(key) or "").strip()
        if value:
            out[key] = value
    for key in INT_FIELDS:
        if key not in raw or raw.get(key) in ("", None):
            continue
        try:
            number = int(raw.get(key))
        except (TypeError, ValueError):
            continue
        if number >= 0:
            out[key] = number
    return out


def _integer(value: object) -> int:
    text = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    text = text.replace(",", "").replace("٬", "").strip()
    return int(text)


def save_policy(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("سیاست نامعتبر است")
    cleaned: dict = {}
    for key in TEXT_FIELDS:
        value = str(patch.get(key) or "").strip()
        if value:
            cleaned[key] = value[:200]
    card = str(cleaned.get("cardNumber") or "").replace("-", "").strip()
    if card:
        if not (card.isdigit() and len(card) == 16):
            raise ValueError("شماره کارت باید ۱۶ رقم باشد")
        cleaned["cardNumber"] = card
    sheba = str(cleaned.get("sheba") or "").strip()
    if sheba:
        sheba = sheba.replace(" ", "").upper()
        if not (sheba.startswith("IR") and len(sheba) == 24):
            raise ValueError("شبا باید با IR شروع شود و ۲۴ نویسه باشد")
        cleaned["sheba"] = sheba
    for key in INT_FIELDS:
        if key not in patch or patch.get(key) in ("", None):
            continue
        try:
            number = _integer(patch.get(key))
        except (TypeError, ValueError) as exc:
            raise ValueError("عدد سیاست نامعتبر است") from exc
        if number < 0:
            raise ValueError("عدد سیاست نامعتبر است")
        cleaned[key] = number
    write_json("sales-policy.json", cleaned)
    return cleaned


def battery_policy() -> dict:
    """Policy for the sales-battery shop.

    minOrder is omitted on purpose: the minimum-purchase question must still
    hand off, while every other stored field can be answered from this file.
    """
    return {
        "shippingMethod": "پست پیشتاز",
        "shippingCost": 60000,
        "shippingDays": "۳ تا ۵ روز کاری",
        "shippingCities": "همهٔ شهرها",
        "freeShippingFrom": 2000000,
        "returnDays": 7,
        "returnNote": "اگر استفاده نشده باشد پس گرفته می‌شود",
        "returnPayer": "مشتری",
        "hours": "۱۰ تا ۱۸",
        "sizeExchange": "تعویض سایز تا ۷ روز اگر استفاده نشده باشد",
        "invoice": "بله، فاکتور فروش می‌دهیم",
        "cod": "نداریم",
    }


def _norm(text: str) -> str:
    return (
        str(text or "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .strip()
        .lower()
    )


def _fa(value: int) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _sentence(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    if cleaned.endswith((".", "۔", "!", "؟")):
        return cleaned
    return f"{cleaned}."


def get_policy() -> dict:
    raw = read_json("sales-policy.json", {})
    if not isinstance(raw, dict):
        raw = {}
    out: dict = {}
    for key in TEXT_FIELDS:
        out[key] = str(raw.get(key) or "").strip()
    for key in INT_FIELDS:
        value = raw.get(key)
        if value is None or value == "":
            out[key] = None
            continue
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            out[key] = None
    return out


def _shipping(policy: dict) -> str:
    parts = []
    if policy["shippingMethod"]:
        parts.append(f"ارسال با {policy['shippingMethod']} است.")
    if policy["shippingCost"] is not None:
        parts.append(f"هزینهٔ ارسال {_fa(policy['shippingCost'])} تومان است.")
    if policy["shippingDays"]:
        parts.append(f"مدت ارسال {policy['shippingDays']} است.")
    if policy["shippingCities"]:
        parts.append(f"شهرها: {policy['shippingCities']}.")
    if policy["freeShippingFrom"] is not None:
        parts.append(f"ارسال رایگان از {_fa(policy['freeShippingFrom'])} تومان است.")
    return " ".join(parts)


def _free(policy: dict) -> str:
    if policy["freeShippingFrom"] is None:
        return ""
    return f"ارسال رایگان از {_fa(policy['freeShippingFrom'])} تومان است."


def _returns(policy: dict) -> str:
    parts = []
    if policy["returnDays"] is not None:
        parts.append(f"مهلت مرجوعی {_fa(policy['returnDays'])} روز است.")
    if policy["returnNote"]:
        parts.append(_sentence(policy["returnNote"]))
    if policy["returnPayer"]:
        parts.append(f"هزینهٔ برگشت با {policy['returnPayer']} است.")
    return " ".join(parts)


def _hours(policy: dict) -> str:
    return f"ساعت کاری: {policy['hours']}." if policy["hours"] else ""


def _exchange(policy: dict) -> str:
    return _sentence(policy["sizeExchange"])


def _invoice(policy: dict) -> str:
    return _sentence(policy["invoice"])


def _min_order(policy: dict) -> str:
    if policy["minOrder"] is None:
        return ""
    return f"حداقل خرید {_fa(policy['minOrder'])} تومان است."


def _card(policy: dict) -> str:
    text = policy.get("cardToCard") or ""
    if not text:
        return ""
    if "کارت" in text:
        return _sentence(text)
    return f"کارت به کارت: {text}."


def _cod(policy: dict) -> str:
    text = policy["cod"]
    if not text:
        return ""
    if "پرداخت" in text:
        return _sentence(text)
    return f"پرداخت در محل: {text}."


def fixed_reply(text: str) -> str | None:
    """None when the message is not about shipping, returns, or shop policy.

    A string, possibly empty, when it is. Empty means that fact is not stored.
    """
    folded = _norm(text)
    if not folded:
        return None
    policy = get_policy()
    if "کارت به کارت" in folded:
        if policy.get("cardToCard"):
            return _card(policy)
        if "کارت به کارت" in _norm(policy.get("cod") or ""):
            return _cod(policy)
        return ""
    if "پرداخت در محل" in folded or "درب منزل" in folded:
        return _cod(policy)
    if "حداقل خرید" in folded:
        return _min_order(policy)
    if "فاکتور" in folded:
        return _invoice(policy)
    if "ساعت کار" in folded:
        return _hours(policy)
    if "تعویض" in folded:
        return _exchange(policy)
    if any(mark in folded for mark in ("مرجوع", "برمیگرد", "برگشت", "سایز نخورد")) or (
        "فرق" in folded and "عکس" in folded
    ):
        return _returns(policy)
    if "ارسال رایگان" in folded:
        return _free(policy)
    if "ارسال شد" in folded:
        return None
    if any(mark in folded for mark in ("ارسال", "پیشتاز", "شهرستان", "پست")):
        return _shipping(policy)
    return None


# --- seller-sentence parsing (plan §7.2) -------------------------------------
#
# parse(sentence) turns a seller's spoken policy into a structured patch plus a
# confirmation card. It is deterministic: numbers and promises come only from
# the sentence itself, never guessed. The caller (panel form today, X's
# set_sales_policy router tool with the qa50 gate later) shows the card and
# saves the patch only after the seller confirms.

_FA_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SHEBA_RE = re.compile(r"IR\s?(?:\d[\s-]?){24}", re.IGNORECASE)
_HOLDER_RE = re.compile(r"به\s*نام\s+([^\n،.]+)")
_METHODS = ("پست پیشتاز", "پست معمولی", "تیپاکس", "پیک", "باربری", "پست")
_WORD_VALUES = {
    "مجانی": 0,
    "رایگان": 0,
}
_CARD_FIELD_ORDER = (
    "shippingMethod",
    "shippingCost",
    "shippingDays",
    "shippingCities",
    "freeShippingFrom",
    "returnDays",
    "returnPayer",
    "hours",
    "minOrder",
    "invoice",
    "cod",
    "cardNumber",
    "sheba",
    "accountHolder",
)
CARD_FIELDS = ("shippingCost", "freeShippingFrom", "returnDays", "minOrder", "cardNumber", "sheba", "accountHolder")


def _fold_digits(text: str) -> str:
    return str(text or "").translate(_FA_FOLD)


def _numbers(text: str) -> list[tuple[int, str]]:
    """(value, raw) for amounts; unit-less small numbers (counts, days) stay out."""
    folded = _fold_digits(text)
    out = []
    for match in re.finditer(r"(\d[\d,،_]*)(?:\s*(هزار|میلیون))?", folded):
        digits = match.group(1).replace(",", "").replace("،", "").replace("_", "")
        unit = match.group(2) or ""
        value = int(digits) * (1000 if unit == "هزار" else 1_000_000 if unit == "میلیون" else 1)
        if unit or value >= 1000:
            out.append((value, match.group(0).strip()))
    return out


def _fa_span(match_text: str) -> str:
    return match_text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _word_number(text: str) -> int | None:
    """«ششصد هزار», «دو میلیون»: word + unit combos worth knowing."""
    words = {
        "صد": 100,
        "دویست": 200,
        "سیصد": 300,
        "پانصد": 500,
        "ششصد": 600,
        "هفتصد": 700,
        "هشتصد": 800,
        "نهصد": 900,
        "دو": 2,
        "سه": 3,
        "پنج": 5,
        "یک": 1,
        "نیم": 0.5,
    }
    folded = str(text or "").replace("\u200c", " ")
    for word, base in words.items():
        for unit, mult in (("میلیون", 1_000_000), ("هزار", 1000)):
            if f"{word} {unit}" in folded and base * mult >= 1000:
                return int(base * mult)
    return None


def parse(sentence: str) -> dict:
    """Seller sentence → {"patch": {...}, "card": {...}}.

    patch holds only confidently parsed fields (int for *_INT_KEYS, string for
    the rest). card lists every known policy field with its parsed value or a
    missing state, for the confirmation UI.
    """
    raw = str(sentence or "").strip()
    folded = _fold_digits(raw).replace("\u200c", "").replace("\u200d", "")
    patched: dict = {}

    for word, value in _WORD_VALUES.items():
        if re.search(rf"(هزینه|کرایه|پست|ارسال)[^\n]{{0,25}}{word}", folded) and "بالای" not in folded:
            patched.setdefault("shippingCost", value)

    method = next((name for name in _METHODS if name in folded), "")
    if method:
        patched["shippingMethod"] = method

    cities = ""
    if re.search(r"همهٔ?\s*شهرها|همه\s+شهرها|سراسر\s+کشور", folded):
        cities = "همهٔ شهرها"
    else:
        city = re.search(r"(?:به|در)\s+(تهران|کرج|اصفهان|مشهد|شیراز|تبریز)(?:\s+و\s+\S+)?", folded)
        if city:
            cities = city.group(0).replace("به ", "").replace("در ", "").strip()
    if cities:
        patched["shippingCities"] = cities

    days = re.search(r"(\d{1,2}(?:\s*تا\s*\d{1,2})?)\s*روز", folded)
    if days and any(mark in folded for mark in ("ارسال", "پست", "تحویل", "می‌رسد", "میرسه", "کارخانه")):
        patched["shippingDays"] = f"{_fa_span(days.group(1))} روز"

    if any(mark in folded for mark in ("ارسال", "پست", "کرایه", "هزینهٔ ارسال", "هزینه ارسال", "تیپاکس", "پیک", "باربری")) and "رایگان" not in folded:
        for value, span in _numbers(folded):
            if "روز" in span:
                continue
            context = folded[max(0, folded.find(span) - 40) : folded.find(span) + len(span) + 6]
            if "مرجوع" in context or "برگشت" in context or "حداقل" in context:
                continue
            patched.setdefault("shippingCost", value)
            break
    if "shippingCost" not in patched:
        for value, span in _numbers(folded):
            if "روز" in span:
                continue
            context = folded[max(0, folded.find(span) - 40) : folded.find(span) + len(span) + 6]
            if re.search(r"(هزینه|کرایه|پست|ارسال|تیپاکس|پیک|باربری)[^\d]{0,20}$", context):
                patched.setdefault("shippingCost", value)
                break

    free = re.search(r"(?:ارسال\s+رایگان[^\d]{0,30}|بالای\s+)(\d[\d,،_]*)", folded)
    if free:
        value = int(free.group(1).replace(",", "").replace("،", ""))
        if value >= 1000:
            patched["freeShippingFrom"] = value
    if "freeShippingFrom" not in patched:
        for value, span in _numbers(folded):
            context = folded[max(0, folded.find(span) - 50) : folded.find(span) + len(span) + 10]
            if "رایگان" in context and ("بالای" in context or "از" in context):
                patched["freeShippingFrom"] = value
                break

    returns = re.search(r"(\d{1,2})\s*روز[^\n.]{0,20}(مرجوع|برگشت|پس گرفت)|مرجوعی\s*(\d{1,2})\s*روز", folded)
    if returns:
        patched["returnDays"] = int(returns.group(1) or returns.group(3))
    elif re.search(r"(\d{1,2})\s*روزه?[^\n.]{0,10}(مرجوع|برگشت)", folded):
        match = re.search(r"(\d{1,2})\s*روز", folded)
        if match:
            patched["returnDays"] = int(match.group(1))
    payer = re.search(r"(هزینهٔ?\s*برگشت|پست\s*برگشت|هزینهٔ?\s*مرجوعی)[^\n.]{0,15}(مشتری|فروشنده|خریدار)", folded)
    if payer:
        patched["returnPayer"] = payer.group(2) if payer.group(2) != "خریدار" else "مشتری"

    hours = re.search(r"از\s*(\d{1,2})(?:\s*صبح)?\s*تا\s*(\d{1,2})(?:\s*(عصر|شب|شام))?", folded)
    if not hours and "ساعت" in folded and "روز" not in folded:
        hours = re.search(r"(\d{1,2})\s*تا\s*(\d{1,2})", folded)
    if hours:
        start = int(hours.group(1)) + 12 if hours.group(1) and int(hours.group(1)) <= 8 and not hours.group(2) else int(hours.group(1))
        end = int(hours.group(2)) + 12 if hours.group(2) and int(hours.group(2)) <= 8 else int(hours.group(2) or 0)
        if end:
            patched["hours"] = f"{_fa(str(start))} تا {_fa(str(end))}"

    minimum = re.search(r"حداقل\s*(خرید|سفارش)[^\d]{0,15}(\d[\d,،_]*)", folded)
    if minimum:
        value = int(minimum.group(2).replace(",", "").replace("،", ""))
        if value >= 1000:
            patched["minOrder"] = value
    if "minOrder" not in patched:
        for value, span in _numbers(folded):
            context = folded[max(0, folded.find(span) - 30) : folded.find(span) + len(span) + 4]
            if "حداقل" in context:
                patched["minOrder"] = value
                break

    if re.search(r"فاکتور[^\n.]{0,10}(می\s*دهیم|داریم|صادر|می کنیم)", folded):
        patched["invoice"] = "بله، فاکتور فروش می‌دهیم"

    if re.search(r"پرداخت\s*(در\s*محل|درب\s*منزل)\s*(داریم|هست|می‌دهیم|می کنیم|میکنیم)", folded):
        patched["cod"] = "داریم"
    elif re.search(r"پرداخت\s*(در\s*محل|درب\s*منزل)\s*(نداریم|نیست)", folded):
        patched["cod"] = "نداریم"

    flat = folded.replace(" ", "").replace("-", "")
    card_match = re.search(r"\d{16}", flat)
    if card_match:
        patched["cardNumber"] = card_match.group(0)
    sheba = _SHEBA_RE.search(folded.replace(" ", "").replace("-", ""))
    if sheba:
        patched["sheba"] = sheba.group(0).upper().replace(" ", "")
    holder = _HOLDER_RE.search(raw)
    if holder:
        patched["accountHolder"] = holder.group(1).strip()

    card_rows = {}
    for key in _CARD_FIELD_ORDER:
        if key in patched:
            card_rows[key] = {"value": patched[key], "state": "parsed"}
        else:
            card_rows[key] = {"value": "", "state": "missing"}
    return {"patch": patched, "card": card_rows}
