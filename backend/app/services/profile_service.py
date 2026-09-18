from __future__ import annotations

from copy import deepcopy

from app.phone import normalize_phone
from app.state_store import read_json, write_json

TONES = {
    "warm": {
        "id": "warm",
        "label": "گرم و خودمونی",
        "tone": "گرم، کوتاه، فارسی روزمره",
        "summary": "فروشندهٔ صمیمی؛ واضح و بی‌تعارف.",
        "sampleReply": "سلام، موجودی را همین حالا چک می‌کنم و برمی‌گردم.",
    },
    "formal": {
        "id": "formal",
        "label": "رسمی و مؤدب",
        "tone": "رسمی، مؤدب، کامل",
        "summary": "پاسخ‌های دقیق و مؤدب برای مشتری.",
        "sampleReply": "با سلام، موجودی و قیمت را بررسی می‌کنم و خدمت‌تان اعلام می‌کنم.",
    },
    "street": {
        "id": "street",
        "label": "جوان و خیابانی",
        "tone": "جوان، کوتاه، پرانرژی",
        "summary": "لحن استریت؛ سریع و خودمانی.",
        "sampleReply": "داشتم همین مدل رو — موجوده، بفرستم برات؟",
    },
    "luxury": {
        "id": "luxury",
        "label": "لوکس و آرام",
        "tone": "آرام، لوکس، کم‌حرف",
        "summary": "برند دست‌دوز و خاص؛ جمله‌های کوتاه.",
        "sampleReply": "این مدل موجود است. جزئیات را برایتان می‌فرستم.",
    },
}

EMPTY = {
    "onboarded": False,
    "firstName": "",
    "lastName": "",
    "brandName": "",
    "brandWork": "",
    "toneId": "warm",
    "hasLogo": False,
}


def _store() -> dict:
    data = read_json("profiles.json", {})
    return data if isinstance(data, dict) else {}


def _save_store(data: dict) -> None:
    write_json("profiles.json", data)


def public_profile(row: dict) -> dict:
    out = deepcopy(EMPTY)
    if isinstance(row, dict):
        out.update({key: row[key] for key in EMPTY if key in row})
    out["onboarded"] = bool(out.get("onboarded"))
    out["hasLogo"] = bool(out.get("hasLogo"))
    tone = str(out.get("toneId") or "warm")
    out["toneId"] = tone if tone in TONES else "warm"
    out["tones"] = [{"id": item["id"], "label": item["label"]} for item in TONES.values()]
    return out


def touch(phone: str, *, existed: bool) -> dict:
    key = normalize_phone(phone)
    store = _store()
    current = store.get(key)
    if isinstance(current, dict):
        return public_profile(current)
    row = deepcopy(EMPTY)
    row["onboarded"] = bool(existed)
    store[key] = row
    _save_store(store)
    return public_profile(row)


def get_profile(phone: str) -> dict:
    key = normalize_phone(phone)
    store = _store()
    current = store.get(key)
    if not isinstance(current, dict):
        return public_profile(EMPTY)
    return public_profile(current)


def for_session(phone: str) -> dict:
    key = normalize_phone(phone)
    store = _store()
    current = store.get(key)
    if isinstance(current, dict):
        return public_profile(current)
    return public_profile({**EMPTY, "onboarded": True})


def patch_profile(phone: str, patch: dict) -> dict:
    key = normalize_phone(phone)
    store = _store()
    row = deepcopy(EMPTY)
    if isinstance(store.get(key), dict):
        row.update({k: store[key][k] for k in EMPTY if k in store[key]})
    allowed = ("firstName", "lastName", "brandName", "brandWork", "toneId", "hasLogo")
    for field in allowed:
        if field not in patch or patch[field] is None:
            continue
        if field == "toneId":
            tone = str(patch[field]).strip()
            row["toneId"] = tone if tone in TONES else row.get("toneId") or "warm"
        elif field == "hasLogo":
            row["hasLogo"] = bool(patch[field])
        else:
            row[field] = str(patch[field]).strip()[:400]
    store[key] = row
    _save_store(store)
    return public_profile(row)


def mark_onboarded(phone: str) -> dict:
    key = normalize_phone(phone)
    store = _store()
    row = store.get(key) if isinstance(store.get(key), dict) else deepcopy(EMPTY)
    row["onboarded"] = True
    store[key] = row
    _save_store(store)
    return public_profile(row)


def is_onboarded(phone: str) -> bool:
    return bool(for_session(phone).get("onboarded"))


def complete(
    phone: str,
    *,
    firstName: str,
    lastName: str,
    brandName: str,
    brandWork: str,
    toneId: str,
    hasLogo: bool,
) -> dict:
    patch_profile(
        phone,
        {
            "firstName": firstName,
            "lastName": lastName,
            "brandName": brandName,
            "brandWork": brandWork,
            "toneId": toneId,
            "hasLogo": hasLogo,
        },
    )
    return mark_onboarded(phone)
