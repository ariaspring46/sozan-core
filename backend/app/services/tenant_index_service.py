"""Shared tenant index: slug / order id / Sendbox account → phone.

Public lookups (storefront checkout, order status, DM webhooks) must not open
every tenant folder on every request. Writers keep the index fresh
(`upsert`), startup builds it once (`build_all`), and a lookup that misses may
trigger a full rescan — but never more than one per REBUILD_MIN_GAP seconds, so
a caller who invents slugs cannot turn each request into a disk scan.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.state_store import iter_tenants, read_json, shared_lock, tenant_scope, write_json

INDEX_FILE = "tenant-index.json"
KINDS = ("slug", "order", "sendbox")
REBUILD_MIN_GAP = 15.0
_scan_lock = threading.Lock()


def _empty() -> dict:
    return {"slug": {}, "order": {}, "sendbox": {}, "builtAt": 0}


def load() -> dict:
    data = read_json(INDEX_FILE, {}, shared=True)
    if not isinstance(data, dict):
        return _empty()
    for kind in KINDS:
        if not isinstance(data.get(kind), dict):
            data[kind] = {}
    return data


def _save(data: dict) -> None:
    write_json(INDEX_FILE, data, shared=True)


def rebuild(all_rows: list[tuple[str, dict]]) -> dict:
    """Full rebuild from (phone, {shop, orderIds, sendboxIds}) pairs."""
    data = _empty()
    for phone, extras in all_rows:
        shop = extras.get("shop") if isinstance(extras.get("shop"), dict) else {}
        slug = str(shop.get("slug") or "").strip()
        if slug:
            data["slug"][slug] = phone
        for oid in extras.get("orderIds") or []:
            if str(oid).strip():
                data["order"][str(oid)] = phone
        for acc in extras.get("sendboxIds") or []:
            if str(acc).strip():
                data["sendbox"][str(acc)] = phone
    data["builtAt"] = time.time()
    with shared_lock():
        _save(data)
    return data


def scan_all() -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for phone in iter_tenants():
        with tenant_scope(phone):
            shop = read_json("shop.json", {})
            orders = read_json("pay-orders.json", [])
            channels = read_json("channels.json", [])
        order_ids = [str(r.get("id") or "") for r in orders if isinstance(r, dict)] if isinstance(orders, list) else []
        sendbox_ids = []
        for row in channels if isinstance(channels, list) else []:
            creds = row.get("credentials") if isinstance(row, dict) else None
            if isinstance(creds, dict) and str(creds.get("sendboxAccountId") or "").strip():
                sendbox_ids.append(str(creds["sendboxAccountId"]).strip())
        rows.append((phone, {"shop": shop if isinstance(shop, dict) else {}, "orderIds": order_ids, "sendboxIds": sendbox_ids}))
    return rows


def build_all() -> dict:
    return rebuild(scan_all())


def slug_owner(index: dict, slug: str) -> str | None:
    return index.get("slug", {}).get(str(slug or "").strip())


def order_owner(index: dict, order_id: str) -> str | None:
    return index.get("order", {}).get(str(order_id or "").strip())


def sendbox_owner(index: dict, account_id: str) -> str | None:
    return index.get("sendbox", {}).get(str(account_id or "").strip())


def upsert(*, phone: str, slug: str = "", order_id: str = "", sendbox_id: str = "") -> None:
    """Record a fresh fact. Never raises: the index heals itself on a miss."""
    wanted = {"slug": str(slug).strip(), "order": str(order_id).strip(), "sendbox": str(sendbox_id).strip()}
    wanted = {kind: key for kind, key in wanted.items() if key}
    if not wanted or not phone:
        return
    try:
        with shared_lock():
            data = load()
            changed = False
            for kind, key in wanted.items():
                if data[kind].get(key) != phone:
                    data[kind][key] = phone
                    changed = True
            if changed:
                _save(data)
    except Exception:
        pass


def _can_rescan(data: dict) -> bool:
    return time.time() - float(data.get("builtAt") or 0) >= REBUILD_MIN_GAP


def lookup(kind: str, key: str, verify: Callable[[str], bool]) -> str | None:
    """Phone that owns `key`, or None. `verify` checks the tenant's own file."""
    wanted = str(key or "").strip()
    if not wanted or kind not in KINDS:
        return None
    data = load()
    phone = data[kind].get(wanted)
    if phone and verify(phone):
        return phone
    if not _can_rescan(data):
        return None
    with _scan_lock:
        data = load()
        if _can_rescan(data):
            data = build_all()
    phone = data[kind].get(wanted)
    return phone if phone and verify(phone) else None
