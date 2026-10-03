"""The router's words: the gate decides and checks the facts, the model says them (see shop_voice_service.say)."""

from __future__ import annotations

import re

from app.services import router_text, shop_voice_service

HOSTILE = re.compile(r"ignore|system prompt|پرامپت|دستورالعمل|jailbreak|\bdan\b|فراموش کن|secret|token|api[_-]?key", re.I)
NEVER = re.compile(r"secret|jwt|api[_-]?key|otp|read_env|\bsql\b|token", re.I)


def is_hostile(spoken: str) -> bool:
    from app.services.turn_parse import parse_turn

    text = spoken or ""
    return bool(
        HOSTILE.search(text)
        or NEVER.search(text)
        or router_text.has_payment_number(text)
        or parse_turn(text).topic in {"secret", "shaba", "other_shop"}
    )


async def voice(spoken: str, text: str, situation: str, rows: list[dict]) -> str:
    """The model's wording of `text`; a refusal is worded from the facts alone (the seller's words may be an attack).
    Without a model, or over the AI budget, the plain text is shown."""
    plain = str(text or "")
    if not plain.strip():
        return plain
    hostile = is_hostile(spoken)
    return await shop_voice_service.say(
        situation,
        [plain],
        seller_text="" if hostile else spoken,
        fallback=plain,
        recent=None if hostile else [row for row in rows[-6:] if isinstance(row, dict)],
    )
