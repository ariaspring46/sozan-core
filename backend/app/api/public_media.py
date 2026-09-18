from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.services import public_media_service

router = APIRouter(tags=["public-media"])

IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
VIDEO = {".mp4": "video/mp4", ".webm": "video/webm"}


@router.get("/public-media/{token}")
async def public_media_file(token: str):
    path = public_media_service.resolve_token(token)
    suffix = Path(path.name).suffix.lower()
    media = IMAGE.get(suffix) or VIDEO.get(suffix) or "application/octet-stream"
    return FileResponse(path, media_type=media)
