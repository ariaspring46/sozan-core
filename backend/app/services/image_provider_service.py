from __future__ import annotations

import base64
import logging
import os

import httpx

from app.services.observe_client import observe_base

log = logging.getLogger("sozan.image")

DEFAULT_STILL = (
    "cinematic product still life on a clean studio surface, soft directional light, "
    "empty shop, no people, no text, no logos"
)


def generate_still(prompt: str, *, width: int = 1080, height: int = 1080) -> bytes:
    from app.services import llm_routing_service

    text = (prompt or "").strip() or DEFAULT_STILL
    route = llm_routing_service.get("image") or {}
    if str(route.get("kind") or "") == "cloud":
        png = _openai_images(text, width=width, height=height, route=route)
        if png:
            return png
        log.warning("cloud image provider failed; falling back to local observe")
    return _observe_local(text, width=width, height=height)


def _observe_local(prompt: str, *, width: int, height: int) -> bytes:
    url = f"{observe_base()}/observe/api/image"
    try:
        with httpx.Client(timeout=httpx.Timeout(420.0, connect=5.0), trust_env=False) as client:
            res = client.post(url, json={"prompt": prompt, "width": width, "height": height})
    except Exception as exc:
        log.warning("observe image failed: %s", type(exc).__name__)
        return b""
    if res.status_code != 200 or len(res.content) < 2048:
        return b""
    if "json" in (res.headers.get("content-type") or ""):
        return b""
    return res.content


def _openai_images(prompt: str, *, width: int, height: int, route: dict) -> bytes:
    from app.services import llm_routing_service

    provider = llm_routing_service.provider(str(route.get("provider") or ""))
    base = str(provider.get("base_url") or "").rstrip("/")
    model = str(route.get("model") or "").strip()
    key_env = str(provider.get("key_env") or "CLOUD_LLM_TOKEN")
    token = (os.environ.get(key_env) or "").strip()
    if not base or not model or not token:
        return b""
    size = f"{max(256, min(width, 2048))}x{max(256, min(height, 2048))}"
    proxy = (os.environ.get("CLOUD_LLM_PROXY") or os.environ.get("CHANNEL_PROXY") or "").strip() or None
    try:
        with httpx.Client(timeout=httpx.Timeout(180.0, connect=5.0), trust_env=False, proxy=proxy) as client:
            res = client.post(
                f"{base}/images/generations",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"model": model, "prompt": prompt[:800], "size": size, "response_format": "b64_json"},
            )
        if res.status_code >= 400:
            log.warning("cloud images http %s: %s", res.status_code, res.text[:200])
            return b""
        data = res.json()
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            return b""
        raw = str((rows[0] or {}).get("b64_json") or "")
        if not raw:
            return b""
        png = base64.b64decode(raw)
        return png if len(png) >= 2048 else b""
    except Exception as exc:
        log.warning("cloud images failed: %s", type(exc).__name__)
        return b""


def probe_ollama_cloud() -> dict:
    from app.config import settings

    token = (settings.cloud_llm_token or os.environ.get("OLLAMA_API_KEY") or "").strip()
    if not token:
        return {"ok": False, "error": "no-token"}
    proxy = (settings.cloud_llm_proxy or settings.channel_proxy or "").strip() or None
    url = "https://ollama.com/v1/images/generations"
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), trust_env=False, proxy=proxy) as client:
            res = client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "model": "x/z-image-turbo",
                    "prompt": "a white ceramic mug on a wooden table, no text",
                    "size": "512x512",
                    "response_format": "b64_json",
                },
            )
        return {
            "ok": res.status_code < 400 and "b64_json" in (res.text or ""),
            "status": res.status_code,
            "detail": (res.text or "")[:240],
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
