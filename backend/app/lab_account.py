"""One reserved lab phone. It is not a customer and must never receive an SMS."""

from __future__ import annotations

LAB_PHONE = "09120000991"


def is_lab_phone(phone: str) -> bool:
    return str(phone or "").strip() == LAB_PHONE


def require_lab_phone(raw: str) -> str:
    from app.phone import normalize_phone

    phone = normalize_phone(raw)
    if not is_lab_phone(phone):
        raise ValueError("not a lab phone")
    return phone
