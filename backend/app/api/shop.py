import asyncio

from pydantic import BaseModel, Field

from app.api.chat_payload import read_chat_payload
from app.security import require_permission
from app.services import idempotency_service, onboard_service, shop_service
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

router = APIRouter(prefix="/shop", tags=["shop"])


class DomainIn(BaseModel):
    domain: str = Field(default="", max_length=200)


class BuildIn(BaseModel):
    prompt: str = Field(default="", max_length=4000)
    rebuild: bool = False
    reviseOnly: bool = False


@router.get("")
async def get_shop(_user=Depends(require_permission("campaigns:read"))):
    return await asyncio.to_thread(shop_service.snapshot)


def _idempotency_key(request: Request) -> str:
    return (request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key") or "").strip()


@router.post("/chat")
async def shop_chat(request: Request, _user=Depends(require_permission("campaigns:write"))):
    key = _idempotency_key(request)
    raw = await request.body()
    stamp = idempotency_service.body_stamp(raw)
    cached = idempotency_service.recall("shop-chat", key, stamp)
    if cached is not None:
        return cached
    text, media, view_path, view_target, _confirm, _cancel, _thread = await read_chat_payload(request)
    out = await shop_service.chat(text, media, view_path, view_target)
    idempotency_service.put("shop-chat", key, out, stamp)
    return out


@router.patch("/domain")
async def shop_domain(body: DomainIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return shop_service.set_domain(body.domain)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/build")
async def shop_build(request: Request, body: BuildIn, _user=Depends(require_permission("campaigns:write"))):
    key = _idempotency_key(request)
    raw = await request.body()
    stamp = idempotency_service.body_stamp(raw)
    cached = idempotency_service.recall("shop-build", key, stamp)
    if cached is not None:
        return cached
    shop = (await asyncio.to_thread(shop_service.snapshot))["shop"]
    if not shop.get("slug") and not onboard_service.brief_ready():
        return {
            "result": {"ok": False, "error": "اول در چت بگو چه سایتی می‌خواهی؛ سبک و رنگ لازم است."},
            **(await asyncio.to_thread(shop_service.snapshot)),
        }
    result = await asyncio.to_thread(
        shop_service.start_build,
        prompt=body.prompt or shop.get("brand") or "",
        rebuild=bool(body.rebuild and shop.get("slug")),
        revise_only=True if body.reviseOnly else (False if body.rebuild else None),
    )
    out = {"result": result, **(await asyncio.to_thread(shop_service.snapshot))}
    idempotency_service.put("shop-build", key, out, stamp)
    return out


@router.post("/undo")
async def shop_undo(request: Request, _user=Depends(require_permission("campaigns:write"))):
    key = _idempotency_key(request)
    stamp = idempotency_service.body_stamp(await request.body())
    cached = idempotency_service.recall("shop-undo", key, stamp)
    if cached is not None:
        return cached
    out = await asyncio.to_thread(shop_service.undo_edit)
    idempotency_service.put("shop-undo", key, out, stamp)
    return out


@router.post("/image")
async def shop_image(
    file: UploadFile = File(...),
    src: str = Form("", max_length=2000),
    _user=Depends(require_permission("campaigns:write")),
):
    data = await file.read()
    try:
        return await asyncio.to_thread(shop_service.replace_image, data, file.content_type or "", file.filename or "photo.jpg", src)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
