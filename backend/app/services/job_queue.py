from __future__ import annotations

import json
import os
from uuid import uuid4

from app.redis_client import redis_client

QUEUE = "sozan:studio-jobs"


def enabled() -> bool:
    return os.environ.get("SOZAN_WORKER") == "1"


async def enqueue(payload: dict) -> str:
    job_id = str(uuid4())
    body = dict(payload)
    body["id"] = job_id
    await redis_client.lpush(QUEUE, json.dumps(body, ensure_ascii=False))
    return job_id


async def pop(timeout: int = 5) -> dict | None:
    item = await redis_client.brpop(QUEUE, timeout=timeout)
    if not item:
        return None
    raw = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else ""
    data = json.loads(raw or "{}")
    return data if isinstance(data, dict) else None
