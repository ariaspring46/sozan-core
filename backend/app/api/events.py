from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.security import require_permission
from app.services import seller_alerts, seller_events

router = APIRouter(prefix="/events", tags=["events"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=10, max_length=60)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: PushKeys


class PushEndpointIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


@router.get("/unseen")
async def events_unseen(_user=Depends(require_permission("campaigns:read"))):
    """How many things Sozan said on her own since the seller last opened the chat (the chat tab badge)."""
    return {"count": seller_events.unseen()}


@router.post("/seen")
async def events_seen(_user=Depends(require_permission("campaigns:read"))):
    seller_events.mark_seen()
    return {"count": 0}


@router.get("/push")
async def push_state(_user=Depends(require_permission("campaigns:read"))):
    return {"publicKey": seller_alerts.public_key(), "devices": seller_alerts.devices()}


@router.post("/push/subscribe")
async def push_subscribe(body: PushSubscriptionIn, request: Request, _user=Depends(require_permission("campaigns:write"))):
    try:
        count = seller_alerts.subscribe(body.endpoint, body.keys.p256dh, body.keys.auth, request.headers.get("user-agent", ""))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"devices": count}


@router.post("/push/unsubscribe")
async def push_unsubscribe(body: PushEndpointIn, _user=Depends(require_permission("campaigns:write"))):
    return {"devices": seller_alerts.unsubscribe(body.endpoint)}


@router.post("/push/test")
async def push_test(_user=Depends(require_permission("campaigns:write"))):
    return await seller_alerts.push("سوزان", "اعلان سوزان روشن است؛ سفارش و رسید تازه همین‌جا خبر داده می‌شود.", url="/chat", tag="test")
