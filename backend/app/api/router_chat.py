import asyncio
from contextlib import asynccontextmanager

from app.api.chat_payload import read_chat_payload
from app.database import SessionLocal
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.security import require_permission
from app.services import idempotency_service, router_service
from app.services.campaign_service import CampaignService
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/chat", tags=["chat"])


@asynccontextmanager
async def _campaigns():
    async with SessionLocal() as session:
        yield CampaignService(CampaignRepository(session), AssetRepository(session), CopyRepository(session))


def _idempotency_key(request: Request) -> str:
    return (request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key") or "").strip()


async def _read_payload(request: Request) -> tuple[str, dict | None, str, str, str, str]:
    ctype = request.headers.get("content-type") or ""
    if ctype.startswith("multipart/form-data"):
        return await read_chat_payload(request)
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


async def _wait_cached(key: str):
    for _ in range(80):
        await asyncio.sleep(0.5)
        cached = idempotency_service.get("router-chat", key)
        if cached is not None:
            return cached
        if not router_service.turn_busy():
            return None
    return None


async def _finish_turn(key: str, text: str, media, view_path: str, view_target: str, confirm_id: str, cancel_id: str):
    for _ in range(3):
        try:
            out = await router_service.turn(
                text,
                confirm_id=confirm_id,
                cancel_id=cancel_id,
                campaigns_factory=_campaigns,
                media=media,
                view_path=view_path,
                view_target=view_target,
            )
        except router_service.RouterBusy:
            cached = await _wait_cached(key)
            if cached is not None:
                return cached
            continue
        idempotency_service.put("router-chat", key, out)
        return out
    raise HTTPException(status.HTTP_409_CONFLICT, "هنوز جواب قبلی تمام نشده. چند ثانیه بعد دوباره بفرست.")


@router.post("")
async def post_chat(
    request: Request,
    _user=Depends(require_permission("campaigns:write")),
):
    key = _idempotency_key(request)
    text, media, view_path, view_target, confirm_id, cancel_id = await _read_payload(request)
    async with router_service.turn_lock():
        cached = idempotency_service.get("router-chat", key)
        if cached is not None:
            return cached
        return await _finish_turn(key, text, media, view_path, view_target, confirm_id, cancel_id)
