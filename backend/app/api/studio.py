from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.api.chat_payload import read_chat_payload
from app.database import get_session
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.security import require_permission
from app.services.campaign_service import CampaignService
from app.services import channel_service, idempotency_service, studio_chat_service, studio_publish_service
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/studio", tags=["studio"])


class PublishIn(BaseModel):
    campaignId: str = ""
    messageId: str = ""
    platform: str = Field(min_length=2, max_length=32)
    caption: str = Field(default="", max_length=2200)
    mediaName: str = Field(min_length=1, max_length=200)
    mediaKind: str = Field(min_length=1, max_length=16)
    force: bool = False
    recipientId: str = Field(default="", max_length=80)


class CaptionIn(BaseModel):
    messageId: str = Field(min_length=1, max_length=64)
    captions: dict = Field(default_factory=dict)


def _svc(session: AsyncSession = Depends(get_session)) -> CampaignService:
    return CampaignService(CampaignRepository(session), AssetRepository(session), CopyRepository(session))


def _idempotency_key(request: Request) -> str:
    return (request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key") or "").strip()


@router.get("")
async def get_studio(_user=Depends(require_permission("campaigns:read"))):
    snap = studio_chat_service.snapshot()
    return {**snap, "targets": channel_service.publish_targets()}


@router.get("/content")
async def studio_content(
    _user=Depends(require_permission("campaigns:read")),
    service: CampaignService = Depends(_svc),
):
    return studio_chat_service.content_library(await service.list_campaigns())


@router.get("/audience")
async def studio_audience(
    q: str = "",
    platform: str = "instagram",
    _user=Depends(require_permission("campaigns:read")),
):
    return studio_publish_service.list_audience(platform=platform, q=q)


@router.post("/chat")
async def studio_chat(
    request: Request,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    key = _idempotency_key(request)
    raw = await request.body()
    stamp = idempotency_service.body_stamp(raw)
    cached = idempotency_service.recall("studio-chat", key, stamp)
    if cached is not None:
        return cached
    text, media, _view_path, _view_target, _confirm, _cancel, _thread = await read_chat_payload(request)
    out = await studio_chat_service.chat(text, service, media)
    idempotency_service.put("studio-chat", key, out, stamp)
    return out


@router.post("/publish")
async def studio_publish(request: Request, body: PublishIn, _user=Depends(require_permission("campaigns:write"))):
    key = _idempotency_key(request)
    raw = await request.body()
    stamp = idempotency_service.body_stamp(raw)
    cached = idempotency_service.recall("studio-publish", key, stamp)
    if cached is not None:
        return cached
    try:
        out = await studio_publish_service.publish(
            platform=body.platform,
            caption=body.caption,
            media_name=body.mediaName,
            media_kind=body.mediaKind,
            message_id=body.messageId,
            campaign_id=body.campaignId,
            force=body.force,
            recipient_id=body.recipientId,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    idempotency_service.put("studio-publish", key, out, stamp)
    return out


@router.patch("/caption")
async def studio_caption(
    body: CaptionIn,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    try:
        out = studio_chat_service.update_captions(body.messageId, body.captions)
        campaign_id = str(out.get("campaignId") or "")
        if campaign_id:
            from uuid import UUID

            clipped = out["captions"]
            await service.update_copy(
                UUID(campaign_id),
                title=None,
                subtitle=None,
                cta=None,
                instagram_caption=clipped["instagram"],
                telegram_caption=clipped["telegram"],
                whatsapp_caption=clipped["whatsapp"],
            )
        return out
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/regenerate")
async def studio_regenerate(
    request: Request,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    key = _idempotency_key(request)
    raw = await request.body()
    stamp = idempotency_service.body_stamp(raw)
    cached = idempotency_service.recall("studio-regenerate", key, stamp)
    if cached is not None:
        return cached
    message_id = ""
    part = "caption"
    media = None
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            message_id = str(form.get("messageId") or "")
            part = str(form.get("part") or "caption")
            upload = form.get("file")
            if upload is not None and hasattr(upload, "read"):
                from app.services import chat_media_service

                data = await upload.read()
                saved = chat_media_service.save(
                    getattr(upload, "filename", "") or "still.png",
                    data,
                    getattr(upload, "content_type", "") or "",
                )
                media = saved
        else:
            body = await request.json()
            message_id = str(body.get("messageId") or "")
            part = str(body.get("part") or "caption")
        out = await studio_chat_service.regenerate(
            message_id=message_id, part=part, campaigns=service, media=media
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    idempotency_service.put("studio-regenerate", key, out, stamp)
    return out
