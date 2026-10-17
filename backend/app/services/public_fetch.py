"""Downloads from links other people send us (media in messages, scanned images).

Only addresses on the public internet are contacted. Every redirect hop is checked before it is requested, so a 302
cannot reach loopback, private, link-local (cloud metadata) or shared address space.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

from app.services.channel_http import async_client

REDIRECTS = {301, 302, 303, 307, 308}
MAX_HOPS = 4


async def _resolve(host: str, port: int) -> set[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {str(info[4][0]).split("%")[0] for info in infos}


async def public_url(url: str) -> bool:
    """http(s) to an address on the public internet only: no loopback, private, link-local (cloud metadata) or shared space."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    try:
        found = await _resolve(host, parsed.port or 443)
        return bool(found) and all(ipaddress.ip_address(addr).is_global for addr in found)
    except (OSError, ValueError):
        return False


async def fetch_public(url: str, timeout: float, *, headers: dict | None = None) -> tuple[int, dict, bytes]:
    """(status, headers, body) of the final answer. A refused hop or a failed request gives (0, {}, b"")."""
    try:
        for _hop in range(MAX_HOPS):
            if not await public_url(url):
                return 0, {}, b""
            async with async_client(timeout=timeout, follow_redirects=False, headers=headers or {}) as client:
                res = await client.get(url)
            location = res.headers.get("location") if res.status_code in REDIRECTS else None
            if not location:
                return res.status_code, res.headers, res.content or b""
            url = urljoin(url, location)
    except Exception:
        return 0, {}, b""
    return 0, {}, b""
