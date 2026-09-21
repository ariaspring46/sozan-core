from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat_payload import read_chat_payload
from app.database import get_session
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.security import require_permission
from app.services import idempotency_service, router_service
from app.services.campaign_service import CampaignService
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/chat", tags=["chat"])


def _svc(session: AsyncSession = Depends(get_session)) -> CampaignService:
    return CampaignService(CampaignRepository(session), AssetRepository(session), CopyRepository(session))


def _idempotency_key(request: Request) -> str:
    return (request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key") or "").strip()


async def _read_payload(request: Request) -> tuple[str, dict | None, str, str, str, str]:
    ctype = request.headers.get("content-type") or ""
    if ctype.startswith("multipart/form-data"):
        text, media, view_path, view_target = await read_chat_payload(request)
        return text, media, view_path, view_target, "", ""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "بدنه نامعتبر است.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "بدنه نامعتبر است.")
    text = str(payload.get("text") or "").strip()
    confirm_id = str(payload.get("confirmId") or "").strip()
    cancel_id = str(payload.get("cancelId") or "").strip()
    view_path = str(payload.get("viewPath") or "").strip()[:200]
    view_target = str(payload.get("viewTarget") or "").strip()[:80]
    if not text and not confirm_id and not cancel_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "متن یا تأیید لازم است.")
    if len(text) > 4000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "متن خیلی بلند است.")
    return text, None, view_path, view_target, confirm_id, cancel_id


@router.get("")
async def get_chat(_user=Depends(require_permission("campaigns:read"))):
    return router_service.snapshot()


@router.post("")
async def post_chat(
    request: Request,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    key = _idempotency_key(request)
    cached = idempotency_service.get("router-chat", key)
    if cached is not None:
        return cached
    text, media, view_path, view_target, confirm_id, cancel_id = await _read_payload(request)
    out = await router_service.turn(
        text,
        confirm_id=confirm_id,
        cancel_id=cancel_id,
        campaigns=service,
        media=media,
        view_path=view_path,
        view_target=view_target,
    )
    idempotency_service.put("router-chat", key, out)
    return out
