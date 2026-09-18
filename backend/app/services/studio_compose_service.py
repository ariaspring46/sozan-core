from __future__ import annotations

import asyncio
import logging
import threading
import time
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.database import SessionLocal
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.services.campaign_service import CampaignService
from app.services.image_provider_service import DEFAULT_STILL, generate_still
from app.services.observe_client import emit_later
from app.state_store import current_tenant, tenant_scope

log = logging.getLogger("sozan.studio-compose")
STALE_SEC = 600
_still_lock = threading.Lock()


def _generate_still_locked(prompt: str, width: int, height: int, on_acquired=None) -> bytes:
    with _still_lock:
        if on_acquired:
            on_acquired()
        return generate_still(prompt, width=width, height=height)


def _svc(session) -> CampaignService:
    return CampaignService(CampaignRepository(session), AssetRepository(session), CopyRepository(session))


def start(
    *,
    message_id: str,
    campaign_id: str,
    media: dict | None = None,
    title: str = "",
    image_prompt: str = "",
) -> str:
    from app.services import studio_chat_service

    job_id = str(uuid4())
    studio_chat_service.set_compose(
        message_id,
        {"status": "running", "startedAt": time.time(), "jobId": job_id},
    )
    emit_later(
        kind="studio",
        surface="studio",
        title="compose-start",
        status="running",
        stage="queued",
        operation_id=campaign_id,
        turn_id=message_id,
        payload={"jobId": job_id, "title": title[:80]},
    )
    tenant = current_tenant()
    kwargs = {
        "tenant": tenant,
        "message_id": message_id,
        "campaign_id": campaign_id,
        "media": media,
        "title": title,
        "image_prompt": image_prompt,
        "job_id": job_id,
        "started": time.time(),
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run(**kwargs))
    except RuntimeError:
        threading.Thread(target=lambda: asyncio.run(_run(**kwargs)), daemon=True).start()
    return job_id


async def _run(
    *,
    tenant: str,
    message_id: str,
    campaign_id: str,
    media: dict | None,
    title: str,
    image_prompt: str,
    job_id: str,
    started: float,
) -> None:
    from app.services import studio_chat_service

    with tenant_scope(tenant):
        try:
            async with SessionLocal() as session:
                campaigns = _svc(session)
                cid = UUID(campaign_id)
                attached = await studio_chat_service.attach_still(campaigns, cid, media)
                raw_ok = attached
                if not raw_ok:
                    prompt = (image_prompt or "").strip() or f"{DEFAULT_STILL}. Subject: {title[:120]}"

                    def _touch() -> None:
                        studio_chat_service.touch_compose_start(message_id, job_id)

                    png = await asyncio.to_thread(_generate_still_locked, prompt, 1080, 1080, _touch)
                    if len(png) < 2048:
                        raise RuntimeError("still-failed")
                    await campaigns.save_raw(cid, "feed.png", png)
                    emit_later(
                        kind="studio",
                        surface="studio",
                        title="still-generated",
                        status="running",
                        stage="still",
                        operation_id=campaign_id,
                        turn_id=message_id,
                        payload={"jobId": job_id, "bytes": len(png)},
                    )
                await campaigns.compose(cid)
                attachments = studio_chat_service.copy_outputs(await campaigns.preview_outputs(cid))
                if not attachments:
                    attachments = studio_chat_service.fallback_attachment(media)
                studio_chat_service.finish_compose(message_id, attachments, status="ready", job_id=job_id)
                emit_later(
                    kind="studio",
                    surface="studio",
                    title="compose-ready",
                    status="ready",
                    stage="video",
                    operation_id=campaign_id,
                    turn_id=message_id,
                    duration_ms=int((time.time() - started) * 1000),
                    payload={"jobId": job_id, "attachments": len(attachments)},
                )
        except Exception as exc:
            log.warning("studio compose failed: %s: %s", type(exc).__name__, str(exc)[:200])
            detail = "تصویر خام"
            if isinstance(exc, HTTPException):
                detail = str(exc.detail or detail)
            if "still-failed" in str(exc) or "تصویر خام" in detail:
                error = "کپشن ذخیره شد. ساخت تصویر نشد؛ یک عکس پیوست کن یا دوباره بساز."
            else:
                error = "کپشن ذخیره شد؛ ساخت تصویر و ویدیو کامل نشد. از صفحهٔ کمپین دوباره بساز."
            studio_chat_service.finish_compose(
                message_id,
                studio_chat_service.fallback_attachment(media),
                status="failed",
                error=error,
                job_id=job_id,
            )
            emit_later(
                kind="studio",
                surface="studio",
                title="compose-failed",
                status="failed",
                stage="video",
                operation_id=campaign_id,
                turn_id=message_id,
                duration_ms=int((time.time() - started) * 1000),
                payload={"jobId": job_id, "error": str(exc)[:200], "errorClass": type(exc).__name__},
            )


def expire_stale() -> None:
    from app.services import studio_chat_service

    studio_chat_service.expire_stale_compose(STALE_SEC)
