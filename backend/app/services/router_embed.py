"""Safety net when the router model returns prose and no tool call.

The chat model still chooses the tool. This layer runs only after that choice
is empty: embed the user's sentence with Arvan BGE-M3 and compare it to the
precomputed intent bank. A score at or above the threshold runs that tool with
the user's sentence. A lower score leaves the model's prose in place.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import httpx

from app.services.llm import CLOUD_UA, route_for_surface
from app.services.llm import auth_scheme as _auth_scheme
from app.services.llm import emit_usage as _emit_usage
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.router.embed")

EMBED_MODEL = "Bge-m3"
EMBED_TIMEOUT = 8.0
# Sentence-to-sentence probe was 0.77 versus 0.46, but scores against this bank
# sit higher. Held-out checks: a real status/caption/shop/inbox line is at least
# 0.779, while سلام، جوک، and «کپشن قبلی را حذف کن» stay at or below 0.706.
INTENT_THRESHOLD = 0.75
INTENT_TOOLS = {
    "status": "status",
    "content": "studio_chat",
    "shop": "shop_chat",
    "inbox": "inbox_status",
}
_DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLES_PATH = _DATA / "router_intents.json"
VECTORS_PATH = _DATA / "router_intent_vectors.json"
_CACHE: dict | None = None


def clear_vectors_cache() -> None:
    global _CACHE
    _CACHE = None


def load_samples() -> dict[str, list[str]]:
    try:
        raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, rows in raw.items():
        if name not in INTENT_TOOLS or not isinstance(rows, list):
            continue
        texts = [str(item).strip() for item in rows if str(item).strip()]
        if texts:
            out[name] = texts
    return out


def load_vectors() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    loaded = _read_vectors()
    if loaded:
        _CACHE = loaded
    return loaded


def _read_vectors() -> dict:
    try:
        raw = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    intents = raw.get("intents") if isinstance(raw, dict) else None
    return intents if isinstance(intents, dict) else {}


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = 0.0
    norm_left = 0.0
    norm_right = 0.0
    for x, y in zip(left, right):
        dot += x * y
        norm_left += x * x
        norm_right += y * y
    if norm_left <= 0 or norm_right <= 0:
        return -1.0
    return dot / math.sqrt(norm_left * norm_right)


def intent_score(vector: list[float], row: dict) -> float:
    refs: list[list[float]] = []
    mean = row.get("mean")
    if isinstance(mean, list) and mean:
        refs.append(mean)
    for sample in row.get("samples") or []:
        if isinstance(sample, list) and sample:
            refs.append(sample)
    best = -1.0
    for ref in refs:
        best = max(best, cosine(vector, ref))
    return best


def pick_tool(vector: list[float], bank: dict, threshold: float = INTENT_THRESHOLD) -> tuple[str, float]:
    best_intent = ""
    best_score = -1.0
    for intent, row in bank.items():
        if intent not in INTENT_TOOLS or not isinstance(row, dict):
            continue
        score = intent_score(vector, row)
        if score > best_score:
            best_score = score
            best_intent = intent
    if not best_intent or best_score < threshold:
        return "", best_score
    return INTENT_TOOLS[best_intent], best_score


def mean_vector(rows: list[list[float]]) -> list[float]:
    if not rows:
        return []
    width = len(rows[0])
    if width < 2 or any(len(row) != width for row in rows):
        return []
    total = [0.0] * width
    for row in rows:
        for index, value in enumerate(row):
            total[index] += value
    count = float(len(rows))
    return [value / count for value in total]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    cleaned = [str(text or "").strip()[:2000] for text in texts]
    if not cleaned or any(not text for text in cleaned):
        raise RuntimeError("embed_empty")
    route = route_for_surface("router")
    if route.get("kind") != "cloud" or not route.get("url") or not route.get("token"):
        raise RuntimeError("embed_requires_cloud")
    body = {"model": EMBED_MODEL, "input": cleaned}
    headers = {"Content-Type": "application/json", "User-Agent": CLOUD_UA}
    scheme = _auth_scheme(route.get("auth"))
    headers["Authorization"] = f"{scheme} {route['token']}"
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT, trust_env=False, proxy=route.get("proxy")) as client:
        res = await client.post(f"{route['url'].rstrip('/')}/embeddings", json=body, headers=headers)
        res.raise_for_status()
        payload = res.json()
    _emit_usage(surface="router", model=EMBED_MODEL, payload=payload if isinstance(payload, dict) else {})
    return _vectors_from(payload, len(cleaned))


def _vectors_from(payload: object, count: int) -> list[list[float]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("embed_bad_json")
    ordered: list[list[float] | None] = [None] * count
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index") or 0)
        except (TypeError, ValueError):
            continue
        raw = item.get("embedding")
        if not isinstance(raw, list) or not (0 <= index < count):
            continue
        ordered[index] = [float(value) for value in raw]
    if any(row is None for row in ordered):
        raise RuntimeError("embed_incomplete")
    return [row for row in ordered if row is not None]


async def rescue_tool(
    text: str,
    *,
    embed=None,
    bank: dict | None = None,
    threshold: float | None = None,
) -> str:
    spoken = (text or "").strip()
    if not spoken:
        return ""
    vectors = bank if bank is not None else load_vectors()
    if not vectors:
        return ""
    limit = INTENT_THRESHOLD if threshold is None else threshold
    try:
        if embed is None:
            vector = (await embed_texts([spoken]))[0]
        else:
            vector = await embed(spoken)
    except Exception:
        log.warning("router embed skipped")
        emit_later(
            kind="llm",
            title="router-embed-fail",
            surface="router",
            status="error",
            payload={"error": "unreachable"},
        )
        return ""
    if not isinstance(vector, list) or len(vector) < 2:
        return ""
    tool, score = pick_tool([float(value) for value in vector], vectors, limit)
    if not tool:
        return ""
    emit_later(
        kind="llm",
        title="router-embed-rescue",
        surface="router",
        status="ok",
        payload={"tool": tool, "score": round(score, 3)},
    )
    return tool
