import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

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


@router.post("/p/shop/checkout")
async def shop_checkout(body: ShopCheckoutIn):
    try:
        return await pay_service.shop_checkout(
            slug=body.slug,
            secret=body.secret,
            name=body.name,
            phone=body.phone,
            lines=[item.model_dump() for item in body.lines],
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
            slug=body.slug, phone=body.phone, ip=request.client.host if request.client else ""
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
