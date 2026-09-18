from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

_tenant: ContextVar[str] = ContextVar("sozan_tenant", default="")

SHARED_FILES = frozenset({"profiles.json", "settings.json"})
TENANT_JSON = (
    "products.json",
    "sales.json",
    "channels.json",
    "shop.json",
    "shop-messages.json",
    "shop-brief.json",
    "voice.json",
    "channel-scan.json",
    "scan-status.json",
    "inbox.json",
    "studio-messages.json",
    "ig-seen.json",
    "unipile-seen.json",
    "sendbox-seen.json",
    "sendbox-posts.json",
    "tg-seen.json",
    "telegram-offset.json",
    "sites.json",
    "campaign-ids.json",
    "integrations.json",
    "plan.json",
    "billing.json",
    "wallet.json",
    "wallet-ledger.json",
    "pay-orders.json",
    "sms-usage.json",
    "withdrawals.json",
)


def iter_tenants() -> list[str]:
    root = settings.state_path / "tenants"
    if not root.is_dir():
        return []
    names = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and path.name and path.name != "_none":
            names.append(path.name)
    return names


def current_tenant() -> str:
    return _tenant.get()


def set_tenant(phone: str) -> Token:
    from app.phone import normalize_phone

    try:
        return _tenant.set(normalize_phone(phone))
    except ValueError:
        return _tenant.set("")


def reset_tenant(token: Token) -> None:
    _tenant.reset(token)


@contextmanager
def tenant_scope(phone: str) -> Iterator[None]:
    token = set_tenant(phone)
    try:
        yield
    finally:
        reset_tenant(token)


def tenant_dir() -> Path:
    phone = current_tenant()
    path = settings.state_path / "tenants" / (phone or "_none")
    path.mkdir(parents=True, exist_ok=True)
    return path


def brand_dir() -> Path:
    path = tenant_dir() / "brand"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(name: str, *, shared: bool = False) -> Path:
    if shared or name in SHARED_FILES:
        root = settings.state_path
        root.mkdir(parents=True, exist_ok=True)
        return root / name
    return tenant_dir() / name


def read_json(name: str, default: Any, *, shared: bool = False) -> Any:
    path = _path(name, shared=shared)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(name: str, payload: Any, *, shared: bool = False) -> None:
    path = _path(name, shared=shared)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
