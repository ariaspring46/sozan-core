"""Shop shipping and return policy. Empty fields mean the seller has not set them."""

from __future__ import annotations

from app.state_store import read_json, write_json

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
