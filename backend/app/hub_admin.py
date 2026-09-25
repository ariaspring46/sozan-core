from __future__ import annotations

# Default in config.py. An unset production env must not grant hub power.
PLACEHOLDER_ADMIN_PHONE = "09120000000"


def is_hub_admin(phone: str) -> bool:
    from app.config import settings
    from app.phone import normalize_phone

    try:
        wanted = normalize_phone(settings.admin_phone)
        got = normalize_phone(phone)
    except ValueError:
        return False
    if wanted == PLACEHOLDER_ADMIN_PHONE:
        return False
    return wanted == got
