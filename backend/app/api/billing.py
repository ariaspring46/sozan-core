from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.security import require_permission
from app.services import billing_service

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans")
async def public_plans():
    from app.services import plan_service

    return plan_service.public_catalog()


class SubscribeIn(BaseModel):
    plan: str = Field(min_length=2, max_length=16)


@router.post("/subscribe")
async def subscribe(body: SubscribeIn, user=Depends(require_permission("campaigns:write"))):
    try:
        return await billing_service.start_subscription(body.plan, phone=user.phone)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/zarinpal/callback")
async def zarinpal_callback(
    authority: str = Query(default="", alias="Authority"),
    pay_status: str = Query(default="", alias="Status"),
):
    ok = pay_status.upper() == "OK" and bool(authority.strip())
    url = await billing_service.finish_subscription(authority=authority.strip(), ok=ok)
    return RedirectResponse(url, status_code=302)
