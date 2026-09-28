"""One Chroma database per shop. The database name is a hash, never the phone.

Prices, stock, and order status are stored here only as a retrieval hint.
The reply must still read those numbers live from products and orders.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import nullcontext
from typing import Any

import httpx

from app.state_store import current_tenant

COLLECTIONS = (
    "catalog",
    "product_images",
    "policies",
    "answers",
    "customers",
    "conversations",
    "content",
    "outcomes",
)


def memory_key(phone: str | None = None) -> str:
    raw = (phone if phone is not None else current_tenant() or "").strip()
    if not raw or raw == "_none":
        raise RuntimeError("shop_memory_requires_tenant")
    return hashlib.sha256(f"sozan-memory-v1\n{raw}".encode()).hexdigest()[:32]


class MemoryBackend:
    """In-process stand-in used by tests and when the Chroma URL is unset."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict[str, dict]]] = {}

    def upsert(self, key: str, collection: str, rows: list[dict]) -> None:
        bucket = self.docs.setdefault(key, {}).setdefault(collection, {})
        for row in rows:
            doc_id = str(row.get("id") or "").strip()
            if not doc_id:
                continue
            bucket[doc_id] = {
                "id": doc_id,
                "document": str(row.get("document") or ""),
                "metadata": dict(row.get("metadata") or {}),
            }

    def search(self, key: str, collection: str, query: str, limit: int = 5) -> list[dict]:
        bucket = self.docs.get(key, {}).get(collection, {})
        needles = [part for part in query.split() if part]
        scored = []
        for row in bucket.values():
            text = row["document"]
            score = sum(1 for part in needles if part and part in text)
            if not needles or score:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _score, row in scored[:limit]]

    def delete_shop(self, key: str) -> None:
        self.docs.pop(key, None)

    def export_shop(self, key: str) -> dict:
        return {name: list(rows.values()) for name, rows in self.docs.get(key, {}).items()}


class ChromaHttp:
    """Chroma v2 on 127.0.0.1. The token stays in the process environment."""

    def __init__(self, base_url: str, token: str = "", tenant: str = "default_tenant", client: httpx.Client | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.tenant = tenant
        self._client = client

    def _open(self):
        if self._client is not None:
            return nullcontext(self._client)
        return httpx.Client(timeout=10, trust_env=False)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _db(self, key: str) -> str:
        return f"{self.base}/api/v2/tenants/{self.tenant}/databases/{key}"

    def upsert(self, key: str, collection: str, rows: list[dict]) -> None:
        if collection not in COLLECTIONS or not rows:
            return
        with self._open() as client:
            client.post(f"{self.base}/api/v2/tenants/{self.tenant}/databases", json={"name": key}, headers=self._headers())
            created = client.post(
                f"{self._db(key)}/collections",
                json={"name": collection, "get_or_create": True},
                headers=self._headers(),
            )
            created.raise_for_status()
            body = created.json()
            cid = str(body.get("id") or collection)
            client.post(
                f"{self._db(key)}/collections/{cid}/upsert",
                json={
                    "ids": [str(row["id"]) for row in rows],
                    "documents": [str(row.get("document") or "") for row in rows],
                    "metadatas": [dict(row.get("metadata") or {}) for row in rows],
                },
                headers=self._headers(),
            ).raise_for_status()

    def search(self, key: str, collection: str, query: str, limit: int = 5) -> list[dict]:
        with self._open() as client:
            found = client.get(f"{self._db(key)}/collections/{collection}", headers=self._headers())
            if found.status_code == 404:
                return []
            found.raise_for_status()
            cid = str((found.json() or {}).get("id") or collection)
            res = client.post(
                f"{self._db(key)}/collections/{cid}/query",
                json={"query_texts": [query], "n_results": limit, "include": ["documents", "metadatas"]},
                headers=self._headers(),
            )
            res.raise_for_status()
            payload = res.json()
        ids = ((payload.get("ids") or [[]])[0]) if isinstance(payload, dict) else []
        docs = ((payload.get("documents") or [[]])[0]) if isinstance(payload, dict) else []
        metas = ((payload.get("metadatas") or [[]])[0]) if isinstance(payload, dict) else []
        out = []
        for index, doc_id in enumerate(ids):
            out.append(
                {
                    "id": doc_id,
                    "document": docs[index] if index < len(docs) else "",
                    "metadata": metas[index] if index < len(metas) and isinstance(metas[index], dict) else {},
                }
            )
        return out

    def delete_shop(self, key: str) -> None:
        with self._open() as client:
            client.delete(self._db(key), headers=self._headers())

    def export_shop(self, key: str) -> dict:
        out: dict[str, list] = {}
        with self._open() as client:
            for name in COLLECTIONS:
                found = client.get(f"{self._db(key)}/collections/{name}", headers=self._headers())
                if found.status_code == 404:
                    continue
                found.raise_for_status()
                cid = str((found.json() or {}).get("id") or name)
                got = client.post(
                    f"{self._db(key)}/collections/{cid}/get",
                    json={"include": ["documents", "metadatas"]},
                    headers=self._headers(),
                )
                got.raise_for_status()
                payload = got.json() if got.content else {}
                ids = payload.get("ids") or []
                docs = payload.get("documents") or []
                metas = payload.get("metadatas") or []
                out[name] = [
                    {
                        "id": ids[index],
                        "document": docs[index] if index < len(docs) else "",
                        "metadata": metas[index] if index < len(metas) and isinstance(metas[index], dict) else {},
                    }
                    for index in range(len(ids))
                ]
        return out


_MEMORY = MemoryBackend()


def backend() -> Any:
    url = os.environ.get("SOZAN_CHROMA_URL", "").strip()
    if not url:
        return _MEMORY
    return ChromaHttp(url, token=os.environ.get("SOZAN_CHROMA_TOKEN", "").strip())


def upsert(collection: str, rows: list[dict], *, phone: str | None = None) -> str:
    key = memory_key(phone)
    backend().upsert(key, collection, rows)
    return key


def search(collection: str, query: str, *, limit: int = 5, phone: str | None = None) -> list[dict]:
    return backend().search(memory_key(phone), collection, query, limit)


def delete_shop(*, phone: str | None = None) -> None:
    backend().delete_shop(memory_key(phone))


def export_shop(*, phone: str | None = None) -> dict:
    return backend().export_shop(memory_key(phone))


def catalog_rows(products: list[dict]) -> list[dict]:
    rows = []
    for item in products:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "id": str(item.get("id") or item.get("sku") or title),
                "document": " ".join(
                    [
                        title,
                        str(item.get("description") or ""),
                        str(item.get("price") or ""),
                        str(item.get("stock") if item.get("stock") is not None else ""),
                    ]
                ).strip(),
                "metadata": {"sku": str(item.get("sku") or ""), "title": title},
            }
        )
    return rows


def match_image(*_args, **_kwargs) -> list[dict]:
    """No image match until product image vectors are stored. An empty list is not a guess."""
    return []


def backfill_catalog(products: list[dict], *, phone: str | None = None) -> int:
    rows = catalog_rows(products)
    if rows:
        upsert("catalog", rows, phone=phone)
    return len(rows)

