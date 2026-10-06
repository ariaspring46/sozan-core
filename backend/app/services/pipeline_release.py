from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import settings

EVENT_VERSION = 1
BEHAVIOR_VERSION = "2026.10.06-harness"

_HERE = Path(__file__).resolve().parent
_HUB_FILES = tuple(
    _HERE / name
    for name in (
        "observe_client.py",
        "shop_service.py",
        "shop_edit_service.py",
        "channel_scan_service.py",
        "shop_intent_service.py",
        "shop_route_service.py",
        # The agents themselves: a change here must change the release id on their events.
        "router_service.py",
        "router_embed.py",
        "router_voice.py",
        "router_text.py",
        "turn_parse.py",
        "shop_voice_service.py",
        "number_span.py",
        "turn_clock.py",
        "channel_tool.py",
        "llm.py",
        "inbox_agent_service.py",
        "studio_chat_service.py",
        "image_provider_service.py",
        "claims_guard.py",
    )
)
_DATA_DIR = _HERE.parent / "data"
_digest_cache: dict[tuple, str] = {}


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _release_files() -> list[Path]:
    data = sorted(_DATA_DIR.glob("*.json")) if _DATA_DIR.is_dir() else []
    return [*_HUB_FILES, *data, settings.factory_script]


def hub_release_id() -> str:
    files = _release_files()
    stamp = []
    for path in files:
        try:
            info = path.stat()
            stamp.append((str(path), info.st_mtime_ns, info.st_size))
        except OSError:
            stamp.append((str(path), 0, -1))
    key = tuple(stamp)
    cached = _digest_cache.get(key)
    if cached:
        return cached
    joined = "|".join(_file_digest(path) for path in files).encode()
    value = hashlib.sha256(joined).hexdigest()[:20]
    _digest_cache.clear()
    _digest_cache[key] = value
    return value


def envelope(
    *,
    kind: str,
    title: str,
    surface: str,
    component: str = "",
    stage: str = "",
    status: str = "",
    tenant: str = "",
    brand: str = "",
    conversation_id: str = "",
    turn_id: str = "",
    operation_id: str = "",
    job_id: str = "",
    scan_id: str = "",
    parent_id: str = "",
    event_id: str = "",
    started_at: float | None = None,
    duration_ms: int | None = None,
    payload: dict | None = None,
) -> dict:
    from uuid import uuid4

    from app.state_store import current_tenant

    body = dict(payload or {})
    return {
        "eventVersion": EVENT_VERSION,
        "eventId": event_id or str(uuid4()),
        "tenant": tenant or current_tenant(),
        "conversationId": conversation_id,
        "turnId": turn_id,
        "operationId": operation_id or turn_id or job_id or scan_id,
        "jobId": job_id,
        "scanId": scan_id,
        "parentId": parent_id,
        "surface": surface,
        "component": component or surface,
        "releaseId": hub_release_id(),
        "behaviorVersion": BEHAVIOR_VERSION,
        "stage": stage,
        "status": status,
        "startedAt": started_at,
        "durationMs": duration_ms,
        "kind": kind,
        "title": title[:240],
        "brand": brand,
        "payload": body,
    }
