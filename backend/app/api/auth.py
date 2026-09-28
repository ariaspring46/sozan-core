from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas import OtpSendIn, OtpVerifyIn
from app.security import get_current_user
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_hub_admin(phone: str) -> bool:
    from app.hub_admin import is_hub_admin

    return is_hub_admin(phone)


def _auth(session: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(UserRepository(session))


@router.get("/otp/captcha")
async def otp_captcha(phone: str):
    import secrets as _secrets

    from app.redis_client import redis_client

    a = _secrets.randbelow(8) + 2
    b = _secrets.randbelow(8) + 2
    token = _secrets.token_hex(12)
    await redis_client.setex(f"captcha:{token}", 300, str(a + b))
    fa = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return {"token": token, "question": f"{str(a).translate(fa)} + {str(b).translate(fa)} = ؟"}


@router.post("/otp/send")
async def otp_send(request: Request, body: OtpSendIn, service: AuthService = Depends(_auth)):
    ip = request.client.host if request.client else ""
    return await service.send_otp(
        body.phone,
        ip=ip,
        captcha_token=body.captchaToken,
        captcha_answer=body.captchaAnswer,
    )


@router.post("/otp/verify")
async def otp_verify(body: OtpVerifyIn, service: AuthService = Depends(_auth)):
    return await service.verify_otp(body.phone, body.code)


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    from app.services import profile_service

    profile = profile_service.for_session(user.phone)
    return {
        "id": str(user.id),
        "phone": user.phone,
        "role": user.role,
        "onboarded": bool(profile.get("onboarded")),
        "isAdmin": _is_hub_admin(user.phone),
    }
