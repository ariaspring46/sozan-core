"""Cloud background removal for product cutouts.

`CUTOUT_PROVIDER` picks the service (default `clipdrop`; alternatives
`removebg`, `photoroom`). `CUTOUT_API_KEY` is the owner's key in the hub env.
Traffic rides CHANNEL_PROXY when set. Every cut's cost lands in the observe
ledger like other image spend. Without a key, no cloud call is made and the
caller falls back to the local model behind the dev flag.
"""

from __future__ import annotations

import logging

import io

import httpx
from PIL import Image

from app.config import settings
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.image")

TIMEOUT = 45.0

ENDPOINTS = {
    "clipdrop": ("https://clipdrop-api.co/remove-background/v1", "x-api-key"),
    "removebg": ("https://api.remove.bg/v1.0/removebg", "X-Api-Key"),
    "photoroom": ("https://sdk.photoroom.com/v1/segment", "x-api-key"),
}

DEFAULT_OPENROUTER_EDIT_MODEL = "google/gemini-2.5-flash-image-preview"
CUT_PROMPT = (
    "Remove the background of this image completely. "
    "Keep the product exactly as it is — untouched pixels, same shape, same colors. "
    "Output the product on a plain solid white background, full image size."
)

# هزینهٔ هر برش به دلار — از usage.cost پاسخ خوانده می‌شود؛ این فقط فالبک تخمینی است.
COST_PER_CUT = 0.005


def _provider() -> str:
    return str(settings.cutout_provider or "openrouter").strip().lower()


def _key() -> str:
    if _provider() == "openrouter":
        import os

        return os.environ.get("open_router_api_token", "").strip() or str(settings.cutout_api_key or "").strip()
    return str(settings.cutout_api_key or "").strip()


def cloud_enabled() -> bool:
    provider = _provider()
    if provider == "openrouter":
        import os

        return bool(os.environ.get("CLOUD_LLM_URL", "").strip()) and bool(_key())
    return provider in ENDPOINTS and bool(_key())


def _flood_white_to_alpha(image: Image.Image, threshold: int = 242) -> Image.Image:
    """پس‌زمینهٔ سفید یکدست را از لبه‌ها شفاف می‌کند — قطعی و میلی‌ثانیه‌ای، ML نیست."""
    from collections import deque

    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()

    def is_white(point) -> bool:
        r, g, b, _ = point
        return r >= threshold and g >= threshold and b >= threshold

    seen = [[False] * width for _ in range(height)]
    queue = deque()
    for x in range(width):
        for y in (0, height - 1):
            if is_white(pixels[x, y]) and not seen[y][x]:
                seen[y][x] = True
                queue.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if is_white(pixels[x, y]) and not seen[y][x]:
                seen[y][x] = True
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        pixels[x, y] = (255, 255, 255, 0)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and not seen[ny][nx] and is_white(pixels[nx, ny]):
                seen[ny][nx] = True
                queue.append((nx, ny))
    return rgba


def _extract_image_part(payload: dict) -> bytes | None:
    import base64

    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    message = (choices[0] or {}).get("message") if choices and isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        return None
    raw = ""
    images = message.get("images") if isinstance(message.get("images"), list) else []
    if images and isinstance(images[0], dict):
        image_url = images[0].get("image_url")
        raw = str(image_url.get("url") if isinstance(image_url, dict) else image_url or "")
    if not raw:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
                    image_url = part.get("image_url")
                    raw = str(image_url.get("url") if isinstance(image_url, dict) else image_url or "")
                    if raw:
                        break
        elif isinstance(content, str) and content.startswith("data:image"):
            raw = content
    if not raw.startswith("data:") or "," not in raw:
        return None
    try:
        return base64.b64decode(raw.split(",", 1)[1])
    except Exception:
        return None


def _emit_failure(error_class: str, return_code: str) -> None:
    emit_later(
        kind="routing",
        title="cloud-cutout-failed",
        surface="image",
        status="error",
        payload={"errorClass": error_class, "returnCode": str(return_code)[:20]},
    )


async def remove_background(png: bytes, *, proxy: str | None = None) -> tuple[bytes, float]:
    """Remove background via cloud. Returns (png_with_alpha, cost_usd)."""
    provider = _provider()
    if provider == "openrouter":
        import base64

        url = str(settings.cloud_llm_url or "").rstrip("/")
        token = _key()
        model = str(settings.cutout_openrouter_model or DEFAULT_OPENROUTER_EDIT_MODEL).strip()
        b64 = base64.b64encode(png).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "curl/8.5.0",
        }
        body = {
            "model": model,
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CUT_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=90, trust_env=False, proxy=proxy) as client:
            response = await client.post(f"{url}/chat/completions", json=body, headers=headers)
        if response.status_code >= 400:
            log.warning("openrouter cutout rejected: http=%s", response.status_code)
            _emit_failure("provider", f"http-{response.status_code}")
            raise RuntimeError(f"cloud-cutout-{response.status_code}")
        payload = response.json() if isinstance(response.json(), dict) else {}
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        try:
            cost = float(usage.get("cost") or COST_PER_CUT)
        except (TypeError, ValueError):
            cost = COST_PER_CUT
        image_bytes = _extract_image_part(payload)
        if not image_bytes:
            log.warning("openrouter cutout returned no image")
            _emit_failure("provider", "no-image")
            raise RuntimeError("cloud-cutout-no-image")
        record = Image.open(io.BytesIO(image_bytes))
        try:
            has_alpha = record.mode in ("RGBA", "LA") and record.getextrema()[3][0] < 250
        except Exception:
            has_alpha = False
        result = record if has_alpha else _flood_white_to_alpha(record)
        out = io.BytesIO()
        result.save(out, "PNG")
        return out.getvalue(), cost
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
        _emit_failure("provider", f"http-{response.status_code}")
        raise RuntimeError(f"cloud-cutout-{response.status_code}")
    return response.content, COST_PER_CUT
