from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.user import User
from app.repositories.user_repository import UserRepository

bearer = HTTPBearer(auto_error=False)

PERMISSIONS_BY_ROLE = {
    "admin": {"campaigns:read", "campaigns:write", "campaigns:export"},
}


def encode_token(user_id: UUID, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "permissions": sorted(PERMISSIONS_BY_ROLE.get(role, set())),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ورود لازم است")
    try:
        payload = decode_token(creds.credentials)
        user_id = UUID(payload["sub"])
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "توکن نامعتبر است") from exc
    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "کاربر یافت نشد")
    from app.state_store import set_tenant

    set_tenant(user.phone)
    return user


def require_permission(code: str):
    async def _inner(user: User = Depends(get_current_user)) -> User:
        allowed = PERMISSIONS_BY_ROLE.get(user.role, set())
        if code not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "دسترسی کافی نیست")
        return user

    return _inner
