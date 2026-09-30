"""Cloud background removal for product cutouts.

`CUTOUT_PROVIDER` picks the service (default `clipdrop`; alternatives
`removebg`, `photoroom`). `CUTOUT_API_KEY` is the owner's key in the hub env.
Traffic rides CHANNEL_PROXY when set. Every cut's cost lands in the observe
ledger like other image spend. Without a key, no cloud call is made and the
caller falls back to the local model behind the dev flag.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.image")

TIMEOUT = 45.0

ENDPOINTS = {
    "clipdrop": ("https://clipdrop-api.co/remove-background/v1", "x-api-key"),
    "removebg": ("https://api.remove.bg/v1.0/removebg", "X-Api-Key"),
    "photoroom": ("https://sdk.photoroom.com/v1/segment", "x-api-key"),
}

# هزینهٔ هر برش به دلار — از مصرف واقعی صفر است تا اولین صورت‌حساب؛ عدد قابل تغییر با env.
COST_PER_CUT = 0.005


def _provider() -> str:
    return str(settings.cutout_provider or "clipdrop").strip().lower()


def _key() -> str:
    return str(settings.cutout_api_key or "").strip()


def cloud_enabled() -> bool:
    provider = _provider()
    return provider in ENDPOINTS and bool(_key())


async def remove_background(png: bytes, *, proxy: str | None = None) -> tuple[bytes, float]:
    """Remove background via cloud. Returns (png_with_alpha, cost_usd)."""
    provider = _provider()
    endpoint, header = ENDPOINTS[provider]
    key = _key()
    headers = {header: key, "Accept": "image/png"}
    files = {"image_file": ("input.png", png, "image/png")}
    params: dict = {}
    if provider == "removebg":
        params = {"size": "auto"}
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, proxy=proxy) as client:
        response = await client.post(endpoint, headers=headers, files=files, params=params)
    if response.status_code >= 400:
        log.warning("cloud cutout rejected: http=%s provider=%s", response.status_code, provider)
        emit_later(
            kind="routing",
            title="cloud-cutout-failed",
            surface="image",
            status="error",
            payload={"provider": provider, "http": response.status_code},
        )
        raise RuntimeError(f"cloud-cutout-{response.status_code}")
    return response.content, COST_PER_CUT
