from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from app.security import require_permission
from app.services.settings_service import STUDIO_KEYS, public_settings, save_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsIn(BaseModel):
    mockSms: bool | None = None
    adminPhone: str | None = None
    otpTtlSeconds: int | None = None
    gatewayPublicUrl: str | None = None
    storeName: str | None = None
    storeTagline: str | None = None
    paymentSandbox: bool | None = None
    paymentGateway: str | None = None
    paymentMerchantId: str | None = Field(default=None, max_length=80)
    paymentApiKey: str | None = Field(default=None, max_length=200)
    paymentCurrency: str | None = Field(default=None, max_length=8)
    paymentCallbackUrl: str | None = Field(default=None, max_length=400)
    smsProvider: str | None = Field(default=None, max_length=32)
    smsApiKey: str | None = Field(default=None, max_length=200)
    smsTemplateId: str | None = Field(default=None, max_length=80)
    smsTokenName: str | None = Field(default=None, max_length=40)
    plan: str | None = None
    helpImprove: bool | None = None


def _is_hub_admin(user) -> bool:
    from app.hub_admin import is_hub_admin

    return is_hub_admin(user.phone)


class FeedbackIn(BaseModel):
    trainId: str = Field(min_length=4, max_length=80)
    good: bool


class SellerTicketIn(BaseModel):
    subject: str = Field(min_length=2, max_length=120)
    text: str = Field(min_length=2, max_length=2000)


@router.get("/support/my-tickets")
async def my_seller_tickets(_user=Depends(require_permission("campaigns:read"))):
    from app.services import support_service

    return {"tickets": support_service.list_tickets(kind="seller")}


@router.post("/support/seller-ticket")
async def create_seller_ticket(body: SellerTicketIn, _user=Depends(require_permission("campaigns:write"))):
    from app.services import support_service

    return support_service.create_ticket(subject=body.subject, text=body.text, kind="seller")


@router.get("/support/hub")
async def hub_tickets(_user=Depends(require_permission("campaigns:read"))):
    from app.hub_admin import is_hub_admin
    from app.services import support_service

    if not is_hub_admin(_user.phone):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "این فهرست برای پشتیبانی سوزان است")
    return {"tickets": support_service.list_all_tickets_for_hub_admin()}


@router.post("/support/hub/{ticket_id}/reply")
async def hub_ticket_reply(
    ticket_id: str,
    body: dict,
    _user=Depends(require_permission("campaigns:write")),
):
    from app.hub_admin import is_hub_admin
    from app.services import support_service

    if not is_hub_admin(_user.phone):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "این پاسخ برای پشتیبانی سوزان است")
    try:
        return support_service.reply_hub_ticket(
            ticket_id, text=str(body.get("text") or ""), status=str(body.get("status") or "")
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/feedback")
async def feedback(body: FeedbackIn, _user=Depends(require_permission("campaigns:write"))):
    from app.services import training_log

    training_log.log_label(str(body.trainId), {"vote": "up" if body.good else "down"})
    return {"ok": True}


@router.get("")
async def read_settings(_user=Depends(require_permission("campaigns:read"))) -> dict[str, Any]:
    return public_settings()


@router.patch("")
async def patch_settings(
    body: SettingsIn,
    user=Depends(require_permission("campaigns:write")),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    hub_admin = _is_hub_admin(user)
    if any(key in patch for key in STUDIO_KEYS) and not hub_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "این تنظیمات فقط برای مدیر هاب است")
    try:
        return save_settings(patch, hub_admin=hub_admin)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


class SalesPolicyIn(BaseModel):
    shippingMethod: str | None = None
    shippingCost: str | int | None = None
    shippingDays: str | None = None
    shippingCities: str | None = None
    freeShippingFrom: str | int | None = None
    returnDays: str | int | None = None
    returnNote: str | None = None
    returnPayer: str | None = None
    hours: str | None = None
    sizeExchange: str | None = None
    invoice: str | None = None
    cod: str | None = None
    minOrder: str | int | None = None


@router.get("/sales-policy")
async def read_sales_policy(_user=Depends(require_permission("campaigns:read"))) -> dict[str, Any]:
    from app.services.sales_policy_service import public_policy

    return public_policy()


@router.put("/sales-policy")
async def write_sales_policy(
    body: SalesPolicyIn,
    _user=Depends(require_permission("campaigns:write")),
) -> dict[str, Any]:
    from app.services.sales_policy_service import save_policy

    try:
        return save_policy(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
