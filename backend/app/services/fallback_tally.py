from __future__ import annotations

import fcntl
import json
import time
from pathlib import Path

from app.config import settings
from app.services.pii_mask import mask_pii


def _path() -> Path:
    root = Path(settings.state_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "fallback-tally.json"


def _week() -> str:
    moment = time.gmtime()
    return f"{moment.tm_year}-W{int(time.strftime('%W', moment))}"


def note(kind: str, spoken: str) -> None:
    text = mask_pii(" ".join(str(spoken or "").split()))[:120]
    if not text:
        return
    path = _path()
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        week_key = _week()
        week = data.get(week_key) if isinstance(data.get(week_key), dict) else {}
        bucket = week.get(kind) if isinstance(week.get(kind), dict) else {}
        bucket[text] = int(bucket.get(text) or 0) + 1
        week[kind] = bucket
        data[week_key] = week
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def top(kind: str = "fallback", limit: int = 10) -> list[tuple[str, int]]:
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    week = data.get(_week()) if isinstance(data, dict) else {}
    bucket = week.get(kind) if isinstance(week, dict) else {}
    if not isinstance(bucket, dict):
        return []
    rows = sorted(((str(key), int(value)) for key, value in bucket.items()), key=lambda item: -item[1])
    return rows[:limit]
