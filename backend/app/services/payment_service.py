from __future__ import annotations

import re

import httpx

from app.config import settings as env

GATEWAYS = (
    {
        "id": "mock",
        "label": "ثبت دستی / بدون درگاه",
        "docs": "",
        "help": "فروش را خودت در بخش فروش ثبت می‌کنی. برای دریافت آنلاین، زرین‌پال یا آیدی‌پی را انتخاب کن.",
    },
    {
        "id": "zarinpal",
        "label": "زرین‌پال",
        "docs": "https://www.zarinpal.com/docs/paymentGateway/connectToGateway",
        "help": "مرچنت شخصی کمیسیون ندارد و پول در حساب خودت می‌ماند. اگر خالی باشد لینک پرداخت روی درگاه سوزان می‌رود و ۲٪ کم می‌شود.",
    },
    {
        "id": "idpay",
        "label": "آیدی‌پی",
        "docs": "https://idpay.ir/web-service/v1.1/",
        "help": "کلید شخصی آیدی‌پی کمیسیون ندارد. اگر نباشد، لینک پرداخت روی زرین‌پال سوزان با ۲٪ می‌رود.",
    },
)

_MERCHANT = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


PAYMENT_LATER = "پرداخت به‌زودی فعال می‌شود"


def payments_enabled() -> bool:
    return bool(env.payments_enabled)


def hub_payments_open() -> bool:
    if not payments_enabled():
        return False
    return bool(merchant_id())


def merchant_id(row: dict | None = None) -> str:
    current = str((row or {}).get("paymentMerchantId") or "").strip()
    if current:
        return current
    return str(env.zarinpal_merchant_id or "").strip()


def to_gateway_amount(toman: int) -> int:
    amount = int(toman)
    if amount <= 0:
        raise ValueError("مبلغ پرداخت نامعتبر است")
    unit = str(env.zarinpal_amount_unit or "rial").strip().lower()
    return amount * 10 if unit == "rial" else amount


def start_pay_url(authority: str) -> str:
    return f"https://payment.zarinpal.com/pg/StartPay/{authority}"


async def zarinpal_request(
    *,
    amount_toman: int,
    description: str,
    callback_url: str,
    mobile: str = "",
    merchant: str = "",
) -> dict:
    merchant = (merchant or merchant_id()).strip()
    if not merchant:
        raise ValueError("مرچنت‌آیدی زرین‌پال روی هاب تنظیم نشده.")
    payload = {
        "merchant_id": merchant,
        "amount": to_gateway_amount(amount_toman),
        "callback_url": callback_url,
        "description": (description or "پرداخت سوزان")[:255],
    }
    if mobile:
        payload["metadata"] = {"mobile": mobile}
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        response = await client.post(
            "https://payment.zarinpal.com/pg/v4/payment/request.json",
            headers={"content-type": "application/json", "accept": "application/json"},
            json=payload,
        )
    body = _json(response)
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    authority = str(data.get("authority") or "").strip()
    if response.status_code >= 400 or data.get("code") != 100 or not authority:
        raise ValueError("درگاه زرین‌پال درخواست را نپذیرفت.")
    return {"authority": authority, "startPayUrl": start_pay_url(authority), "merchant": merchant}


async def zarinpal_verify(*, amount_toman: int, authority: str, merchant: str = "") -> dict:
    merchant = (merchant or merchant_id()).strip()
    if not merchant:
        raise ValueError("مرچنت‌آیدی زرین‌پال روی هاب تنظیم نشده.")
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        response = await client.post(
            "https://payment.zarinpal.com/pg/v4/payment/verify.json",
            headers={"content-type": "application/json", "accept": "application/json"},
            json={
                "merchant_id": merchant,
                "amount": to_gateway_amount(amount_toman),
                "authority": authority,
            },
        )
    body = _json(response)
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    code = data.get("code")
    if response.status_code >= 400 or code not in {100, 101}:
        raise ValueError("تأیید پرداخت زرین‌پال ناموفق بود.")
    return {"ok": True, "refId": str(data.get("ref_id") or ""), "code": code}


async def idpay_request(
    *,
    amount_toman: int,
    description: str,
    callback_url: str,
    order_id: str,
    api_key: str,
    sandbox: bool = False,
    name: str = "",
    phone: str = "",
) -> dict:
    key = api_key.strip()
    if not key:
        raise ValueError("کلید آیدی‌پی را در تنظیمات بگذار.")
    headers = {"X-API-KEY": key, "Content-Type": "application/json", "Accept": "application/json"}
    if sandbox:
        headers["X-SANDBOX"] = "1"
    payload = {
        "order_id": order_id,
        "amount": to_gateway_amount(amount_toman),
        "callback": callback_url,
        "desc": (description or "پرداخت سوزان")[:255],
    }
    if name:
        payload["name"] = name[:255]
    if phone:
        payload["phone"] = phone
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        response = await client.post("https://api.idpay.ir/v1.1/payment", headers=headers, json=payload)
    body = _json(response)
    pay_id = str(body.get("id") or "").strip()
    link = str(body.get("link") or "").strip()
    if response.status_code >= 400 or not pay_id or not link:
        raise ValueError("درگاه آیدی‌پی درخواست را نپذیرفت.")
    return {"authority": pay_id, "startPayUrl": link}


async def idpay_verify(
    *,
    order_id: str,
    authority: str,
    api_key: str,
    sandbox: bool = False,
    amount_toman: int = 0,
) -> dict:
    key = api_key.strip()
    if not key:
        raise ValueError("کلید آیدی‌پی را در تنظیمات بگذار.")
    expected = to_gateway_amount(amount_toman)
    headers = {"X-API-KEY": key, "Content-Type": "application/json", "Accept": "application/json"}
    if sandbox:
        headers["X-SANDBOX"] = "1"
    async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
        response = await client.post(
            "https://api.idpay.ir/v1.1/payment/verify",
            headers=headers,
            json={"id": authority, "order_id": order_id, "amount": expected},
        )
    body = _json(response)
    status_code = body.get("status")
    if response.status_code >= 400 or status_code not in {100, 101, 200}:
        raise ValueError("تأیید پرداخت آیدی‌پی ناموفق بود.")
    payment = body.get("payment") if isinstance(body.get("payment"), dict) else {}
    paid = body.get("amount")
    if paid is None:
        paid = payment.get("amount")
    try:
        paid_amount = int(paid)
    except (TypeError, ValueError):
        paid_amount = -1
    if paid_amount != expected:
        raise ValueError("مبلغ تأیید آیدی‌پی با سفارش یکی نیست.")
    return {"ok": True, "refId": str(body.get("track_id") or payment.get("track_id") or ""), "code": status_code}


def commission_bps() -> int:
    return max(0, int(env.commission_bps or 200))


def commission_toman(amount: int, bps: int | None = None) -> int:
    value = int(amount)
    if value <= 0:
        return 0
    rate = commission_bps() if bps is None else max(0, int(bps))
    return value * rate // 10_000


def resolve_sale_gateway(row: dict | None = None) -> dict:
    current = row if isinstance(row, dict) else {}
    gateway = str(current.get("paymentGateway") or "mock").strip().lower()
    if gateway == "mock":
        from app.services.arvan_dns_service import edge_dry

        if edge_dry():
            return {"id": "mock", "owner": "dry", "dry": True, "commissionBps": 0, "sandbox": False}
    own_merchant = str(current.get("paymentMerchantId") or "").strip()
    hub = str(env.zarinpal_merchant_id or "").strip()
    if gateway == "zarinpal" and own_merchant and own_merchant != hub and (not _MERCHANT.pattern or bool(_MERCHANT.match(own_merchant))):
        return {
            "id": "zarinpal",
            "owner": "own",
            "merchant": own_merchant,
            "commissionBps": 0,
            "sandbox": current.get("paymentSandbox") is True,
        }
    own_key = str(current.get("paymentApiKey") or "").strip()
    if gateway == "idpay" and own_key:
        return {
            "id": "idpay",
            "owner": "own",
            "apiKey": own_key,
            "commissionBps": 0,
            "sandbox": current.get("paymentSandbox") is True,
        }
    if not hub or not payments_enabled():
        raise ValueError(PAYMENT_LATER)
    if gateway == "mock":
        # فروشگاه بی‌درگاه: سفارش با روش رسید کارت‌به‌کارت ثبت می‌شود، نه درگاه سوزان.
        return {"id": "receipt", "owner": "seller", "commissionBps": 0, "sandbox": False}
    return {
        "id": "zarinpal",
        "owner": "hub",
        "merchant": hub,
        "commissionBps": commission_bps(),
        "sandbox": False,
    }


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def public_catalog() -> list[dict]:
    return [dict(item) for item in GATEWAYS]


def public_status(row: dict) -> dict:
    gateway = str(row.get("paymentGateway") or "mock").strip().lower()
    sandbox = row.get("paymentSandbox") is True
    if gateway == "zarinpal":
        merchant = merchant_id(row)
        ready = bool(merchant)
        own = bool(str(row.get("paymentMerchantId") or "").strip()) and str(row.get("paymentMerchantId") or "").strip() != str(env.zarinpal_merchant_id or "").strip()
        if own:
            hint = "مرچنت شخصی زرین‌پال؛ فروش آنلاین کمیسیون ندارد."
        elif payments_enabled() and ready:
            hint = "بدون مرچنت شخصی، فروش روی درگاه سوزان با ۲٪ کمیسیون است."
        elif not payments_enabled():
            ready = False
            hint = PAYMENT_LATER
        else:
            hint = "مرچنت‌آیدی زرین‌پال را بگذار."
    elif gateway == "idpay":
        ready = bool(str(row.get("paymentApiKey") or "").strip()) or row.get("paymentApiKeySet") is True
        hint = "کلید آیدی‌پی ذخیره شد." if ready else "کلید API آیدی‌پی را بگذار."
    else:
        ready = True
        hint = "فروش آنلاین خاموش است؛ فروش دستی ثبت می‌شود."
        gateway = "mock"
    return {
        "gateway": gateway,
        "sandbox": sandbox,
        "currency": str(row.get("paymentCurrency") or "IRT").upper(),
        "ready": ready,
        "hint": hint,
    }


def validate_patch(patch: dict, current: dict) -> None:
    gateway = str(patch.get("paymentGateway") or current.get("paymentGateway") or "mock").strip().lower()
    if gateway not in {item["id"] for item in GATEWAYS}:
        raise ValueError("این درگاه پرداخت پشتیبانی نمی‌شود")
    currency = str(patch.get("paymentCurrency") or current.get("paymentCurrency") or "IRT").strip().upper()
    if currency not in {"IRT", "IRR"}:
        raise ValueError("واحد پول باید تومان (IRT) یا ریال (IRR) باشد")
    if "paymentMerchantId" in patch:
        merchant = str(patch.get("paymentMerchantId") or "").strip()
        if gateway == "zarinpal" and merchant and not _MERCHANT.match(merchant):
            raise ValueError("مرچنت‌آیدی زرین‌پال باید ۳۶ کاراکتر به‌شکل UUID باشد.")
