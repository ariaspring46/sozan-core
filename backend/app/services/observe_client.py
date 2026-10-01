from __future__ import annotations

import asyncio
import contextvars
import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.config import settings
from app.services.pipeline_release import BEHAVIOR_VERSION, envelope, hub_release_id
from app.state_store import current_tenant, tenant_dir

log = logging.getLogger("sozan.observe")


def observe_base() -> str:
    url = settings.local_llm_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url.rstrip("/")


OBSERVE_TEXT_LIMIT = 400


def safe_text(value: object, limit: int = OBSERVE_TEXT_LIMIT) -> str:
    """Seller or prompt text bound for observe: PII masked and trimmed (monitoring-plan rule 1)."""
    from app.services.pii_mask import mask_pii

    return mask_pii(str(value or ""))[:limit]


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


# Test runs set SOZAN_OBSERVE_OUTBOX=0: background emit threads otherwise write into a test's
# temp state dir while it is being removed (the "Directory not empty" flakes).
OUTBOX_ENABLED = os.environ.get("SOZAN_OBSERVE_OUTBOX", "1").strip() != "0"
_OUTBOX_MAX_ROWS = 2000
_OUTBOX_COOLDOWN = 30.0
_flush_cooldown_until = 0.0
_outbox_lock = threading.Lock()


@contextmanager
def _outbox_guard(path: Path) -> Iterator[None]:
    """Threads in this process and other processes (worker) both append here."""
    with _outbox_lock:
        handle = path.with_name(path.name + ".lock").open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Append under the lock; past the cap the oldest rows go and one marker counts them.

    Never emits an event: an event about a full queue would land in the same full
    queue while observe is down and feed itself forever.
    """
    with _outbox_guard(path):
        if rows:
            with path.open("a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _OUTBOX_MAX_ROWS:
            return
        dropped = 0
        body: list[str] = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue
            if isinstance(item, dict) and set(item) <= {"dropped", "queuedAt"} and "dropped" in item:
                dropped += int(item.get("dropped") or 0)
                continue
            body.append(line)
        over = max(0, len(body) - (_OUTBOX_MAX_ROWS - 1))
        dropped += over
        body = body[over:]
        marker = json.dumps({"dropped": dropped, "queuedAt": time.time()})
        _write_lines(path, [marker, *body])
    log.warning("observe outbox full; %s oldest events dropped so far", dropped)


def _write_lines(path: Path, lines: list[str]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))
    os.replace(tmp, path)


def _append_outbox(body: dict[str, Any]) -> None:
    if not OUTBOX_ENABLED:
        return
    row = dict(body)
    row.setdefault("queuedAt", time.time())
    row.setdefault("attempts", 0)
    try:
        _append_rows(outbox_path(), [row])
    except Exception:
        log.warning("observe outbox append failed", exc_info=True)


def _rewrite_outbox(rows: list[dict[str, Any]]) -> None:
    path = outbox_path()
    with _outbox_guard(path):
        _write_lines(path, [json.dumps(row, ensure_ascii=False) for row in rows])


def _read_rows(path: Path) -> list[dict[str, Any]]:
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


def load_outbox() -> list[dict[str, Any]]:
    return _read_rows(outbox_path())


async def _post_event(body: dict[str, Any]) -> bool:
    try:
        async with httpx.AsyncClient(timeout=0.8, trust_env=False) as client:
            response = await client.post(f"{observe_base()}/sozan/events", json=body)
            return response.status_code < 400
    except Exception:
        return False


async def flush_outbox(limit: int = 40) -> int:
    """Take the file away atomically, send it, append back what failed.

    Rows appended while this awaits go to a fresh file and are never overwritten.
    """
    global _flush_cooldown_until
    if not OUTBOX_ENABLED or time.time() < _flush_cooldown_until:
        return 0
    path = outbox_path()
    if not path.is_file():
        return 0
    taken = path.with_name(f"{path.name}.{uuid4().hex[:8]}.sending")
    with _outbox_guard(path):
        if not path.is_file():
            return 0
        os.replace(path, taken)
    rows = _read_rows(taken)
    kept: list[dict[str, Any]] = []
    sent = 0
    for index, row in enumerate(rows):
        if index >= limit or "eventId" not in row and "dropped" in row:
            kept.append(row)
            continue
        ok = await _post_event(row)
        if ok:
            sent += 1
            continue
        row["attempts"] = int(row.get("attempts") or 0) + 1
        kept.append(row)
    if kept:
        # Older rows go back first so order stays roughly oldest-first.
        with _outbox_guard(path):
            fresh = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            _write_lines(path, [json.dumps(row, ensure_ascii=False) for row in kept] + fresh)
        _append_rows(path, [])  # re-apply the cap after putting failed rows back
    taken.unlink(missing_ok=True)
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
        # A bare Thread starts with an empty context; copy it so the tenant stays on the event.
        ctx = contextvars.copy_context()
        threading.Thread(target=lambda: ctx.run(asyncio.run, _run()), daemon=True).start()
        return
    loop.create_task(_run())
