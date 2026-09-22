"""Rebuild the router intent vectors with Arvan BGE-M3. Prints scores only."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.router_embed import (  # noqa: E402
    EMBED_MODEL,
    SAMPLES_PATH,
    VECTORS_PATH,
    clear_vectors_cache,
    embed_texts,
    intent_score,
    load_samples,
    mean_vector,
)


def _round(row: list[float]) -> list[float]:
    return [round(value, 5) for value in row]


async def _embed_all(texts: list[str]) -> list[list[float]]:
    try:
        return await embed_texts(texts)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {400, 413, 422}:
            raise
    rows: list[list[float]] = []
    for text in texts:
        rows.extend(await embed_texts([text]))
    return rows


async def main() -> None:
    samples = load_samples()
    if len(samples) != 4 or any(not (10 <= len(rows) <= 20) for rows in samples.values()):
        raise SystemExit("intent bank must have 4 intents of 10 to 20 sentences")
    flat: list[tuple[str, str]] = []
    for intent, rows in samples.items():
        for text in rows:
            flat.append((intent, text))
    vectors = await _embed_all([text for _, text in flat])
    if len(vectors) != len(flat):
        raise SystemExit("embedding count mismatch")
    grouped: dict[str, list[list[float]]] = {name: [] for name in samples}
    for (intent, _), vector in zip(flat, vectors):
        grouped[intent].append(vector)
    intents = {
        name: {"mean": _round(mean_vector(rows)), "samples": [_round(row) for row in rows]}
        for name, rows in grouped.items()
    }
    VECTORS_PATH.write_text(
        json.dumps({"model": EMBED_MODEL, "dim": len(vectors[0]), "intents": intents}, ensure_ascii=False),
        encoding="utf-8",
    )
    clear_vectors_cache()
    heldout = {
        "status": "وضعیت مغازه را خلاصه کن",
        "content": "یه متن تبلیغ برای کفش بده بدون عکس",
        "shop": "رنگ دکمه را آبی کن",
        "inbox": "چند دایرکت نخوانده دارم",
        "greeting": "سلام",
        "delete_caption": "کپشن قبلی را حذف کن",
    }
    probes = await _embed_all(list(heldout.values()))
    print(f"wrote {VECTORS_PATH.name} dim={len(vectors[0])} sentences={len(flat)} from {SAMPLES_PATH.name}")
    for (label, _), vector in zip(heldout.items(), probes):
        scores = {name: round(intent_score(vector, row), 3) for name, row in intents.items()}
        winner = max(scores, key=scores.get)
        print(f"{label}\twinner={winner}\t{scores}")


if __name__ == "__main__":
    asyncio.run(main())
