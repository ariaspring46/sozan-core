from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from time import time
from uuid import uuid4

from app.config import settings as env
from app.phone import normalize_phone
from app.services import payment_service, storefront_service, wallet_service
from app.services.observe_client import emit_later
from app.services.settings_service import get_settings
from app.state_store import current_tenant, iter_tenants, read_json, shared_lock, tenant_scope, write_json

log = logging.getLogger("sozan.pay")


def public_pay_url(order_id: str) -> str:
    base = str(env.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{base}/p/{order_id}"


def panel_pay_url(order_id: str, status: str = "") -> str:
    base = str(env.panel_url or "https://app.sozan-core.ir").rstrip("/")
    suffix = f"?pay={status}" if status else ""
    return f"{base}/p/{order_id}{suffix}"


def zarinpal_callback_url() -> str:
    base = str(env.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{base}/pay/zarinpal/callback"


def idpay_callback_url() -> str:
    base = str(env.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    return f"{base}/pay/idpay/callback"


def _orders() -> list[dict]:
    rows = read_json("pay-orders.json", [])
    return rows if isinstance(rows, list) else []


def _save_orders(rows: list[dict]) -> None:
    write_json("pay-orders.json", rows[-200:])


def _pending() -> dict:
    stored = read_json("pay-pending.json", {}, shared=True)
    return stored if isinstance(stored, dict) else {}


def _save_pending(rows: dict) -> None:
    write_json("pay-pending.json", rows, shared=True)


def _put_pending(authority: str, hint: dict) -> None:
    with shared_lock():
        pending = _pending()
        pending[authority] = hint
        _save_pending(pending)


def _drop_pending(key: str) -> None:
    with shared_lock():
        pending = _pending()
        pending.pop(key, None)
        _save_pending(pending)


def _checkout_lines(lines: list[dict] | None, *, product_id: str, qty: int) -> list[dict]:
    packed: list[dict] = []
    for line in lines or []:
        pid = str(line.get("productId") or "").strip()
        count = max(0, int(line.get("qty") or 0))
        if pid and count >= 1:
            packed.append({"productId": pid, "qty": count})
    if packed:
        return packed
    if product_id and qty >= 1:
        return [{"productId": product_id, "qty": qty}]
    return []


def _stock_lines(row: dict) -> list[dict]:
    raw = row.get("lines")
    if isinstance(raw, list) and raw:
        return _checkout_lines(raw, product_id="", qty=0)
    return _checkout_lines(None, product_id=str(row.get("productId") or ""), qty=int(row.get("qty") or 1))


def _matches_paid_lookup(row: dict, *, order_id: str, ref_id: str) -> bool:
    oid = str(order_id or "").strip()
    rid = str(ref_id or "").strip()
    if oid and str(row.get("id") or "") == oid:
        return True
    if rid and str(row.get("refId") or "") == rid:
        return True
    return False


def _new_id() -> str:
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12]


def get_order(order_id: str) -> dict | None:
    wanted = str(order_id or "").strip()
    for row in _orders():
        if str(row.get("id")) == wanted:
            return dict(row)
    return None


def list_orders(limit: int = 40) -> list[dict]:
    rows = _orders()
    return [public_order(row) for row in reversed(rows[-max(1, limit) :])]


def locate_order(order_id: str) -> tuple[str, dict] | None:
    wanted = str(order_id or "").strip()
    if not wanted:
        return None
    for phone in iter_tenants():
        with tenant_scope(phone):
            row = get_order(wanted)
            if row:
                return phone, row
    return None


def public_order(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "amount": int(row.get("amount") or 0),
        "status": row.get("status") or "pending",
        "channel": row.get("channel") or "",
        "payUrl": public_pay_url(str(row.get("id") or "")),
        "startPayUrl": row.get("startPayUrl") or "",
    }


def _product_amount(product_id: str, qty: int) -> tuple[dict | None, int]:
    qty = max(1, int(qty or 1))
    wanted = str(product_id or "").strip()
    if not wanted:
        return None, 0
    for item in storefront_service.list_products().get("products") or []:
        if str(item.get("id") or "") != wanted:
            continue
        price = int(item.get("finalPrice") or item.get("price") or 0)
        return item, price * qty
    return None, 0


async def create_order(
    *,
    title: str = "",
    amount: int = 0,
    product_id: str = "",
    qty: int = 1,
    customer: str = "",
    channel: str = "دایرکت",
    thread_id: str = "",
    mobile: str = "",
    lines: list[dict] | None = None,
) -> dict:
    product, from_product = _product_amount(product_id, qty)
    total = int(amount or 0) or from_product
    if total <= 0:
        raise ValueError("مبلغ پرداخت مشخص نیست")
    label = title.strip() or str((product or {}).get("title") or "سفارش")
    route = payment_service.resolve_sale_gateway(get_settings())
    order_id = _new_id()
    phone = current_tenant()
    if not phone:
        raise ValueError("مستأجر نامشخص است")
    row = {
        "id": order_id,
        "title": label,
        "amount": total,
        "productId": str((product or {}).get("id") or product_id or ""),
        "qty": max(1, int(qty or 1)),
        "lines": _checkout_lines(lines, product_id=str((product or {}).get("id") or product_id or ""), qty=max(1, int(qty or 1))),
        "customer": (customer or "مشتری").strip()[:80],
        "channel": channel.strip() or "دایرکت",
        "threadId": thread_id,
        "gateway": route["id"],
        "owner": route["owner"],
        "merchant": route.get("merchant") or "",
        "commissionBps": int(route.get("commissionBps") or 0),
        "sandbox": bool(route.get("sandbox")),
        "status": "pending",
        "authority": "",
        "startPayUrl": "",
        "refId": "",
        "at": int(time()),
        "phone": phone,
    }
    if route["id"] == "idpay":
        paid = await payment_service.idpay_request(
            amount_toman=total,
            description=label,
            callback_url=idpay_callback_url(),
            order_id=order_id,
            api_key=str(route.get("apiKey") or ""),
            sandbox=bool(route.get("sandbox")),
            phone=mobile,
        )
    else:
        paid = await payment_service.zarinpal_request(
            amount_toman=total,
            description=label,
            callback_url=zarinpal_callback_url(),
            mobile=mobile or phone,
            merchant=str(route.get("merchant") or ""),
        )
    row["authority"] = str(paid.get("authority") or "")
    row["startPayUrl"] = str(paid.get("startPayUrl") or "")
    if route["id"] == "idpay":
        row["apiKey"] = str(route.get("apiKey") or "")
    if not row["authority"] or not row["startPayUrl"]:
        raise ValueError("درگاه شناسه پرداخت نداد")
    orders = _orders()
    orders.append(row)
    _save_orders(orders)
    _put_pending(row["authority"], {"phone": phone, "orderId": order_id, "gateway": route["id"]})
    return public_order(row)


def start_url(order_id: str) -> str:
    found = locate_order(order_id)
    if found is None:
        raise KeyError("سفارش پیدا نشد")
    _phone, row = found
    if str(row.get("status") or "") == "paid":
        return panel_pay_url(order_id, "ok")
    url = str(row.get("startPayUrl") or "").strip()
    if not url:
        raise ValueError("نشانی درگاه آماده نیست")
    return url


async def attach_pay_link(
    reply: str,
    pay: dict | None,
    *,
    channel: str = "دایرکت",
    thread_id: str = "",
    customer: str = "",
) -> str:
    text = (reply or "").strip()
    if not text or not isinstance(pay, dict):
        return text
    product_id = str(pay.get("productId") or "").strip()
    product, priced = _product_amount(product_id, 1)
    if not product or priced <= 0:
        return text
    try:
        amount = int(pay.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    try:
        order = await create_order(
            title=str(pay.get("title") or "").strip(),
            amount=amount or priced,
            product_id=product_id,
            customer=customer,
            channel=channel,
            thread_id=thread_id,
        )
    except Exception:
        return text
    url = str(order.get("payUrl") or "").strip()
    if not url or url in text:
        return text
    return f"{text}\n{url}"[:1000]


async def finish_order(*, authority: str, ok: bool, gateway: str = "zarinpal") -> str:
    key = str(authority or "").strip()
    pending = _pending()
    hint = pending.get(key)
    if not isinstance(hint, dict):
        return str(env.panel_url or "https://app.sozan-core.ir").rstrip("/") + "/p/missing?pay=missing"
    phone = str(hint.get("phone") or "").strip()
    order_id = str(hint.get("orderId") or "").strip()
    if not phone or not order_id:
        _drop_pending(key)
        return panel_pay_url(order_id or "missing", "fail")
    with tenant_scope(phone):
        orders = _orders()
        row = next((item for item in orders if str(item.get("id")) == order_id), None)
        if row is None:
            _drop_pending(key)
            return panel_pay_url(order_id, "missing")
        if str(row.get("status") or "") == "paid":
            _drop_pending(key)
            return panel_pay_url(order_id, "ok")
        if not ok:
            row["status"] = "failed"
            _save_orders(orders)
            _drop_pending(key)
            return panel_pay_url(order_id, "cancel")
        try:
            if str(row.get("gateway") or gateway) == "idpay":
                api_key = str(row.get("apiKey") or "") or str(
                    payment_service.resolve_sale_gateway(get_settings()).get("apiKey") or ""
                )
                verified = await payment_service.idpay_verify(
                    order_id=order_id,
                    authority=key,
                    api_key=api_key,
                    sandbox=bool(row.get("sandbox")),
                )
            else:
                verified = await payment_service.zarinpal_verify(
                    amount_toman=int(row.get("amount") or 0),
                    authority=key,
                    merchant=str(row.get("merchant") or ""),
                )
        except ValueError:
            return panel_pay_url(order_id, "fail")
        try:
            _mark_paid(row, ref_id=str(verified.get("refId") or ""))
            _save_orders(orders)
        finally:
            _drop_pending(key)
    return panel_pay_url(order_id, "ok")


def _mark_paid(row: dict, *, ref_id: str) -> None:
    if str(row.get("status") or "") == "paid":
        return
    amount = int(row.get("amount") or 0)
    bps = int(row.get("commissionBps") or 0)
    commission = payment_service.commission_toman(amount, bps)
    owner = str(row.get("owner") or "hub")
    row["status"] = "paid"
    row["refId"] = ref_id
    row["paidAt"] = int(time())
    wallet_service.credit_sale(
        amount=amount,
        commission=commission if owner == "hub" else 0,
        order_id=str(row.get("id") or ""),
        note=str(row.get("title") or ""),
        owner=owner,
    )
    storefront_service.add_sale(
        title=str(row.get("title") or "سفارش"),
        amount=amount,
        customer=str(row.get("customer") or "مشتری"),
        channel=str(row.get("channel") or "دایرکت"),
    )
    for line in _stock_lines(row):
        product_id = str(line["productId"])
        try:
            storefront_service.adjust_stock(product_id, -int(line["qty"]))
        except (KeyError, ValueError):
            log.warning("stock-shortage productId=%s", product_id)
            emit_later(
                kind="shop",
                title="stock-shortage",
                surface="shop",
                status="failed",
                payload={"productId": product_id},
            )


def find_tenant_by_slug(slug: str) -> str | None:
    wanted = slug.strip()
    if not wanted:
        return None
    for phone in iter_tenants():
        with tenant_scope(phone):
            shop = read_json("shop.json", {})
            if isinstance(shop, dict) and str(shop.get("slug") or "").strip() == wanted:
                return phone
    return None


def ensure_pay_secret() -> str:
    shop = read_json("shop.json", {})
    if not isinstance(shop, dict):
        shop = {}
    secret = str(shop.get("paySecret") or "").strip()
    if secret:
        return secret
    secret = secrets.token_urlsafe(24)
    shop["paySecret"] = secret
    write_json("shop.json", shop)
    return secret


def verify_pay_secret(slug: str, secret: str) -> str:
    phone = find_tenant_by_slug(slug)
    if not phone:
        raise ValueError("فروشگاه پیدا نشد")
    with tenant_scope(phone):
        shop = read_json("shop.json", {})
        stored = str((shop or {}).get("paySecret") or "").strip() if isinstance(shop, dict) else ""
        if not stored or not hmac.compare_digest(stored, (secret or "").strip()):
            raise ValueError("کلید فروشگاه نادرست است")
    return phone


def sign_body(raw: bytes) -> str:
    return hmac.new(env.jwt_secret.encode(), raw, hashlib.sha256).hexdigest()


def valid_sign(raw: bytes, header: str) -> bool:
    got = (header or "").strip().lower()
    if not got:
        return False
    return hmac.compare_digest(sign_body(raw), got)


async def shop_checkout(
    *,
    slug: str,
    secret: str,
    name: str = "",
    phone: str = "",
    lines: list[dict] | None = None,
) -> dict:
    tenant = verify_pay_secret(slug, secret)
    with tenant_scope(tenant):
        total = 0
        titles = []
        packed: list[dict] = []
        for line in lines or []:
            pid = str(line.get("productId") or "").strip()
            count = max(0, int(line.get("qty") or 0))
            if not pid or count < 1:
                continue
            product, amount = _product_amount(pid, count)
            if not product or amount <= 0:
                continue
            total += amount
            titles.append(str(product.get("title") or pid))
            packed.append({"productId": pid, "qty": count})
        if total <= 0:
            raise ValueError("سبد خالی است")
        customer = name.strip() or "مشتری"
        try:
            mobile = normalize_phone(phone) if phone.strip() else ""
        except ValueError:
            mobile = ""
        first = packed[0]
        order = await create_order(
            title="، ".join(titles)[:120],
            amount=total,
            product_id=str(first["productId"]),
            qty=int(first["qty"]),
            customer=customer,
            channel="فروشگاه",
            mobile=mobile,
            lines=packed,
        )
        return {**order, "url": order["startPayUrl"] or order["payUrl"], "orderId": order["id"]}


def shop_paid(*, slug: str, order_id: str, amount: int, title: str, customer: str, ref_id: str = "") -> dict:
    phone = find_tenant_by_slug(slug)
    if not phone:
        raise ValueError("فروشگاه پیدا نشد")
    with tenant_scope(phone):
        orders = _orders()
        existing = next(
            (row for row in orders if _matches_paid_lookup(row, order_id=order_id, ref_id=ref_id)),
            None,
        )
        if existing and str(existing.get("status") or "") == "paid":
            return public_order(existing)
        row = existing or {
            "id": order_id or _new_id(),
            "title": (title or "سفارش فروشگاه").strip()[:120],
            "amount": int(amount),
            "productId": "",
            "qty": 1,
            "customer": (customer or "مشتری").strip()[:80],
            "channel": "فروشگاه",
            "gateway": "zarinpal",
            "owner": "hub",
            "commissionBps": payment_service.commission_bps(),
            "status": "pending",
            "at": int(time()),
            "phone": phone,
        }
        if int(row.get("amount") or 0) <= 0:
            row["amount"] = int(amount)
        _mark_paid(row, ref_id=ref_id)
        if existing is None:
            orders.append(row)
        _save_orders(orders)
        return public_order(row)
