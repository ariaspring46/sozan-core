"""Channel HTTP: Iranian APIs go direct, foreign hosts go through SOCKS with a second proxy.

Sendbox, BoxAPI, Bale and Rubika answer from Iran and can refuse a foreign IP, so they stay direct.
Instagram, Facebook's graph, Telegram and t.me are blocked from the hub, so they use CHANNEL_PROXY
and, if that never connects, CHANNEL_PROXY_FALLBACK. A read that already started is not sent again.
"""

from __future__ import annotations

import httpx

from app.config import settings

CONNECT_LIMIT = 5.0

# Suffixes. A host matches when it is the suffix or a subdomain of it.
_FOREIGN_SUFFIXES = (
    "instagram.com",
    "cdninstagram.com",
    "fbcdn.net",
    "graph.facebook.com",
    "api.telegram.org",
    "t.me",
    "telegram.me",
)

_FOREIGN_MOUNTS = (
    "all://*instagram.com",
    "all://*cdninstagram.com",
    "all://*fbcdn.net",
    "all://graph.facebook.com",
    "all://api.telegram.org",
    "all://t.me",
    "all://*.t.me",
    "all://*telegram.me",
)


def _socks(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("socks5://"):
        return "socks5h://" + text[len("socks5://") :]
    return text


def channel_proxy() -> str | None:
    return _socks(settings.channel_proxy or "")


def channel_proxy_fallback() -> str | None:
    return _socks(getattr(settings, "channel_proxy_fallback", "") or "")


def foreign_host(host: str) -> bool:
    name = (host or "").lower().rstrip(".")
    return any(name == suffix or name.endswith("." + suffix) for suffix in _FOREIGN_SUFFIXES)


def proxies_for(url: str) -> list[str]:
    """SOCKS hops for a foreign URL, primary then fallback. Empty means direct."""
    try:
        host = httpx.URL(url).host
    except Exception:
        return []
    if not foreign_host(host):
        return []
    return [item for item in (channel_proxy(), channel_proxy_fallback()) if item]


def _connect_failed(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError))


def _short_connect(saved: object) -> dict:
    base = dict(saved) if isinstance(saved, dict) else {}
    current = base.get("connect", CONNECT_LIMIT)
    try:
        limit = CONNECT_LIMIT if current is None else min(float(current), CONNECT_LIMIT)
    except (TypeError, ValueError):
        limit = CONNECT_LIMIT
    base["connect"] = limit
    return base


class FailoverProxyTransport(httpx.AsyncBaseTransport):
    """Try each SOCKS in order. Only a connect failure moves to the next one."""

    def __init__(self, proxies: list[str]) -> None:
        self._pool = [httpx.AsyncHTTPTransport(proxy=proxy) for proxy in proxies if proxy]
        # no proxy configured: one direct transport, closed with this one (closing it per request dropped the body
        # before the client could read it)
        self._direct = None if self._pool else httpx.AsyncHTTPTransport()
        self._closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._direct is not None:
            return await self._direct.handle_async_request(request)
        last: BaseException | None = None
        for index, transport in enumerate(self._pool):
            saved = request.extensions.get("timeout")
            shrink = index == 0 and len(self._pool) > 1
            if shrink:
                request.extensions["timeout"] = _short_connect(saved)
            try:
                return await transport.handle_async_request(request)
            except Exception as exc:
                if not _connect_failed(exc) or index == len(self._pool) - 1:
                    raise
                last = exc
            finally:
                if shrink:
                    if saved is None:
                        request.extensions.pop("timeout", None)
                    else:
                        request.extensions["timeout"] = saved
        assert last is not None
        raise last

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for transport in self._pool:
            await transport.aclose()
        if self._direct is not None:
            await self._direct.aclose()


def async_client(*, timeout: float = 20, **kwargs) -> httpx.AsyncClient:
    kwargs.pop("proxy", None)
    hops = [item for item in (channel_proxy(), channel_proxy_fallback()) if item]
    mounts: dict[str, httpx.AsyncBaseTransport] | None = None
    if hops:
        transport = FailoverProxyTransport(hops)
        mounts = {pattern: transport for pattern in _FOREIGN_MOUNTS}
    return httpx.AsyncClient(timeout=timeout, trust_env=False, mounts=mounts, **kwargs)
