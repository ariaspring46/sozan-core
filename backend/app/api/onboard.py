from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.channels import _with_oauth
from app.models.user import User
from app.security import require_permission
from app.services import onboard_service

router = APIRouter(prefix="/onboard", tags=["onboard"])


class OnboardDraftIn(BaseModel):
    firstName: str = Field(default="", max_length=80)
    lastName: str = Field(default="", max_length=80)
    brandName: str = Field(default="", max_length=120)
    brandWork: str = Field(default="", max_length=400)
    toneId: str = Field(default="", max_length=40)


@router.get("")
async def get_onboard(user: User = Depends(require_permission("campaigns:read"))):
    return _with_oauth(onboard_service.snapshot(user.phone))


@router.post("/draft")
async def save_onboard_draft(body: OnboardDraftIn, user: User = Depends(require_permission("campaigns:write"))):
    return _with_oauth(
        onboard_service.save_draft(
            user.phone,
            first_name=body.firstName,
            last_name=body.lastName,
            brand_name=body.brandName,
            brand_work=body.brandWork,
            tone_id=body.toneId,
        )
    )


@router.post("/complete")
async def complete_onboard(
    firstName: str = Form(""),
    lastName: str = Form(""),
    brandName: str = Form(""),
    brandWork: str = Form(""),
    toneId: str = Form("warm"),
    channels: str = Form("[]"),
    logo: UploadFile | None = File(None),
    user: User = Depends(require_permission("campaigns:write")),
):
    blob = await logo.read() if logo and logo.filename else None
    try:
        return await onboard_service.complete(
            phone=user.phone,
            first_name=firstName,
            last_name=lastName,
            brand_name=brandName,
            brand_work=brandWork,
            tone_id=toneId,
            channels=onboard_service.parse_channels(channels),
            logo=blob or None,
            logo_name=(logo.filename if logo else "") or "logo.png",
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except HTTPException:
        raise
