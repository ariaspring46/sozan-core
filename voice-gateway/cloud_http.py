"""Kept-alive HTTPS connections to the cloud: a new TLS handshake costs round trips on every model and voice call."""

from __future__ import annotations

import http.client
import io
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_POOL_LOCK = threading.Lock()
_POOL: dict[tuple[str, str], list[tuple[http.client.HTTPConnection, float]]] = {}
_POOL_IDLE_S = 30.0
_POOL_MAX = 4


def _checkout(scheme: str, host: str, timeout: float, fresh: bool = False) -> tuple[http.client.HTTPConnection, bool]:
    """A kept-alive connection to the host, else a new one: a new TLS handshake costs round trips on every call."""
    with _POOL_LOCK:
        idle = [] if fresh else _POOL.get((scheme, host), [])
        while idle:
            conn, since = idle.pop()
            if time.monotonic() - since < _POOL_IDLE_S and conn.sock is not None:
                try:
                    conn.sock.settimeout(timeout)
                    return conn, True
                except OSError:
                    pass
            conn.close()
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return cls(host, timeout=timeout), False


def _checkin(scheme: str, host: str, conn: http.client.HTTPConnection) -> None:
    with _POOL_LOCK:
        idle = _POOL.setdefault((scheme, host), [])
        if len(idle) < _POOL_MAX:
            idle.append((conn, time.monotonic()))
            return
    conn.close()


class _KeptResponse:
    """The connection goes back to the pool only when its body was read to the end."""

    def __init__(self, conn: http.client.HTTPConnection, resp, scheme: str, host: str) -> None:
        self._conn, self._resp, self._key = conn, resp, (scheme, host)
        self.headers = resp.headers

    def read(self, amount: int = -1) -> bytes:
        return self._resp.read() if amount < 0 else self._resp.read(amount)

    def close(self) -> None:
        resp, conn = self._resp, self._conn
        if resp is None:
            return
        self._resp = None
        if not resp.isclosed() and not resp.will_close and conn.sock is not None:
            # A stream ends with a short tail after [DONE]; read it so the socket is free again.
            conn.sock.settimeout(0.5)
            try:
                resp.read(4096)
            except (OSError, http.client.HTTPException):
                pass
        if resp.isclosed() and not resp.will_close:
            _checkin(*self._key, conn)
        else:
            conn.close()
        resp.close()

    def __enter__(self) -> "_KeptResponse":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def pooled_open(req: urllib.request.Request, timeout: float) -> _KeptResponse:
    """Like urlopen for the cloud (no proxy), reusing the TLS connection. A stale kept-alive socket is retried once, fresh."""
    parts = urllib.parse.urlsplit(req.full_url)
    scheme, host = parts.scheme, parts.netloc
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    headers = dict(req.header_items())

    def send(conn: http.client.HTTPConnection):
        conn.request(req.get_method(), path, body=req.data, headers=headers)
        return conn.getresponse()

    conn, reused = _checkout(scheme, host, timeout)
    try:
        resp = send(conn)
    except (OSError, http.client.HTTPException):
        conn.close()
        if not reused:
            raise
        conn, _ = _checkout(scheme, host, timeout, fresh=True)
        resp = send(conn)
    if resp.status >= 400:
        payload = resp.read()
        if resp.will_close:
            conn.close()
        else:
            _checkin(scheme, host, conn)
        raise urllib.error.HTTPError(req.full_url, resp.status, resp.reason, resp.headers, io.BytesIO(payload))
    return _KeptResponse(conn, resp, scheme, host)


def warm_connection(url: str, timeout: float = 10.0) -> None:
    """Open the TLS connection while the phone rings, so the first model turn skips the handshake."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        return
    conn, _ = _checkout(parts.scheme, parts.netloc, timeout)
    try:
        if conn.sock is None:
            conn.connect()
    except OSError:
        conn.close()
        return
    _checkin(parts.scheme, parts.netloc, conn)
