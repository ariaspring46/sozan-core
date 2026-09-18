from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.repositories.campaign_repository import AssetRepository, CampaignRepository, CopyRepository
from app.schemas import CampaignCreateIn, CampaignOut, CampaignUpdateIn, ImportSlugIn
from app.security import require_permission
from app.services.campaign_service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _svc(session: AsyncSession = Depends(get_session)) -> CampaignService:
    return CampaignService(CampaignRepository(session), AssetRepository(session), CopyRepository(session))


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    _user=Depends(require_permission("campaigns:read")),
    service: CampaignService = Depends(_svc),
):
    return await service.list_campaigns()


@router.post("", response_model=CampaignOut)
async def create_campaign(
    body: CampaignCreateIn,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    return await service.create(**body.model_dump())


@router.post("/import", response_model=CampaignOut)
async def import_campaign(
    body: ImportSlugIn,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    return await service.import_disk_slug(body.slug)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: UUID,
    _user=Depends(require_permission("campaigns:read")),
    service: CampaignService = Depends(_svc),
):
    return await service.get(campaign_id)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdateIn,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    return await service.update_copy(campaign_id, **body.model_dump())


@router.post("/{campaign_id}/raw", response_model=CampaignOut)
async def upload_raw(
    campaign_id: UUID,
    file: UploadFile = File(...),
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    data = await file.read()
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام فایل لازم است")
    await service.save_raw(campaign_id, file.filename, data)
    return await service.get(campaign_id)


@router.post("/{campaign_id}/compose", response_model=CampaignOut)
async def compose(
    campaign_id: UUID,
    _user=Depends(require_permission("campaigns:write")),
    service: CampaignService = Depends(_svc),
):
    return await service.compose(campaign_id)


@router.get("/{campaign_id}/export")
async def export_pack(
    campaign_id: UUID,
    _user=Depends(require_permission("campaigns:export")),
    service: CampaignService = Depends(_svc),
):
    archive = await service.export_zip(campaign_id)
    return FileResponse(archive, filename=archive.name, media_type="application/zip")


@router.get("/{campaign_id}/file/{rel_path:path}")
async def campaign_file(
    campaign_id: UUID,
    rel_path: str,
    _user=Depends(require_permission("campaigns:read")),
    service: CampaignService = Depends(_svc),
):
    campaign = await service.get(campaign_id)
    if not rel_path.startswith(campaign.slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مسیر مال این کمپین نیست")
    path = service.resolve_file(rel_path)
    media = "image/png" if path.suffix.lower() == ".png" else None
    if path.suffix.lower() == ".mp4":
        media = "video/mp4"
    if path.suffix.lower() == ".md":
        media = "text/markdown; charset=utf-8"
    return FileResponse(path, media_type=media)
