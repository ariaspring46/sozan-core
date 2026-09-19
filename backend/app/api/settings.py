from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.phone import normalize_phone
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


def _is_hub_admin(user) -> bool:
    try:
        return normalize_phone(user.phone) == normalize_phone(settings.admin_phone)
    except ValueError:
        return False


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
