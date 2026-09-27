from contextlib import asynccontextmanager

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.brand import router as brand_router
from app.api.campaigns import router as campaigns_router
from app.api.channels import router as channels_router
from app.api.chat_media import router as chat_media_router
from app.api.router_chat import router as chat_router
from app.api.inbox import router as inbox_router
from app.api.onboard import router as onboard_router
from app.api.public_media import router as public_media_router
from app.api.settings import router as settings_router
from app.api.shop import router as shop_router
from app.api.storefront import router as storefront_router
from app.api.studio import router as studio_router
from app.api.pay import router as pay_router
from app.api.wallet import router as wallet_router
from app.config import settings
from app.database import Base, engine
from app.models import Asset, Campaign, CopyVariant, User  # noqa: F401

log = logging.getLogger("sozan")


async def _channel_poll_loop() -> None:
    from app.services import channel_poll_service

    await asyncio.sleep(4)
    while True:
        try:
            await channel_poll_service.poll_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("channel poll failed")
        await asyncio.sleep(4)


async def _housekeeping_loop() -> None:
    from app.services import inbox_service, studio_compose_service
    from app.state_store import iter_tenants, tenant_scope

    await asyncio.sleep(20)
    while True:
        try:
            for phone in iter_tenants():
                with tenant_scope(phone):
                    studio_compose_service.expire_stale()
                    inbox_service.expire_stale_sending()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("housekeeping failed")
        await asyncio.sleep(60)


async def _rearm_inbox() -> None:
    from app.services import inbox_service
    from app.state_store import iter_tenants, tenant_scope

    for phone in iter_tenants():
        try:
            with tenant_scope(phone):
                await inbox_service.rearm_pending_auto_replies()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("inbox rearm failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.tenant_migrate import migrate_campaign_ids, migrate_files

    migrate_files()
    await migrate_campaign_ids()
    from app.services import router_service

    router_service.clear_dead_busy()
    from app.services.loop_watch import start as start_loop_watch

    poller = asyncio.create_task(_channel_poll_loop())
    housekeeper = asyncio.create_task(_housekeeping_loop())
    rearm = asyncio.create_task(_rearm_inbox())
    loop_watch = start_loop_watch()
    from app.services import image_provider_service, llm_routing_service

    probe_task = asyncio.create_task(image_provider_service.probe_ollama_cloud_once())
    router_task = asyncio.create_task(llm_routing_service.refresh_loop())
    yield
    poller.cancel()
    housekeeper.cancel()
    rearm.cancel()
    probe_task.cancel()
    router_task.cancel()
    loop_watch.cancel()
    for task in (poller, housekeeper, rearm, probe_task, router_task, loop_watch):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await engine.dispose()


app = FastAPI(title="Sozan Ads", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(onboard_router)
app.include_router(brand_router)
app.include_router(campaigns_router)
app.include_router(shop_router)
app.include_router(chat_router)
app.include_router(studio_router)
app.include_router(settings_router)
app.include_router(channels_router)
app.include_router(inbox_router)
app.include_router(chat_media_router)
app.include_router(public_media_router)
app.include_router(storefront_router)
app.include_router(pay_router)
app.include_router(wallet_router)


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return RedirectResponse("https://app.sozan-core.ir/login", status_code=302)


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health():
    from app.services.payment_service import hub_payments_open

    return {"ok": True, "paymentReady": bool(hub_payments_open())}
