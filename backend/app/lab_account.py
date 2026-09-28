"""One reserved lab phone. It is not a customer and must never receive an SMS."""

from __future__ import annotations

LAB_PHONE = "09120000991"


def lab_login_active() -> bool:
    """ورود بی‌کدِ حساب آزمایشی فقط تا تاریخ انقضا (LAB_LOGIN_UNTIL) باز است."""
    from app.config import settings

    import datetime as _dt

    try:
        until = _dt.date.fromisoformat(str(settings.lab_login_until or "").strip())
    except ValueError:
        return False
    return _dt.date.today() <= until


def is_lab_phone(phone: str) -> bool:
    return lab_login_active() and str(phone or "").strip() == LAB_PHONE


def require_lab_phone(raw: str) -> str:
    from app.phone import normalize_phone

    phone = normalize_phone(raw)
    if not is_lab_phone(phone):
        raise ValueError("not a lab phone")
    return phone
