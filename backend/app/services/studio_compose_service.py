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
from app.services.image_provider_service import generate_still
from app.services.observe_client import emit_later
from app.state_store import current_tenant, tenant_scope

log = logging.getLogger("sozan.studio-compose")
STALE_SEC = 600
_still_lock = threading.Lock()
_COMPOSE_TASKS: set[asyncio.Task] = set()
_COMPOSE_THREADS: set[threading.Thread] = set()


def queued_outputs(*, has_image: bool) -> tuple[bool, bool]:
    return bool(has_image), bool(has_image)


def _generate_still_locked(
    prompt: str,
    width: int,
    height: int,
    on_acquired=None,
    source: bytes | None = None,
    edit: bool = False,
    subject: str = "",
    edit_kind: str = "",
) -> bytes:
    with _still_lock:
        if on_acquired:
            on_acquired()
        from app.services.plan_service import current_plan_id

        return generate_still(
            prompt,
            width=width,
            height=height,
            edit=edit,
            plan=current_plan_id(),
            source=source,
            subject=subject,
            edit_kind=edit_kind,
        )


def _media_bytes(media: dict | None) -> bytes:
    if not media or str(media.get("kind") or "") != "image":
        return b""
    try:
        from app.services import chat_media_service

        path = chat_media_service.resolve(str(media.get("name") or ""))
        data = path.read_bytes()
    except Exception:
        return b""
    return data if len(data) >= 32 else b""


def _svc(session) -> CampaignService:
    return CampaignService(CampaignRepository(session), AssetRepository(session), CopyRepository(session))


# Instagram output sizes; the seller picks one, the export is exactly this box.
ASPECT_SIZES = {
    "post": (1080, 1350),
    "square": (1080, 1080),
    "story": (1080, 1920),
}
RAW_NAMES = {"post": "feed.png", "square": "square.png", "story": "story.png"}
OUT_NAMES = {"post": "ig-post.png", "square": "ig-feed.png", "story": "ig-story.png"}


def start(
    *,
    message_id: str,
    campaign_id: str,
    media: dict | None = None,
    title: str = "",
    image_prompt: str = "",
    width: int = 1080,
    height: int = 1080,
    aspect: str = "",
    edit: bool = False,
    edit_kind: str = "",
    subject: str = "",
) -> str:
    from app.services import studio_chat_service

    job_id = str(uuid4())
    studio_chat_service.set_compose(
        message_id,
        {"status": "running", "stage": "photo", "startedAt": time.time(), "jobId": job_id},
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
    if aspect in ASPECT_SIZES:
        width, height = ASPECT_SIZES[aspect]
    kwargs = {
        "tenant": tenant,
        "aspect": aspect if aspect in ASPECT_SIZES else "post",
        "message_id": message_id,
        "campaign_id": campaign_id,
        "media": media,
        "title": title,
        "image_prompt": image_prompt,
        "job_id": job_id,
        "started": time.time(),
        "width": width,
        "height": height,
        "edit": edit,
        "edit_kind": edit_kind,
        "subject": subject,
    }
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_run(**kwargs))
        _COMPOSE_TASKS.add(task)
        task.add_done_callback(_COMPOSE_TASKS.discard)
    except RuntimeError:
        thread = threading.Thread(target=lambda: asyncio.run(_run(**kwargs)), daemon=True)
        _COMPOSE_THREADS.add(thread)
        thread.start()
    return job_id


async def drain() -> None:
    tasks = [task for task in list(_COMPOSE_TASKS) if not task.done()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    for thread in list(_COMPOSE_THREADS):
        if thread.is_alive():
            await asyncio.to_thread(thread.join, 600)


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
    width: int = 1080,
    height: int = 1080,
    aspect: str = "post",
    edit: bool = False,
    edit_kind: str = "",
    subject: str = "",
) -> None:
    from app.services import studio_chat_service

    with tenant_scope(tenant):
        try:
            async with SessionLocal() as session:
                campaigns = _svc(session)
                cid = UUID(campaign_id)
                source = _media_bytes(media)
                prompt = (image_prompt or "").strip()

                def _touch() -> None:
                    studio_chat_service.touch_compose_start(message_id, job_id)

                save = False
                png = b""
                scene = (edit_kind or "") == "scene"
                if source and not scene:
                    png = await asyncio.to_thread(
                        _generate_still_locked,
                        prompt or "soft studio surface",
                        width,
                        height,
                        _touch,
                        source,
                        False,
                        subject,
                        "background",
                    )
                    save = True
                elif source and scene:
                    png = await asyncio.to_thread(
                        _generate_still_locked,
                        prompt or "keep the same product",
                        width,
                        height,
                        _touch,
                        source,
                        True,
                        subject,
                        "scene",
                    )
                    save = True
                else:
                    attached = await studio_chat_service.attach_still(campaigns, cid, media)
                    if not attached:
                        if not prompt:
                            raise RuntimeError("still-failed")
                        png = await asyncio.to_thread(
                            _generate_still_locked,
                            prompt,
                            width,
                            height,
                            _touch,
                            None,
                            False,
                            subject,
                            "",
                        )
                        save = True
                if save:
                    if len(png) < 2048:
                        from app.services.image_provider_service import last_error

                        if last_error == "subject":
                            raise RuntimeError("subject-failed")
                        raise RuntimeError("still-failed")
                    from app.services import image_provider_service

                    if image_provider_service.last_closeup:
                        studio_chat_service.append_note(message_id, studio_chat_service.CLOSEUP_PHOTO)
                    await campaigns.save_raw(cid, RAW_NAMES.get(aspect, "feed.png"), png)
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
                studio_chat_service.mark_compose_stage(message_id, "layout")
                await campaigns.compose(cid)
                outputs = await campaigns.preview_outputs(cid)
                wanted = OUT_NAMES.get(aspect, "ig-post.png")
                matched = [row for row in outputs if str(row.get("name") or "") == wanted]
                attachments = studio_chat_service.copy_outputs(matched or outputs)
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
            if "subject-failed" in str(exc):
                from app.services.image_provider_service import SUBJECT_FAIL

                error = SUBJECT_FAIL
            elif "still-failed" in str(exc) or "تصویر خام" in detail:
                from app.services.image_provider_service import FAIL_TEXT

                error = FAIL_TEXT
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
