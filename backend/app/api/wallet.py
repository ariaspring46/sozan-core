from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.phone import normalize_phone
from app.security import require_permission
from app.services import wallet_service

router = APIRouter(prefix="/wallet", tags=["wallet"])


class WithdrawIn(BaseModel):
    amount: int = Field(gt=0)
    iban: str = Field(min_length=26, max_length=32)
    name: str = Field(default="", max_length=80)


class WithdrawDecisionIn(BaseModel):
    ok: bool


def _is_admin(user) -> bool:
    try:
        return normalize_phone(user.phone) == normalize_phone(settings.admin_phone)
    except ValueError:
        return False


@router.get("")
async def read_wallet(_user=Depends(require_permission("campaigns:read"))):
    return wallet_service.snapshot()


@router.post("/withdraw")
async def withdraw(body: WithdrawIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return wallet_service.request_withdraw(amount=body.amount, iban=body.iban, name=body.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/admin/withdrawals")
async def admin_list(user=Depends(require_permission("campaigns:read"))):
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "فقط مدیر سوزان")
    return {"withdrawals": wallet_service.admin_withdrawals()}


@router.post("/admin/withdrawals/{withdraw_id}")
async def admin_decide(
    withdraw_id: str,
    body: WithdrawDecisionIn,
    user=Depends(require_permission("campaigns:write")),
):
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "فقط مدیر سوزان")
    found = next((row for row in wallet_service.admin_withdrawals() if str(row.get("id")) == withdraw_id), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "درخواست پیدا نشد")
    try:
        return wallet_service.decide_withdraw(withdraw_id, ok=body.ok, phone=str(found.get("phone") or ""))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
