from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.hub_admin import is_hub_admin
from app.security import require_permission
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user) -> None:
    if not is_hub_admin(user.phone):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "این بخش فقط برای مدیر سوزان است")


class PlanChangeIn(BaseModel):
    plan: str = Field(min_length=2, max_length=16)
    days: int = Field(ge=0, le=365)
    reason: str = Field(min_length=3, max_length=300)


class BlockIn(BaseModel):
    blocked: bool
    reason: str = Field(min_length=3, max_length=300)


@router.get("/users")
async def list_users(
    _user=Depends(require_permission("campaigns:read")),
    session: AsyncSession = Depends(get_session),
):
    _require_admin(_user)
    return {"users": await admin_service.list_users(session)}


@router.get("/users/{phone}")
async def user_detail(
    phone: str,
    _user=Depends(require_permission("campaigns:read")),
    session: AsyncSession = Depends(get_session),
):
    _require_admin(_user)
    detail = await admin_service.user_detail(session, phone)
    if not detail:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "کاربر پیدا نشد")
    return detail


@router.post("/users/{phone}/plan")
async def change_plan(
    phone: str,
    body: PlanChangeIn,
    _user=Depends(require_permission("campaigns:write")),
):
    _require_admin(_user)
    try:
        return admin_service.set_user_plan(phone, body.plan, days=body.days, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/users/{phone}/block")
async def block_user(
    phone: str,
    body: BlockIn,
    _user=Depends(require_permission("campaigns:write")),
    session: AsyncSession = Depends(get_session),
):
    _require_admin(_user)
    try:
        return await admin_service.set_user_blocked(session, phone, body.blocked, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/payments")
async def payments(_user=Depends(require_permission("campaigns:read"))):
    _require_admin(_user)
    return admin_service.global_payments()


@router.get("/audit")
async def audit(_user=Depends(require_permission("campaigns:read"))):
    _require_admin(_user)
    return {"actions": admin_service.audit_trail()}


@router.get("/health")
async def health(_user=Depends(require_permission("campaigns:read"))):
    """Hub snapshot for the admin panel (read-only; the probes block, so they run in a thread)."""
    _require_admin(_user)
    import asyncio

    from app.services import admin_health_service

    return await asyncio.to_thread(admin_health_service.snapshot)
