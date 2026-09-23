from __future__ import annotations

import hashlib
import time
from typing import Any

from app.services.tenant_lock import tenant_file_lock
from app.state_store import read_json, write_json

TTL_SEC = 24 * 3600
MISMATCH = "این کلید تکرار با متن دیگری آمده است."


class Mismatch(Exception):
    pass


def body_stamp(raw: bytes) -> str:
    return hashlib.sha256(raw or b"").hexdigest()


def _store() -> dict:
    data = read_json("idempotency.json", {})
    return data if isinstance(data, dict) else {}


def get(scope: str, key: str, stamp: str = "") -> Any | None:
    token = str(key or "").strip()
    if not token:
        return None
    with tenant_file_lock("idempotency"):
        rows = _store()
        row = rows.get(f"{scope}:{token}")
        if not isinstance(row, dict):
            return None
        if float(row.get("at") or 0) < time.time() - TTL_SEC:
            return None
        if str(row.get("stamp") or "") != str(stamp or ""):
            raise Mismatch(MISMATCH)
        return row.get("payload")


def put(scope: str, key: str, payload: Any, stamp: str = "") -> None:
    token = str(key or "").strip()
    if not token:
        return
    with tenant_file_lock("idempotency"):
        rows = _store()
        cutoff = time.time() - TTL_SEC
        kept = {name: row for name, row in rows.items() if isinstance(row, dict) and float(row.get("at") or 0) >= cutoff}
        kept[f"{scope}:{token}"] = {"at": time.time(), "payload": payload, "stamp": str(stamp or "")}
        write_json("idempotency.json", kept)


def recall(scope: str, key: str, stamp: str) -> Any | None:
    try:
        return get(scope, key, stamp)
    except Mismatch as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, MISMATCH) from exc
