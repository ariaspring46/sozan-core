"""Requests to Iranian services (SMS, payment gateways, the Arvan API) leave from the hub's own public IP.

Other projects on the hub can route all outbound traffic through a foreign VPN with a policy rule (seen 2026-10-04:
`from all lookup 77` → wgp). Melipayamak refuses that exit, so login codes stopped. The hub keeps a
`from <its own IP> lookup main` rule ahead of those, so a request bound to that source address goes out of the
hub's own interface whatever the others change. The address is EGRESS_SOURCE_IP, else ARVAN_ORIGIN_IP (the same
public IP the CDN reaches us on); it is used only when it really belongs to this machine.
"""

from __future__ import annotations

import socket
from functools import lru_cache

import httpx

from app.config import settings


@lru_cache(maxsize=4)
def _is_local(ip: str) -> bool:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((ip, 0))
        return True
    except OSError:
        return False


def source_ip() -> str:
    ip = str(getattr(settings, "egress_source_ip", "") or settings.arvan_origin_ip or "").strip()
    return ip if ip and _is_local(ip) else ""


def client_kwargs(*, sync: bool = False) -> dict:
    """Extra httpx client arguments: a transport bound to the hub's own IP, or nothing off the hub."""
    ip = source_ip()
    if not ip:
        return {}
    transport = httpx.HTTPTransport(local_address=ip) if sync else httpx.AsyncHTTPTransport(local_address=ip)
    return {"transport": transport}
