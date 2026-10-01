from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

log = logging.getLogger("sozan.state")
_tenant: ContextVar[str] = ContextVar("sozan_tenant", default="")
_shared_tls = threading.local()
_shared_process_lock = threading.RLock()

SHARED_FILES = frozenset({"profiles.json", "settings.json", "sendbox-pending.json"})
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
    "router-messages.json",
    "router-pending.json",
    "router-usage.json",
    "router-threads.json",
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
        log.warning("invalid tenant phone; refusing tenants/_none")
        raise


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


def _is_shared(name: str, shared: bool) -> bool:
    return shared or name in SHARED_FILES


@contextmanager
def shared_lock() -> Iterator[None]:
    depth = getattr(_shared_tls, "depth", 0)
    if depth == 0:
        _shared_process_lock.acquire()
        root = settings.state_path
        root.mkdir(parents=True, exist_ok=True)
        handle = (root / "_global.lock").open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            handle.close()
            _shared_process_lock.release()
            raise
        _shared_tls.handle = handle
    _shared_tls.depth = depth + 1
    try:
        yield
    finally:
        _shared_tls.depth -= 1
        if _shared_tls.depth == 0:
            handle = _shared_tls.handle
            _shared_tls.handle = None
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
                _shared_process_lock.release()


def _write_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json(name: str, default: Any, *, shared: bool = False) -> Any:
    path = _path(name, shared=shared)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("corrupt json %s; using default", path.name)
        return default


def write_json(name: str, payload: Any, *, shared: bool = False) -> None:
    path = _path(name, shared=shared)
    if _is_shared(name, shared):
        with shared_lock():
            _write_atomic(path, payload)
        return
    _write_atomic(path, payload)


def update_json(name: str, mutate, default: Any, *, lock: str) -> Any:
    """Read-modify-write one tenant file under its tenant_file_lock.

    Use this for any file more than one role writes (shop.json): a plain
    read_json + write_json loses whatever another writer saved in between.
    `mutate` changes the value in place or returns a replacement.
    """
    from app.services.tenant_lock import tenant_file_lock

    with tenant_file_lock(lock):
        value = read_json(name, default)
        if not isinstance(value, type(default)):
            value = default
        result = mutate(value)
        if result is not None:
            value = result
        write_json(name, value)
        return value

