"""Shared tenant index: slug → phone and orderId → phone, so public lookups
don't walk every tenant folder on every request. Built once at startup, kept
fresh on writes, and repaired by a full scan when a row proves stale."""

from __future__ import annotations

import time

from app.state_store import read_json, shared_lock, write_json

INDEX_FILE = "tenant-index.json"


def _empty() -> dict:
    return {"slug": {}, "order": {}, "sendbox": {}, "builtAt": 0}


def load() -> dict:
    data = read_json(INDEX_FILE, {}, shared=True)
    return data if isinstance(data, dict) and isinstance(data.get("slug"), dict) else _empty()


def _save(data: dict) -> None:
    write_json(INDEX_FILE, data, shared=True)


def rebuild(all_rows: list[tuple[str, dict]]) -> dict:
    """Full rebuild from (phone, {shop, orders}) pairs."""
    data = _empty()
    for phone, extras in all_rows:
        shop = extras.get("shop") or {}
        slug = str(shop.get("slug") or "").strip()
        if slug:
            data["slug"][slug] = phone
        for oid in extras.get("orderIds") or []:
            data["order"][str(oid)] = phone
        for acc in extras.get("sendboxIds") or []:
            data["sendbox"][str(acc)] = phone
    data["builtAt"] = time.time()
    _save(data)
    return data


def slug_owner(index: dict, slug: str) -> str | None:
    return index.get("slug", {}).get(str(slug or "").strip())


def order_owner(index: dict, order_id: str) -> str | None:
    return index.get("order", {}).get(str(order_id or "").strip())


def sendbox_owner(index: dict, account_id: str) -> str | None:
    return index.get("sendbox", {}).get(str(account_id or "").strip())


def upsert(data: dict, *, slug: str = "", order_id: str = "", sendbox_id: str = "", phone: str) -> None:
    if slug:
        data.setdefault("slug", {})[str(slug).strip()] = phone
    if order_id:
        data.setdefault("order", {})[str(order_id).strip()] = phone
    if sendbox_id:
        data.setdefault("sendbox", {})[str(sendbox_id).strip()] = phone
    _save(data)
