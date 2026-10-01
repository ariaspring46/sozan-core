"""Real caller IP for rate limits.

The API sits behind nginx behind the CDN, so request.client.host is the proxy,
not the person. TRUSTED_IP_HEADER names a header the CDN overwrites on every
request (never one a caller can set). Empty keeps the socket address.
"""

from __future__ import annotations

from fastapi import Request

from app.config import settings


def client_ip(request: Request) -> str:
    header = str(settings.trusted_ip_header or "").strip()
    if header:
        first = request.headers.get(header, "").split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else ""
