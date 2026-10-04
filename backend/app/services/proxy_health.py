"""A proxy that stops connecting costs a few seconds once, not the full timeout of every AI call.

OPENROUTER_PROXY is an SSH tunnel from another machine. When that machine or its VPN drops, the tunnel still accepts
the TCP connection but never answers, and each call waited the whole primary timeout (10 s) before the Arvan
fallback. The hub's own IP is refused by OpenRouter only some of the time (403), so the two paths cover each other:

- through the tunnel, connecting gets CONNECT_TIMEOUT;
- if it does not connect, the same request goes direct; when direct answers, the tunnel is skipped for DOWN_SECONDS;
- if direct is refused too (403 or no connection), the tunnel gets one more try (it often flaps rather than dies);
- while the tunnel is skipped, a refused direct call clears that and goes back to the tunnel.

Only requests that never reached a server are sent again, so a reply is never generated twice.
"""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("sozan.proxy")

CONNECT_TIMEOUT = 4.0
DIRECT_CONNECT_TIMEOUT = 4.0
DOWN_SECONDS = 300.0
REFUSED = frozenset({403})

_down_until: dict[str, float] = {}


def live(proxy: str | None) -> str | None:
    """The proxy to use now: None while it is skipped."""
    if not proxy:
        return None
    if _down_until.get(proxy, 0.0) > time.monotonic():
        return None
    return proxy


def mark_down(proxy: str | None) -> None:
    if proxy and live(proxy):
        log.warning("proxy did not connect and direct works; direct for %ds", int(DOWN_SECONDS))
    if proxy:
        _down_until[proxy] = time.monotonic() + DOWN_SECONDS


def mark_up(proxy: str | None) -> None:
    if proxy and _down_until.pop(proxy, None) is not None:
        log.warning("direct refused; back to the proxy")


def connect_failed(exc: BaseException) -> bool:
    """The request never reached the server, so sending it again cannot run it twice."""
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError))


def timeout(total: float, proxy: str | None, *, connect: float | None = None) -> float | httpx.Timeout:
    """Through a proxy, connecting gets CONNECT_TIMEOUT; direct keeps the caller's connect limit (None = total)."""
    if proxy:
        return httpx.Timeout(total, connect=min(float(total), CONNECT_TIMEOUT))
    if connect is None:
        return total
    return httpx.Timeout(total, connect=min(float(total), connect))


def _limit(total: float, via: str | None, *, proxy: str | None, connect: float | None) -> float | httpx.Timeout:
    if via:
        return timeout(total, via)
    if proxy:  # the direct stand-in for a proxy that did not connect: it must not hang either
        return timeout(total, None, connect=connect or DIRECT_CONNECT_TIMEOUT)
    return timeout(total, None, connect=connect)


def _refused(res: httpx.Response | None) -> bool:
    return res is None or res.status_code in REFUSED


async def post(url: str, *, proxy: str | None, total: float, connect: float | None = None, **kwargs) -> httpx.Response:
    async def send(via: str | None) -> httpx.Response:
        limit = _limit(total, via, proxy=proxy, connect=connect)
        async with httpx.AsyncClient(timeout=limit, trust_env=False, proxy=via) as client:
            return await client.post(url, **kwargs)

    async def direct() -> httpx.Response | None:
        try:
            return await send(None)
        except Exception as exc:
            if connect_failed(exc):
                return None
            raise

    if not proxy:
        return await send(None)
    if live(proxy):
        try:
            return await send(proxy)
        except Exception as exc:
            if not connect_failed(exc):
                raise
        res = await direct()
        if not _refused(res):
            mark_down(proxy)
            return res
        return await send(proxy)
    res = await direct()
    if not _refused(res):
        return res
    mark_up(proxy)
    return await send(proxy)


def post_sync(url: str, *, proxy: str | None, total: float, connect: float | None = None, **kwargs) -> httpx.Response:
    """post() for the synchronous image calls."""

    def send(via: str | None) -> httpx.Response:
        limit = _limit(total, via, proxy=proxy, connect=connect)
        with httpx.Client(timeout=limit, trust_env=False, proxy=via) as client:
            return client.post(url, **kwargs)

    def direct() -> httpx.Response | None:
        try:
            return send(None)
        except Exception as exc:
            if connect_failed(exc):
                return None
            raise

    if not proxy:
        return send(None)
    if live(proxy):
        try:
            return send(proxy)
        except Exception as exc:
            if not connect_failed(exc):
                raise
        res = direct()
        if not _refused(res):
            mark_down(proxy)
            return res
        return send(proxy)
    res = direct()
    if not _refused(res):
        return res
    mark_up(proxy)
    return send(proxy)
