from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import settings

EVENT_VERSION = 1
BEHAVIOR_VERSION = "2026.09.16-pipeline"

_HUB_FILES = (
    Path(__file__).resolve().parent / "observe_client.py",
    Path(__file__).resolve().parent / "shop_service.py",
    Path(__file__).resolve().parent / "shop_edit_service.py",
    Path(__file__).resolve().parent / "channel_scan_service.py",
    Path(__file__).resolve().parent / "shop_intent_service.py",
    Path(__file__).resolve().parent / "shop_route_service.py",
)


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def hub_release_id() -> str:
    parts = [_file_digest(path) for path in _HUB_FILES]
    factory = settings.factory_script
    parts.append(_file_digest(factory))
    joined = "|".join(parts).encode()
    return hashlib.sha256(joined).hexdigest()[:20]


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
