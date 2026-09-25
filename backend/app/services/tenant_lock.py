from __future__ import annotations

import asyncio
import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.state_store import current_tenant, tenant_dir

_guard = threading.Lock()
_depth: dict[tuple, int] = {}


def lock_path(name: str = "shop") -> Path:
    path = tenant_dir() / f".lock-{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _owner() -> tuple:
    task_id = 0
    try:
        task = asyncio.current_task()
        if task is not None:
            task_id = id(task)
    except RuntimeError:
        task_id = 0
    return (threading.get_ident(), task_id)


@contextmanager
def tenant_file_lock(name: str = "shop") -> Iterator[None]:
    key = (*_owner(), name)
    with _guard:
        depth = _depth.get(key, 0)
        if depth:
            _depth[key] = depth + 1
            reenter = True
        else:
            _depth[key] = 1
            reenter = False
    if reenter:
        try:
            yield
        finally:
            with _guard:
                left = _depth.get(key, 1) - 1
                if left <= 0:
                    _depth.pop(key, None)
                else:
                    _depth[key] = left
        return
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
        with _guard:
            _depth.pop(key, None)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
