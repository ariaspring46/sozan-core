"""OpenRouter leaves the hub directly, through the WireGuard exit. A fallback SOCKS is the second try.

Direct is first. The fallback proxy (OPENROUTER_PROXY_FALLBACK, a Tailscale SOCKS to another foreign node) is used
only when direct never connects or OpenRouter answers 403. A reply that already started, including a read timeout,
is not sent again. When direct does not connect, the fallback goes first for DOWN_SECONDS, so a dead exit costs the
connect timeout once and not on every call.
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


_DIRECT = "direct"


def direct_down() -> bool:
    """Direct did not connect a moment ago (the WireGuard exit is down): the fallback goes first until DOWN_SECONDS pass."""
    return _down_until.get(_DIRECT, 0.0) > time.monotonic()


def _mark_direct_down() -> None:
    if not direct_down():
        log.warning("direct did not connect; fallback first for %ds", int(DOWN_SECONDS))
    _down_until[_DIRECT] = time.monotonic() + DOWN_SECONDS


def openrouter_fallback() -> str | None:
    """SOCKS to a second foreign node. Empty means direct only."""
    import os

    return (os.environ.get("OPENROUTER_PROXY_FALLBACK") or "").strip() or None


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

    if proxy and direct_down():
        try:
            return await send(proxy)
        except Exception as exc:
            if not connect_failed(exc):
                raise
        return await send(None)
    direct_res: httpx.Response | None = None
    try:
        direct_res = await send(None)
    except Exception as exc:
        if not connect_failed(exc):
            raise
        if not proxy:
            raise
        _mark_direct_down()
    else:
        if not _refused(direct_res) or not proxy:
            return direct_res
    try:
        return await send(proxy)
    except Exception:
        if direct_res is not None:
            return direct_res
        raise


def post_sync(url: str, *, proxy: str | None, total: float, connect: float | None = None, **kwargs) -> httpx.Response:
    """post() for the synchronous image calls."""

    def send(via: str | None) -> httpx.Response:
        limit = _limit(total, via, proxy=proxy, connect=connect)
        with httpx.Client(timeout=limit, trust_env=False, proxy=via) as client:
            return client.post(url, **kwargs)

    if proxy and direct_down():
        try:
            return send(proxy)
        except Exception as exc:
            if not connect_failed(exc):
                raise
        return send(None)
    direct_res: httpx.Response | None = None
    try:
        direct_res = send(None)
    except Exception as exc:
        if not connect_failed(exc):
            raise
        if not proxy:
            raise
        _mark_direct_down()
    else:
        if not _refused(direct_res) or not proxy:
            return direct_res
    try:
        return send(proxy)
    except Exception:
        if direct_res is not None:
            return direct_res
        raise
