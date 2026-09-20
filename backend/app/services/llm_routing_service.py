from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.services.observe_client import observe_base
from app.state_store import read_json, shared_lock, write_json

log = logging.getLogger("sozan.llm-routing")

SURFACES = ("shop", "shop-edit", "studio", "inbox", "voice", "factory", "image")
TTL_SEC = 30.0
STORE = "llm-routing.json"

_cache: dict[str, Any] = {"at": 0.0, "routes": {}, "providers": []}
_stale_emitted = False


def _persist(payload: dict) -> None:
    with shared_lock():
        write_json(STORE, payload, shared=True)


def _load_disk() -> dict:
    data = read_json(STORE, {}, shared=True)
    return data if isinstance(data, dict) else {}


def snapshot() -> dict:
    return {
        "routes": dict(_cache.get("routes") or {}),
        "providers": list(_cache.get("providers") or []),
        "at": float(_cache.get("at") or 0),
    }


def provider(ident: str) -> dict:
    wanted = str(ident or "").strip()
    if not wanted:
        return {}
    for row in _cache.get("providers") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == wanted:
            return row
    return {}


def get(surface: str) -> dict | None:
    _maybe_stale_load()
    row = (_cache.get("routes") or {}).get(str(surface or "").strip())
    return dict(row) if isinstance(row, dict) and row.get("model") else None


def _maybe_stale_load() -> None:
    if _cache.get("routes") or _cache.get("at"):
        return
    disk = _load_disk()
    if disk.get("routes"):
        _cache["routes"] = disk.get("routes") or {}
        _cache["providers"] = disk.get("providers") or []
        _cache["at"] = float(disk.get("at") or 0)


def apply_payload(payload: dict) -> None:
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    providers = payload.get("providers") if isinstance(payload.get("providers"), list) else []
    cleaned: dict[str, dict] = {}
    for name, row in routes.items():
        if name not in SURFACES or not isinstance(row, dict):
            continue
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        cleaned[name] = {
            "kind": str(row.get("kind") or "local").strip() or "local",
            "model": model,
            "provider": str(row.get("provider") or "").strip(),
            "base_url": str(row.get("base_url") or "").strip(),
        }
    kept_providers = []
    for row in providers:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or "").strip()
        if not ident:
            continue
        kept_providers.append(
            {
                "id": ident[:40],
                "kind": str(row.get("kind") or "openai-chat").strip(),
                "base_url": str(row.get("base_url") or "").strip(),
                "key_env": str(row.get("key_env") or "CLOUD_LLM_TOKEN").strip(),
                "label": str(row.get("label") or ident).strip()[:80],
                "model": str(row.get("model") or "").strip()[:80],
            }
        )
    _cache["routes"] = cleaned
    _cache["providers"] = kept_providers
    _cache["at"] = time.time()
    _persist({"routes": cleaned, "providers": kept_providers, "at": _cache["at"]})


async def refresh() -> bool:
    global _stale_emitted
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            res = await client.get(f"{observe_base()}/observe/api/routing")
        if res.status_code >= 400:
            raise RuntimeError(f"http-{res.status_code}")
        data = res.json()
        if not isinstance(data, dict):
            raise RuntimeError("bad-json")
        apply_payload(data)
        _stale_emitted = False
        return True
    except Exception as exc:
        _maybe_stale_load()
        log.warning("llm routing refresh failed: %s", type(exc).__name__)
        if not _stale_emitted:
            _stale_emitted = True
            from app.services.observe_client import emit_later

            emit_later(
                kind="routing",
                title="routing-stale",
                status="failed",
                payload={"error": type(exc).__name__},
            )
        return False


async def refresh_loop() -> None:
    await refresh()
    while True:
        import asyncio

        await asyncio.sleep(TTL_SEC)
        await refresh()
