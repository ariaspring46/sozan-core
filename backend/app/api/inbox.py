from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.security import require_permission
from app.services import idempotency_service, inbox_service

router = APIRouter(prefix="/inbox", tags=["inbox"])


class InboundIn(BaseModel):
    platform: str = Field(min_length=2, max_length=32)
    sender: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=4000)
    senderId: str = Field(default="", max_length=200)
    chatId: str = Field(default="", max_length=200)
    externalId: str = Field(default="", max_length=200)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    draftId: str = Field(default="", max_length=64)
    deliver: bool = True


class SettingsIn(BaseModel):
    autoReply: str = Field(default="", max_length=16)


class ThreadPatchIn(BaseModel):
    paused: bool | None = None


@router.get("")
async def list_inbox(
    q: str = Query(default="", max_length=200),
    platform: str = Query(default="", max_length=32),
    filter: str = Query(default="", max_length=32),
    _user=Depends(require_permission("campaigns:read")),
):
    return inbox_service.list_threads(q=q, platform=platform, status_filter=filter)


@router.get("/unread")
async def inbox_unread(_user=Depends(require_permission("campaigns:read"))):
    return inbox_service.unread_count()


@router.post("/sync")
async def inbox_sync(_user=Depends(require_permission("campaigns:write"))):
    try:
        return await inbox_service.sync_now()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.patch("/settings")
async def inbox_settings(body: SettingsIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return inbox_service.save_auto_reply(body.autoReply)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/{thread_id}")
async def get_inbox(thread_id: str, _user=Depends(require_permission("campaigns:read"))):
    try:
        return inbox_service.get_thread(thread_id, mark_read=True)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.patch("/{thread_id}")
async def patch_inbox(thread_id: str, body: ThreadPatchIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return inbox_service.patch_thread(thread_id, paused=body.paused)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{thread_id}/messages/{message_id}")
async def delete_inbox_message(
    thread_id: str, message_id: str, _user=Depends(require_permission("campaigns:write"))
):
    try:
        return inbox_service.discard_failed_message(thread_id, message_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/inbound")
async def inbox_inbound(body: InboundIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return await inbox_service.handle_inbound(
            platform=body.platform,
            sender=body.sender,
            text=body.text,
            sender_id=body.senderId,
            chat_id=body.chatId,
            external_id=body.externalId,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{thread_id}/reply")
async def inbox_reply(thread_id: str, request: Request, body: ReplyIn, _user=Depends(require_permission("campaigns:write"))):
    key = (request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key") or "").strip()
    cached = idempotency_service.get("inbox-reply", key)
    if cached is not None:
        return cached
    try:
        out = await inbox_service.reply(
            thread_id,
            body.text,
            deliver=body.deliver,
            draft_id=body.draftId,
        )
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    idempotency_service.put("inbox-reply", key, out)
    return out
