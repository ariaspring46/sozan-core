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
_OUTBOX_KEEP_ROWS = 1600  # after a trim: room for ~400 appends before the next rewrite
_OUTBOX_MAX_BYTES = 2_000_000
_OUTBOX_COOLDOWN = 30.0
_flush_cooldown_until = 0.0
_outbox_lock = threading.Lock()
_outbox_rows: dict[str, int] = {}
_dropped_pending = 0


def _read_lines(path: Any) -> list[str]:
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_lines(path: Any, lines: list[str]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    tmp.replace(path)
    _outbox_rows[str(path)] = len(lines)


def _append_outbox(body: dict[str, Any]) -> None:
    """One cheap append. The file is rewritten only when it passes the cap, and
    then down to 80%, so a long tunnel outage costs O(1) per event, not O(n).
    It never emits an event itself: the drop count is reported after the next
    successful flush (an event here would be queued here again, forever)."""
    global _dropped_pending
    row = dict(body)
    row.setdefault("queuedAt", time.time())
    row.setdefault("attempts", 0)
    line = json.dumps(row, ensure_ascii=False)
    try:
        with _outbox_lock:
            path = outbox_path()
            key = str(path)
            if key not in _outbox_rows:
                _outbox_rows[key] = len(_read_lines(path))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            _outbox_rows[key] += 1
            if _outbox_rows[key] > _OUTBOX_MAX_ROWS or path.stat().st_size > _OUTBOX_MAX_BYTES:
                lines = _read_lines(path)
                keep = lines[-_OUTBOX_KEEP_ROWS:]
                _dropped_pending += len(lines) - len(keep)
                _write_lines(path, keep)
    except Exception:
        pass


def _rewrite_outbox(rows: list[dict[str, Any]]) -> None:
    with _outbox_lock:
        _write_lines(outbox_path(), [json.dumps(row, ensure_ascii=False) for row in rows])


def load_outbox() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in _read_lines(outbox_path()):
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
    """Send up to `limit` queued events. Rows appended while we were sending stay."""
    global _flush_cooldown_until, _dropped_pending
    if time.time() < _flush_cooldown_until:
        return 0
    with _outbox_lock:
        lines = _read_lines(outbox_path())
    if not lines:
        return 0
    done: set[str] = set()
    sent = 0
    for line in lines[:limit]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            done.add(line)  # garbage is not worth retrying
            continue
        if not isinstance(row, dict) or ("dropped" in row and len(row) <= 2):
            done.add(line)
            continue
        if await _post_event(row):
            sent += 1
            done.add(line)
    if done:
        with _outbox_lock:
            path = outbox_path()
            _write_lines(path, [item for item in _read_lines(path) if item not in done])
    if sent == 0 and len(done) < len(lines):
        # تونل قطع است؛ ۳۰ ثانیه دوباره فایل را باز نکن.
        _flush_cooldown_until = time.time() + _OUTBOX_COOLDOWN
    if sent and _dropped_pending:
        count, _dropped_pending = _dropped_pending, 0
        await emit(
            kind="observe",
            title="observe-outbox-dropped",
            surface="observe",
            status="error",
            payload={"dropped": count},
        )
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
