from pydantic import BaseModel, Field

from app.security import require_permission
from app.services import (
    channel_connect_service,
    channel_scan_service,
    channel_service,
    instagram_oauth_service,
    instagram_service,
    plan_service,
    sendbox_service,
    telegram_service,
    unipile_service,
    voice_service,
)
from app.state_store import current_tenant
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/channels", tags=["channels"])


class ChannelIn(BaseModel):
    platform: str = Field(min_length=2, max_length=32)
    handle: str = Field(default="", max_length=200)
    secret: str = Field(default="", max_length=2000)
    credentials: dict[str, str] = Field(default_factory=dict)
    samples: str = Field(default="", max_length=4000)


class SendboxClaimIn(BaseModel):
    accountId: str = Field(min_length=4, max_length=80)
    handle: str = Field(default="", max_length=200)


class UnipileClaimIn(BaseModel):
    accountId: str = Field(min_length=4, max_length=80)


def _with_oauth(payload: dict) -> dict:
    platforms = []
    for spec in payload.get("platforms") or []:
        item = dict(spec)
        if item.get("id") == "instagram":
            item["oauth"] = True
            item["oauthConfigured"] = instagram_oauth_service.configured()
            item["unipileConfigured"] = unipile_service.configured()
            item["sendboxConfigured"] = sendbox_service.configured()
        platforms.append(item)
    return {**payload, "platforms": platforms}


async def _after_connect(account: dict, *, samples: str, row: dict) -> dict:
    voice = await voice_service.learn(
        platform=str(account.get("platform") or ""),
        handle=str(account.get("handle") or ""),
        samples=samples,
    )
    channel_service.mark_voice(str(account.get("id") or ""))
    extra: dict = {"voice": voice}
    token = channel_service.token_for(row)
    platform = str(account.get("platform") or "")
    handle = str(account.get("handle") or "")
    if platform == "instagram" and (
        token or channel_service.unipile_account_id(row) or channel_service.sendbox_account_id(row)
    ):
        if not plan_service.current()["dmSync"]:
            extra["instagram"] = {
                "ok": False,
                "imported": 0,
                "error": "خواندن دایرکت روی پلن پرو و پرو مکس است.",
            }
        else:
            unipile_id = channel_service.unipile_account_id(row)
            sendbox_id = channel_service.sendbox_account_id(row)
            if sendbox_id:
                extra["instagram"] = {"ok": True, "imported": 0, "webhook": True}
            elif unipile_id:
                extra["instagram"] = await unipile_service.pull_directs(account_id=unipile_id, handle=handle)
            else:
                extra["instagram"] = await instagram_service.pull_directs(token=token, handle=handle)
    if platform == "telegram" and token:
        extra["telegram"] = await telegram_service.pull_updates(token=token, handle=handle)
    return extra


@router.get("")
async def list_channels(_user=Depends(require_permission("campaigns:read"))):
    return {**_with_oauth(channel_service.list_accounts()), "voice": voice_service.get_voice()}


@router.get("/instagram/connect")
async def instagram_connect_start(_user=Depends(require_permission("campaigns:write"))):
    try:
        phone = current_tenant()
        if sendbox_service.configured():
            return await sendbox_service.start_instagram(phone=phone)
        if unipile_service.configured():
            return await unipile_service.start_instagram(phone=phone)
        return await instagram_oauth_service.start_login(phone=phone)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/unipile/connect")
async def unipile_connect_start(_user=Depends(require_permission("campaigns:write"))):
    try:
        return await unipile_service.start_instagram(phone=current_tenant())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/sendbox/accounts")
async def sendbox_accounts(_user=Depends(require_permission("campaigns:read"))):
    try:
        rows = sendbox_service.unused_remote_accounts(
            await sendbox_service.list_remote_accounts(), phone=current_tenant()
        )
    except Exception:
        rows = []
    return {"accounts": rows}


@router.get("/instagram/oauth")
async def instagram_oauth_start(_user=Depends(require_permission("campaigns:write"))):
    try:
        return await instagram_oauth_service.start_login(phone=current_tenant())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/instagram/callback")
async def instagram_oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
):
    url = await instagram_oauth_service.finish_redirect(code=code, state=state, error=error)
    return RedirectResponse(url, status_code=302)


@router.get("/sendbox/callback")
async def sendbox_callback(
    status: str = Query(default=""),
    account_id: str = Query(default=""),
    username: str = Query(default=""),
    id: str = Query(default=""),
    error: str = Query(default=""),
):
    url = sendbox_service.finish_redirect(
        status=status,
        account_id=account_id,
        username=username,
        seller_id=id,
        error=error,
    )
    return RedirectResponse(url, status_code=302)


@router.post("/sendbox/webhook")
async def sendbox_webhook(request: Request, token: str = Query(default="")):
    if not sendbox_service.valid_webhook_token(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "وب‌هوک Sendbox نامعتبر است")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return await sendbox_service.accept_webhook(payload if isinstance(payload, dict) else {})


@router.post("/sendbox/claim")
async def sendbox_claim(body: SendboxClaimIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return _with_oauth(
            await sendbox_service.claim_account(
                account_id=body.accountId, phone=current_tenant(), handle=body.handle
            )
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/unipile/webhook")
async def unipile_webhook(request: Request, token: str = Query(default="")):
    auth = (request.headers.get("Unipile-Auth") or request.headers.get("unipile-auth") or "").strip()
    if not unipile_service.valid_webhook_token(token) and not unipile_service.valid_webhook_token(auth):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "وب‌هوک یونى‌پایل نامعتبر است")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "وب‌هوک یونى‌پایل خوانده نشد") from exc
    return await unipile_service.accept_webhook(payload if isinstance(payload, dict) else {})


@router.post("/unipile/notify")
async def unipile_notify(
    request: Request,
    token: str = Query(default=""),
    tenant: str = Query(default=""),
):
    if not unipile_service.valid_notify_token(token, phone=tenant):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "اعلان یونى‌پایل نامعتبر است")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "اعلان یونى‌پایل خوانده نشد") from exc
    try:
        await unipile_service.accept_notify(payload if isinstance(payload, dict) else {}, phone=tenant)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"ok": True}


@router.post("/unipile/claim")
async def unipile_claim(body: UnipileClaimIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        return _with_oauth(await unipile_service.claim_account(account_id=body.accountId, phone=current_tenant()))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("")
async def add_channel(body: ChannelIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        result = channel_service.add_account(
            platform=body.platform,
            handle=body.handle,
            secret=body.secret,
            credentials=body.credentials,
        )
        row = channel_service.secret_for(str(result["account"]["id"])) or {}
        probe = await channel_connect_service.verify_credentials(
            platform=str(result["account"].get("platform") or ""),
            handle=str(result["account"].get("handle") or ""),
            credentials=channel_service.credentials_for(row),
        )
        if probe.get("ok") is False:
            channel_service.remove_account(str(result["account"]["id"]))
            raise ValueError(str(probe.get("error") or "اتصال برقرار نشد"))
        account = channel_service.apply_verify(str(result["account"]["id"]), probe)
        extra = await _after_connect(account, samples=body.samples, row=row)
        scan = channel_scan_service.start_scan([{"platform": account.get("platform"), "handle": account.get("handle")}])
        return {**_with_oauth(channel_service.list_accounts()), "account": account, **extra, "scan": scan}
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{account_id}/sync")
async def sync_channel(account_id: str, _user=Depends(require_permission("campaigns:write"))):
    row = channel_service.secret_for(account_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "حساب پیدا نشد")
    platform = str(row.get("platform") or "")
    handle = str(row.get("handle") or "")
    if platform == "instagram":
        if not plan_service.current()["dmSync"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "خواندن دایرکت روی پلن پرو و پرو مکس است.")
        sendbox_id = channel_service.sendbox_account_id(row)
        if sendbox_id:
            return {"ok": True, "imported": 0, "webhook": True}
        unipile_id = channel_service.unipile_account_id(row)
        if unipile_id:
            return await unipile_service.pull_directs(account_id=unipile_id, handle=handle)
        await instagram_oauth_service.refresh_row(row)
        row = channel_service.secret_for(account_id) or row
        return await instagram_service.pull_directs(token=channel_service.token_for(row), handle=handle)
    if platform == "telegram":
        return await telegram_service.pull_updates(token=channel_service.token_for(row), handle=handle)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "همگام‌سازی این کانال هنوز وصل نیست")


class ChannelPatchIn(BaseModel):
    postTarget: str = Field(default="", max_length=200)


@router.patch("/{account_id}")
async def patch_channel(account_id: str, body: ChannelPatchIn, _user=Depends(require_permission("campaigns:write"))):
    try:
        account = channel_service.update_account(account_id, post_target=body.postTarget)
        return {**_with_oauth(channel_service.list_accounts()), "account": account}
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "حساب پیدا نشد") from exc


@router.delete("/{account_id}")
async def delete_channel(account_id: str, _user=Depends(require_permission("campaigns:write"))):
    return _with_oauth(channel_service.remove_account(account_id))
