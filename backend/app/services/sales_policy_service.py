"""Fixed replies from the shop's stored sales policy.

Numbers and promises come only from sales-policy.json. A missing field is not filled in.
"""

from __future__ import annotations

from app.state_store import read_json

_TEXT_KEYS = (
    "shippingMethod",
    "shippingDays",
    "shippingCities",
    "returnNote",
    "returnPayer",
    "hours",
    "sizeExchange",
    "invoice",
    "cod",
)
_INT_KEYS = ("shippingCost", "freeShippingFrom", "returnDays", "minOrder")


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
    for key in _TEXT_KEYS:
        out[key] = str(raw.get(key) or "").strip()
    for key in _INT_KEYS:
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
