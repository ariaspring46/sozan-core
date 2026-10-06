"""The seller turn's id and its 30-second budget. Other loops do not arm this clock."""

from __future__ import annotations

import time
from contextvars import ContextVar, Token

_TURN = ContextVar("sozan_turn_id", default="")
_DEADLINE = ContextVar("sozan_turn_deadline", default=0.0)


def arm(turn_id: str, seconds: float = 30.0) -> tuple[Token, Token]:
    return (_TURN.set(str(turn_id or "")), _DEADLINE.set(time.monotonic() + seconds))


def disarm(tokens: tuple[Token, Token]) -> None:
    turn_token, deadline_token = tokens
    _TURN.reset(turn_token)
    _DEADLINE.reset(deadline_token)


def turn_id() -> str:
    return _TURN.get()


def remaining() -> float:
    deadline = _DEADLINE.get()
    if deadline <= 0:
        return 10**9
    return deadline - time.monotonic()


def expired() -> bool:
    deadline = _DEADLINE.get()
    return deadline > 0 and time.monotonic() >= deadline
