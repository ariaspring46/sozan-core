from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.state_store import current_tenant, tenant_dir


def lock_path(name: str = "shop") -> Path:
    path = tenant_dir() / f".lock-{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def tenant_file_lock(name: str = "shop") -> Iterator[None]:
    path = lock_path(name)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        handle.truncate()
        handle.write(current_tenant() or "_none")
        handle.flush()
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
