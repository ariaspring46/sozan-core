from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.config import settings
from app.services.pipeline_release import BEHAVIOR_VERSION, envelope, hub_release_id
from app.state_store import current_tenant, tenant_dir


def observe_base() -> str:
    url = settings.local_llm_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url.rstrip("/")


def _brand() -> str:
    try:
        from app.services.settings_service import get_settings

        return str(get_settings().get("storeName") or "")
    except Exception:
        return ""


def identity(*, surface: str) -> dict[str, str]:
    return {
        "tenant": current_tenant(),
        "surface": surface,
        "brand": _brand(),
        "releaseId": hub_release_id(),
        "behaviorVersion": BEHAVIOR_VERSION,
    }


def _http_header_value(value: str) -> str:
    text = str(value or "").strip().replace("\r", " ").replace("\n", " ")
    if not text:
        return ""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return quote(text, safe="")


def llm_headers(*, surface: str) -> dict[str, str]:
    ident = identity(surface=surface)
    out = {
        "X-Sozan-Tenant": _http_header_value(ident["tenant"]),
        "X-Sozan-Surface": _http_header_value(ident["surface"]),
        "X-Sozan-Brand": _http_header_value(ident["brand"]),
        "X-Sozan-Release": _http_header_value(ident["releaseId"]),
        "X-Sozan-Behavior": _http_header_value(ident["behaviorVersion"]),
        "X-Sozan-Request": _http_header_value(str(uuid4())),
    }
    return {key: value for key, value in out.items() if value}


def outbox_path() -> Any:
    path = tenant_dir().parent / "observe-outbox.jsonl"
    if current_tenant():
        path = tenant_dir() / "observe-outbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_OUTBOX_MAX_ROWS = 2000
_OUTBOX_COOLDOWN = 30.0
_flush_cooldown_until = 0.0


def _append_outbox(body: dict[str, Any]) -> None:
    row = dict(body)
    row.setdefault("queuedAt", time.time())
    row.setdefault("attempts", 0)
    try:
        path = outbox_path()
        existing: list[str] = []
        dropped = 0
        if path.is_file():
            existing = path.read_text(encoding="utf-8").splitlines()
        over = len(existing) + 1 - _OUTBOX_MAX_ROWS
        if over > 0:
            # سقف صف: قدیمی‌ترین‌ها دور ریخته می‌شوند؛ تازه‌ها می‌مانند.
            dropped = over
            existing = existing[over:]
        with path.open("w", encoding="utf-8") as handle:
            if dropped:
                handle.write(json.dumps({"dropped": dropped, "queuedAt": time.time()}) + "\n")
            for line in existing:
                handle.write(line + "\n")
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if dropped:
            emit_later(kind="observe", title="observe-outbox-dropped", surface="observe", status="error", payload={"dropped": dropped})
    except Exception:
        pass


def _rewrite_outbox(rows: list[dict[str, Any]]) -> None:
    path = outbox_path()
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def load_outbox() -> list[dict[str, Any]]:
    path = outbox_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


async def _post_event(body: dict[str, Any]) -> bool:
    try:
        async with httpx.AsyncClient(timeout=0.8, trust_env=False) as client:
            response = await client.post(f"{observe_base()}/sozan/events", json=body)
            return response.status_code < 400
    except Exception:
        return False


async def flush_outbox(limit: int = 40) -> int:
    global _flush_cooldown_until
    if time.time() < _flush_cooldown_until:
        return 0
    rows = load_outbox()
    if not rows:
        return 0
    kept: list[dict[str, Any]] = []
    sent = 0
    for index, row in enumerate(rows):
        if index >= limit:
            kept.append(row)
            continue
        ok = await _post_event(row)
        if ok:
            sent += 1
            continue
        row["attempts"] = int(row.get("attempts") or 0) + 1
        kept.append(row)
    _rewrite_outbox(kept)
    if sent == 0 and kept:
        # تونل قطع است؛ ۳۰ ثانیه دوباره فایل را باز نکن.
        _flush_cooldown_until = time.time() + _OUTBOX_COOLDOWN
    return sent


async def emit(
    *,
    kind: str,
    title: str,
    payload: dict[str, Any] | None = None,
    surface: str = "",
    component: str = "",
    stage: str = "",
    status: str = "",
    conversation_id: str = "",
    turn_id: str = "",
    operation_id: str = "",
    job_id: str = "",
    scan_id: str = "",
    parent_id: str = "",
    event_id: str = "",
    started_at: float | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    ident = identity(surface=surface)
    body = envelope(
        kind=kind,
        title=title,
        surface=ident["surface"] or surface,
        component=component,
        stage=stage,
        status=status,
        tenant=ident["tenant"],
        brand=ident["brand"],
        conversation_id=conversation_id,
        turn_id=turn_id,
        operation_id=operation_id,
        job_id=job_id,
        scan_id=scan_id,
        parent_id=parent_id,
        event_id=event_id,
        started_at=started_at,
        duration_ms=duration_ms,
        payload=payload,
    )
    ok = await _post_event(body)
    if not ok:
        _append_outbox(body)
    return body


def emit_later(
    *,
    kind: str,
    title: str,
    payload: dict[str, Any] | None = None,
    surface: str = "",
    component: str = "",
    stage: str = "",
    status: str = "",
    conversation_id: str = "",
    turn_id: str = "",
    operation_id: str = "",
    job_id: str = "",
    scan_id: str = "",
    parent_id: str = "",
    event_id: str = "",
    started_at: float | None = None,
    duration_ms: int | None = None,
) -> None:
    kwargs = {
        "kind": kind,
        "title": title,
        "payload": payload,
        "surface": surface,
        "component": component,
        "stage": stage,
        "status": status,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "operation_id": operation_id,
        "job_id": job_id,
        "scan_id": scan_id,
        "parent_id": parent_id,
        "event_id": event_id,
        "started_at": started_at,
        "duration_ms": duration_ms,
    }

    async def _run() -> None:
        await emit(**kwargs)
        await flush_outbox()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(target=lambda: asyncio.run(_run()), daemon=True).start()
        return
    loop.create_task(_run())
