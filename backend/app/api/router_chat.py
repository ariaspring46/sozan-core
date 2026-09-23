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


async def _read_payload(request: Request) -> tuple[str, dict | None, str, str, str, str, str]:
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
    thread_id = str(payload.get("threadId") or "").strip()[:32]
    if not text and not confirm_id and not cancel_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "متن یا تأیید لازم است.")
    if len(text) > 4000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "متن خیلی بلند است.")
    return text, None, view_path, view_target, confirm_id, cancel_id, thread_id


@router.get("")
async def get_chat(threadId: str = "", _user=Depends(require_permission("campaigns:read"))):
    return router_service.snapshot(threadId)


def _scope(thread_id: str) -> str:
    return f"router-chat:{thread_id}" if thread_id else "router-chat"


async def _wait_cached(scope: str, key: str, thread_id: str, stamp: str):
    for _ in range(40):
        await asyncio.sleep(0.5)
        cached = idempotency_service.recall(scope, key, stamp)
        if cached is not None:
            return cached
        router_service._bind_thread(thread_id)
        if router_service.inflight_key() != key:
            return None
    return None


async def _finish_turn(
    key: str,
    text: str,
    media,
    view_path: str,
    view_target: str,
    confirm_id: str,
    cancel_id: str,
    thread_id: str,
    stamp: str,
):
    router_service._bind_thread(thread_id)
    tid = router_service._THREAD.get()
    scope = _scope(tid)
    try:
        out = await router_service.turn(
            text,
            confirm_id=confirm_id,
            cancel_id=cancel_id,
            campaigns_factory=_campaigns,
            media=media,
            view_path=view_path,
            view_target=view_target,
            idempotency_key=key,
            thread_id=tid,
        )
    except router_service.RouterBusy:
        router_service._bind_thread(tid)
        if key and router_service.inflight_key() == key:
            cached = await _wait_cached(scope, key, tid, stamp)
            if cached is not None:
                return cached
        snap = router_service.snapshot(tid)
        snap["notice"] = router_service.STILL_WRITING
        return snap
    idempotency_service.put(scope, key, out, stamp)
    return out


@router.post("")
async def post_chat(
    request: Request,
    _user=Depends(require_permission("campaigns:write")),
):
    key = _idempotency_key(request)
    raw = await request.body()
    stamp = idempotency_service.body_stamp(raw)
    text, media, view_path, view_target, confirm_id, cancel_id, thread_id = await _read_payload(request)
    router_service._bind_thread(thread_id)
    tid = router_service._THREAD.get()
    cached = idempotency_service.recall(_scope(tid), key, stamp)
    if cached is not None:
        return cached
    return await _finish_turn(key, text, media, view_path, view_target, confirm_id, cancel_id, tid, stamp)


@router.post("/threads")
async def post_thread(_user=Depends(require_permission("campaigns:write"))):
    try:
        return router_service.new_thread()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
