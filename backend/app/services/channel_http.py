from __future__ import annotations

import httpx

from app.config import settings


def channel_proxy() -> str | None:
    raw = (settings.channel_proxy or "").strip()
    return raw or None


def async_client(*, timeout: float = 20, **kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=channel_proxy(), **kwargs)
