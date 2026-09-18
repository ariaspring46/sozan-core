from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.repositories.brand_repository import BrandRepository
from app.security import require_permission
from app.services.brand_service import BrandService
from app.state_store import brand_dir

router = APIRouter(prefix="/brand", tags=["brand"])


class BrandOut(BaseModel):
    name: str
    description: str
    has_logo: bool
    has_character: bool
    has_motion: bool = False


class BrandUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None


def _svc() -> BrandService:
    return BrandService(BrandRepository(brand_dir(), settings.fonts_path))


@router.get("", response_model=BrandOut)
async def get_brand(
    _user=Depends(require_permission("campaigns:read")),
    service: BrandService = Depends(_svc),
):
    return service.get()


@router.patch("", response_model=BrandOut)
async def update_brand(
    body: BrandUpdateIn,
    _user=Depends(require_permission("campaigns:write")),
    service: BrandService = Depends(_svc),
):
    return service.update(**body.model_dump())


@router.post("/logo", response_model=BrandOut)
async def upload_logo(
    file: UploadFile = File(...),
    _user=Depends(require_permission("campaigns:write")),
    service: BrandService = Depends(_svc),
):
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام فایل لازم است")
    data = await file.read()
    return service.save_logo(file.filename, data)


@router.get("/logo")
async def brand_logo(
    _user=Depends(require_permission("campaigns:read")),
    service: BrandService = Depends(_svc),
):
    path = service.logo_file()
    return FileResponse(path, media_type="image/png")


@router.post("/character", response_model=BrandOut)
async def upload_character(
    file: UploadFile = File(...),
    _user=Depends(require_permission("campaigns:write")),
    service: BrandService = Depends(_svc),
):
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام فایل لازم است")
    data = await file.read()
    return service.save_character(file.filename, data)


@router.get("/character")
async def brand_character(
    _user=Depends(require_permission("campaigns:read")),
    service: BrandService = Depends(_svc),
):
    path = service.character_file()
    return FileResponse(path, media_type="image/png")


@router.post("/logo-motion")
async def make_logo_motion(
    _user=Depends(require_permission("campaigns:write")),
    service: BrandService = Depends(_svc),
):
    return service.make_logo_motion()


@router.get("/motion/{name}")
async def brand_motion(
    name: str,
    _user=Depends(require_permission("campaigns:read")),
    service: BrandService = Depends(_svc),
):
    path = service.motion_file(name)
    return FileResponse(path, media_type="video/mp4")
