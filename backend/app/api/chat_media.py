from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.security import require_permission
from app.services import chat_media_service

router = APIRouter(prefix="/chat-media", tags=["chat-media"])

IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
VIDEO = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
AUDIO = {".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".webm": "audio/webm"}


@router.get("/{name}")
async def chat_media_file(name: str, _user=Depends(require_permission("campaigns:read"))):
    path = chat_media_service.resolve(name)
    suffix = Path(path.name).suffix.lower()
    kind = path.stem.rsplit("-", 1)[-1] if "-" in path.stem else ""
    if suffix in IMAGE:
        media = IMAGE[suffix]
    elif kind == "audio" and suffix in AUDIO:
        media = AUDIO[suffix]
    elif suffix in VIDEO:
        media = VIDEO[suffix]
    elif suffix in AUDIO:
        media = AUDIO[suffix]
    else:
        media = "application/octet-stream"
    return FileResponse(path, media_type=media)
