from __future__ import annotations

import time
from typing import Any

from app.state_store import read_json, write_json

TTL_SEC = 24 * 3600


def _store() -> dict:
    data = read_json("idempotency.json", {})
    return data if isinstance(data, dict) else {}


def get(scope: str, key: str) -> Any | None:
    token = str(key or "").strip()
    if not token:
        return None
    rows = _store()
    row = rows.get(f"{scope}:{token}")
    if not isinstance(row, dict):
        return None
    if float(row.get("at") or 0) < time.time() - TTL_SEC:
        return None
    return row.get("payload")


def put(scope: str, key: str, payload: Any) -> None:
    token = str(key or "").strip()
    if not token:
        return
    rows = _store()
    cutoff = time.time() - TTL_SEC
    kept = {name: row for name, row in rows.items() if isinstance(row, dict) and float(row.get("at") or 0) >= cutoff}
    kept[f"{scope}:{token}"] = {"at": time.time(), "payload": payload}
    write_json("idempotency.json", kept)
