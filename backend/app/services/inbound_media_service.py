from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.services import chat_media_service
from app.services.channel_http import async_client
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.inbound-media")
KIND_HINTS = {"image", "video", "audio"}


def _kind_from_url(url: str, hint: str) -> str:
    if hint in KIND_HINTS:
        return hint
    path = urlparse(url).path.lower()
    kind = chat_media_service.kind_of("", path)
    return kind or "image"


async def fetch_and_store(url: str, *, headers: dict | None = None, kind_hint: str = "") -> dict | None:
    raw = (url or "").strip()
    if not raw or not raw.startswith(("http://", "https://")):
        return None
    kind = _kind_from_url(raw, (kind_hint or "").strip().lower())
    cap = chat_media_service.KIND_MAX.get(kind, 8_000_000)
    try:
        async with async_client(timeout=40) as client:
            response = await client.get(raw, headers=headers or {}, follow_redirects=True)
        if response.status_code >= 400 or not response.content:
            raise RuntimeError(f"http-{response.status_code}")
        data = response.content[: cap + 1]
        if len(data) > cap:
            raise RuntimeError("too-large")
        mime = (response.headers.get("content-type") or "").split(";")[0].strip()
        name = urlparse(raw).path.rsplit("/", 1)[-1] or f"inbound.{kind}"
        return chat_media_service.save(name, data, mime or f"{kind}/*")
    except Exception as exc:
        log.warning("inbound media failed: %s", type(exc).__name__)
        emit_later(
            kind="inbox",
            surface="inbox",
            title="inbound-media-failed",
            status="failed",
            payload={"errorClass": type(exc).__name__, "kind": kind},
        )
        return None
