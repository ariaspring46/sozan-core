import json

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.client_ip import client_ip
from app.security import require_permission
from app.services import pay_service

router = APIRouter(tags=["pay"])


class ShopLine(BaseModel):
    productId: str = Field(default="", max_length=80)
    qty: int = Field(default=0, ge=0, le=99)


class ShopCheckoutIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    secret: str = Field(min_length=8, max_length=80)
    name: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=20)
    lines: list[ShopLine] = Field(default_factory=list)


class ShopOtpSendIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=8, max_length=20)


class ShopOtpVerifyIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=8, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class TicketIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=8, max_length=20)
    otpToken: str = Field(min_length=10, max_length=160)
    subject: str = Field(min_length=2, max_length=120)
    orderNo: str = Field(default="", max_length=40)
    text: str = Field(min_length=2, max_length=2000)


@router.get("/p/catalog-ids")
async def catalog_ids(
    slug: str = Query(default=""),
    secret: str = Query(default=""),
    x_sozan_store_secret: str = Header(default=""),
):
    secret = x_sozan_store_secret or secret
    try:
        return pay_service.catalog_ids(slug=slug, secret=secret)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/p/shop-config")
async def shop_config(
    slug: str = Query(default=""),
    secret: str = Query(default=""),
    x_sozan_store_secret: str = Header(default=""),
):
    secret = x_sozan_store_secret or secret
    try:
        return pay_service.shop_config(slug=slug, secret=secret)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/p/orders/{order_no}/receipt")
async def order_receipt(
    order_no: str,
    request: Request,
    slug: str = Form(default=""),
    secret: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    try:
        return await pay_service.attach_receipt(slug=slug, secret=secret, order_no=order_no, upload=file)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/p/tickets")
async def storefront_ticket(
    request: Request,
    slug: str = Form(default=""),
    phone: str = Form(default=""),
    otpToken: str = Form(default=""),
    subject: str = Form(default=""),
    orderNo: str = Form(default=""),
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    from app.services import shop_otp_service, support_service
    from app.state_store import tenant_scope

    tenant = pay_service.find_tenant_by_slug(slug)

    if not shop_otp_service.valid_buyer_token(otpToken, slug=slug, phone=phone):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "تأیید شماره لازم است")
    if not tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "فروشگاه پیدا نشد")
    image_name = ""
    if file is not None and file.filename and file.size != 0:
        data = await file.read()
        if len(data) > 4_000_000:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "عکس بزرگ‌تر از حد مجاز است")
        if data:
            from app.services import chat_media_service

            with tenant_scope(tenant):
                saved = chat_media_service.save(file.filename, data, file.content_type or "")
                image_name = str(saved.get("name") or "")
    with tenant_scope(tenant):
        out = support_service.create_ticket(
            subject=subject, text=text, phone=phone, order_no=orderNo, image_name=image_name
        )
    return out


@router.get("/pay/receipts")
async def panel_receipts(_user=Depends(require_permission("campaigns:write"))):
    return {"receipts": pay_service.list_receipts()}


@router.post("/pay/receipts/{order_no}/review")
async def panel_review_receipt(
    order_no: str,
    body: dict,
    _user=Depends(require_permission("campaigns:write")),
):
    try:
        approve = body.get("approve")
        if approve is None:
            approve = body.get("decision")
        return pay_service.review_receipt(
            order_no=order_no,
            approve=bool(approve) if approve is not None else None,
            note=str(body.get("note") or ""),
            decision=str(body.get("decision") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/support/tickets")
async def panel_tickets(_user=Depends(require_permission("campaigns:read"))):
    from app.services import support_service

    return {"tickets": support_service.list_tickets(kind="storefront")}


@router.post("/support/tickets/{ticket_id}/reply")
async def panel_ticket_reply(
    ticket_id: str,
    body: dict,
    _user=Depends(require_permission("campaigns:write")),
):
    from app.services import support_service

    try:
        return support_service.reply_ticket(
            ticket_id, text=str(body.get("text") or ""), status=str(body.get("status") or "")
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/p/shop/checkout")
async def shop_checkout(request: Request, body: ShopCheckoutIn):
    try:
        return await pay_service.shop_checkout(
            slug=body.slug,
            secret=body.secret,
            name=body.name,
            phone=body.phone,
            lines=[item.model_dump() for item in body.lines],
            ip=client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/p/shop/paid")
async def shop_paid(request: Request, x_sozan_sign: str = Header(default="")):
    raw = await request.body()
    if not pay_service.valid_sign(raw, x_sozan_sign):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "امضای وب‌هوک نادرست است")
    try:
        payload = json.loads(raw.decode() or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "بدنه نامعتبر است") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "بدنه نامعتبر است")
    try:
        return pay_service.shop_paid(
            slug=str(payload.get("slug") or ""),
            order_id=str(payload.get("orderId") or ""),
            amount=int(payload.get("amount") or 0),
            title=str(payload.get("title") or ""),
            customer=str(payload.get("customer") or ""),
            ref_id=str(payload.get("refId") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/p/otp/send")
async def shop_otp_send(request: Request, body: ShopOtpSendIn):
    from app.services import shop_otp_service

    try:
        return await shop_otp_service.send(
            slug=body.slug, phone=body.phone, ip=client_ip(request)
        )
    except shop_otp_service.OtpLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/p/otp/verify")
async def shop_otp_verify(body: ShopOtpVerifyIn):
    from app.services import shop_otp_service

    try:
        return await shop_otp_service.verify(slug=body.slug, phone=body.phone, code=body.code)
    except shop_otp_service.OtpLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/p/{order_id}/status")
async def pay_status(order_id: str):
    found = pay_service.locate_order(order_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "سفارش پیدا نشد")
    _phone, row = found
    return pay_service.public_order(row)


@router.get("/p/{order_id}")
async def start_pay(order_id: str):
    try:
        url = pay_service.start_url(order_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "سفارش پیدا نشد") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/pay/zarinpal/callback")
async def zarinpal_sale_callback(
    authority: str = Query(default="", alias="Authority"),
    pay_status: str = Query(default="", alias="Status"),
):
    ok = pay_status.upper() == "OK" and bool(authority.strip())
    url = await pay_service.finish_order(authority=authority.strip(), ok=ok, gateway="zarinpal")
    return RedirectResponse(url, status_code=302)


@router.api_route("/pay/idpay/callback", methods=["GET", "POST"])
async def idpay_sale_callback(request: Request):
    payload = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        payload.update({str(key): str(value) for key, value in form.items()})
        try:
            body = await request.json()
            if isinstance(body, dict):
                payload.update({str(key): str(value) for key, value in body.items()})
        except Exception:
            pass
    authority = str(payload.get("id") or "").strip()
    status_code = str(payload.get("status") or "")
    ok = status_code in {"10", "100", "200"} and bool(authority)
    url = await pay_service.finish_order(authority=authority, ok=ok, gateway="idpay")
    return RedirectResponse(url, status_code=302)


@router.get("/wallet/orders")
async def list_pay_orders(_user=Depends(require_permission("campaigns:read"))):
    return {"orders": pay_service.list_orders()}
