from __future__ import annotations

import asyncio
import logging

from app.database import SessionLocal
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.services.campaign_service import CampaignService
from app.services.job_queue import pop
from app.services import router_service, studio_chat_service
from app.state_store import tenant_scope

log = logging.getLogger("sozan.worker")


async def handle(job: dict) -> None:
    tenant = str(job.get("tenant") or "")
    message_id = str(job.get("studioMessageId") or "")
    with tenant_scope(tenant):
        router_service._THREAD.set(str(job.get("thread") or ""))
        try:
            async with SessionLocal() as session:
                service = CampaignService(
                    CampaignRepository(session),
                    AssetRepository(session),
                    CopyRepository(session),
                )
                media = job.get("media") if isinstance(job.get("media"), dict) else None
                await studio_chat_service.chat(
                    str(job.get("spoken") or ""),
                    service,
                    media,
                    into_id=message_id,
                )
        except Exception:
            log.exception("studio job failed")
            if message_id:
                studio_chat_service.finish_compose(
                    message_id,
                    [],
                    status="failed",
                    error="ساخت انجام نشد. دوباره بگو.",
                    job_id=message_id,
                )


async def loop() -> None:
    while True:
        try:
            job = await pop(5)
        except Exception:
            log.exception("studio queue unreachable")
            await asyncio.sleep(2)
            continue
        if job:
            await handle(job)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(loop())


if __name__ == "__main__":
    main()
