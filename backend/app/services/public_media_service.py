from __future__ import annotations

import base64
import hashlib
import hmac
import time
from pathlib import Path

from fastapi import HTTPException, status

from app.config import settings
from app.services import chat_media_service
from app.state_store import current_tenant, tenant_scope


def _sign(body: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def mint(*, name: str, ttl: int = 3600) -> str:
    tenant = current_tenant()
    if not tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مستأجر نامشخص است")
    safe = Path(name).name
    if safe != name or not safe:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام نامعتبر است")
    exp = int(time.time()) + max(60, ttl)
    body = f"{tenant}|{safe}|{exp}"
    raw = f"{body}|{_sign(body)}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def public_url(*, name: str, ttl: int = 3600) -> str:
    origin = (settings.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{origin}/public-media/{mint(name=name, ttl=ttl)}"


def _decode(token: str) -> tuple[str, str, int]:
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لینک نامعتبر است") from exc
    parts = raw.split("|")
    if len(parts) != 4:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لینک نامعتبر است")
    tenant, name, exp_raw, sig = parts
    body = f"{tenant}|{name}|{exp_raw}"
    if not hmac.compare_digest(sig, _sign(body)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لینک نامعتبر است")
    try:
        exp = int(exp_raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لینک نامعتبر است") from exc
    if exp < int(time.time()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لینک منقضی شده است")
    return tenant, name, exp


def resolve_token(token: str) -> Path:
    tenant, name, _exp = _decode(token)
    with tenant_scope(tenant):
        return chat_media_service.resolve(name)
