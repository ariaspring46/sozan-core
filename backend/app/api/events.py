from fastapi import APIRouter, Depends

from app.security import require_permission
from app.services import seller_events

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/unseen")
async def events_unseen(_user=Depends(require_permission("campaigns:read"))):
    """How many things Sozan said on her own since the seller last opened the chat (the chat tab badge)."""
    return {"count": seller_events.unseen()}


@router.post("/seen")
async def events_seen(_user=Depends(require_permission("campaigns:read"))):
    seller_events.mark_seen()
    return {"count": 0}
