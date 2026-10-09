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
from app.services.tenant_lock import tenant_file_lock
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
    # ردیف‌های pending هرگز حذف نمی‌شوند؛ فقط تاریخچهٔ قدیمی کوتاه می‌شود.
    keep = [row for row in rows if str(row.get("status") or "") == "pending"]
    done = [row for row in rows if str(row.get("status") or "") != "pending"]
    write_json("pay-orders.json", (keep + done)[-400:])


def _append_order(row: dict) -> None:
    orders = _orders()
    orders.append(row)
    _save_orders(orders)
    from app.services import tenant_index_service

    tenant_index_service.upsert(phone=str(row.get("phone") or current_tenant()), order_id=str(row.get("id") or ""))


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
    from app.services import tenant_index_service

    def has_order(phone: str) -> bool:
        with tenant_scope(phone):
            return get_order(wanted) is not None

    phone = tenant_index_service.lookup("order", wanted, has_order)
    if not phone:
        return None
    with tenant_scope(phone):
        row = get_order(wanted)
    return (phone, row) if row else None


def public_order(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "amount": int(row.get("amount") or 0),
        "status": row.get("status") or "pending",
        "gateway": row.get("gateway") or "",
        "channel": row.get("channel") or "",
        "at": int(row.get("at") or 0),
        "payUrl": public_pay_url(str(row.get("id") or "")),
        "startPayUrl": row.get("startPayUrl") or "",
        **_action_fields(row),
    }


def _action_fields(row: dict) -> dict:
    need = row.get("needsAction")
    if not isinstance(need, dict) or not need.get("reason"):
        return {}
    return {
        "needsAction": {"reason": str(need.get("reason")), "items": list(need.get("items") or [])},
        "customer": str(row.get("customer") or ""),
        "customerMobile": str(row.get("customerMobile") or ""),
    }


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _wanted(lines: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in lines:
        product_id = str(line.get("productId") or "").strip()
        if product_id:
            out[product_id] = out.get(product_id, 0) + max(1, int(line.get("qty") or 1))
    return out


def stock_problem(lines: list[dict]) -> str:
    """The sentence a shopper sees when the cart asks for more than the shop has; empty when it can be sold.
    Checked before a payment link exists, so nobody pays for a product that is gone."""
    rows = {str(row.get("id") or ""): row for row in storefront_service.list_products().get("products") or []}
    for product_id, qty in _wanted(lines).items():
        row = rows.get(product_id)
        if row is None:
            continue  # a link the seller made with a free amount names no catalog product
        stock = int(row.get("stock") or 0)
        title = str(row.get("title") or "این کالا")
        if stock <= 0:
            return f"«{title}» تمام شده است."
        if stock < qty:
            return f"از «{title}» فقط {str(stock).translate(_FA_DIGITS)} عدد مانده است."
    return ""


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
    packed = _checkout_lines(lines, product_id=str((product or {}).get("id") or product_id or ""), qty=max(1, int(qty or 1)))
    short = stock_problem(packed)
    if short:
        raise ValueError(short)
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
        "lines": packed,
        "customer": (customer or "مشتری").strip()[:80],
        "customerMobile": str(mobile or "").strip()[:20],
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
    if route.get("id") == "receipt":
        # بی‌درگاه: سفارش ثبت و خریدار به صفحهٔ رسید کارت‌به‌کارت فرستاده می‌شود.
        url = f"/p/{order_id}"
        row["gateway"] = "receipt"
        row["owner"] = "seller"
        _append_order(row)
        out = public_order(row)
        out["payUrl"] = url
        out["paymentMethods"] = ["receipt"]
        return out
    if route.get("dry"):
        url = f"https://dry-mock.invalid/p/{order_id}"
        row["authority"] = order_id
        row["startPayUrl"] = url
        _append_order(row)
        out = public_order(row)
        out["payUrl"] = url
        return out
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
    _append_order(row)
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
    except ValueError as exc:
        if str(exc) == payment_service.PAYMENT_LATER and payment_service.PAYMENT_LATER not in text:
            return f"{text}\n{payment_service.PAYMENT_LATER}"[:1000]
        return text
    except Exception:
        return text
    url = str(order.get("payUrl") or "").strip()
    if not url or url in text:
        return text
    if str(order.get("gateway") or "") == "receipt":
        # پیوند نسبت‌دار صفحهٔ رسید با نشانی عمومی کامل می‌شود؛ دایرکت نشانی مطلق می‌بیند.
        url = public_pay_url(str(order.get("id") or ""))
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
                    amount_toman=int(row.get("amount") or 0),
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
            # پس از مکث verify دوباره بخوان؛ سفارش هم‌زمان‌ساخته گم نمی‌شود.
            with tenant_file_lock("pay-orders"):
                fresh = _orders()
                row = next((item for item in fresh if str(item.get("id")) == order_id), row)
                _mark_paid(row, ref_id=str(verified.get("refId") or ""))
                _save_orders(fresh)
        finally:
            _drop_pending(key)
    return panel_pay_url(order_id, "ok")


def _resync_storefront_after_paid() -> None:
    """کاتالوگ استاتیک ویترین بعد از تغییر موجودی هم‌گام شود."""
    try:
        from app.services.catalog_sync_service import sync_live

        sync_live()
    except Exception as exc:
        from app.services.observe_client import emit_later

        emit_later(
            kind="shop",
            title="storefront-resync-failed",
            surface="shop",
            status="failed",
            payload={"error": type(exc).__name__},
        )


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
        source="gateway",
    )
    short, sold_out = _take_stock(row)
    if short:
        # paid but not fully in stock (two shoppers on the last one, or a receipt approved late): the seller decides
        row["needsAction"] = {"reason": "stock", "items": short, "at": int(time())}
    _resync_storefront_after_paid()
    _tell_seller(row, short, sold_out)


def _take_stock(row: dict) -> tuple[list[dict], list[str]]:
    """Take what the shop has for each line. Returns the lines it could not fill and the products this sale emptied."""
    rows = {str(item.get("id") or ""): item for item in storefront_service.list_products().get("products") or []}
    short: list[dict] = []
    sold_out: list[str] = []
    for product_id, qty in _wanted(_stock_lines(row)).items():
        item = rows.get(product_id)
        stock = int((item or {}).get("stock") or 0)
        title = str((item or {}).get("title") or row.get("title") or "کالا")
        take = min(max(stock, 0), qty)
        if take:
            try:
                storefront_service.adjust_stock(product_id, -take)
            except (KeyError, ValueError):
                take = 0
            else:
                if stock - take == 0:
                    sold_out.append(title)
        if take < qty:
            short.append({"productId": product_id, "title": title, "wanted": qty, "had": take})
            log.warning("stock-shortage productId=%s", product_id)
            emit_later(
                kind="shop",
                title="stock-shortage",
                surface="shop",
                status="failed",
                payload={"productId": product_id, "orderId": str(row.get("id") or ""), "wanted": qty, "had": take},
            )
    return short, sold_out


def _tell_seller(row: dict, short: list[dict], sold_out: list[str]) -> None:
    """A line in the seller's chat. The customer's number stays on the sales page, out of the chat and the model."""
    fa = lambda value: str(value).translate(_FA_DIGITS)  # noqa: E731
    if short:
        what = "، ".join(f"«{item['title']}» ({fa(item['wanted'])} خواسته، {fa(item['had'])} داشتی)" for item in short)
        amount = fa(f"{int(row.get('amount') or 0):,}".replace(",", "٬"))
        text = (
            f"سفارش «{row.get('title') or 'سفارش'}» به مبلغ {amount} تومان پرداخت شد "
            f"ولی موجودی کم بود: {what}. با مشتری هماهنگ کن: کالای جایگزین یا برگرداندن پول. "
            "شماره و نام مشتری در صفحهٔ «فروش» زیر «نیازمند اقدام» است."
        )
    elif sold_out:
        names = "، ".join(f"«{title}»" for title in sold_out)
        text = f"موجودی {names} با این فروش تمام شد و در فروشگاه دیگر خریدنی نیست. اگر هنوز داری بگو «موجودی {sold_out[0]} رو ۱۰ کن»."
    else:
        return
    try:
        from app.services import router_service

        router_service.post_notice(router_service.latest_thread_id(), text)
    except Exception:
        log.exception("seller notice failed order=%s", row.get("id"))


def find_tenant_by_slug(slug: str) -> str | None:
    wanted = slug.strip()
    if not wanted:
        return None
    from app.services import tenant_index_service

    def owns_slug(phone: str) -> bool:
        with tenant_scope(phone):
            shop = read_json("shop.json", {})
        return isinstance(shop, dict) and str(shop.get("slug") or "").strip() == wanted

    return tenant_index_service.lookup("slug", wanted, owns_slug)


def ensure_pay_secret() -> str:
    from app.state_store import update_json

    def _secret(shop: dict) -> None:
        if not str(shop.get("paySecret") or "").strip():
            shop["paySecret"] = secrets.token_urlsafe(24)

    # shop.json is also written by the build (X4) and settings (X5): locked update.
    return str(update_json("shop.json", _secret, {}, lock="shop").get("paySecret") or "")


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
    key = (env.payment_sign_secret or env.jwt_secret).encode()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


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
    ip: str = "",
) -> dict:
    tenant = verify_pay_secret(slug, secret)
    from app.redis_client import redis_client

    try:
        rl = f"pay:co:{slug}:{ip or 'no-ip'}"
        hits = await redis_client.incr(rl)
        if hits == 1:
            await redis_client.expire(rl, 3600)
        if hits > 30:
            raise ValueError("تعداد سفارش بیش از حد است؛ کمی بعد تلاش کنید")
    except ValueError:
        raise
    except Exception:
        pass  # بدون Redis سقف نمی‌ماند، اما فروش نمی‌ایستد
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


def catalog_ids(*, slug: str, secret: str) -> dict:
    """نگاشت شناسهٔ ویترین (اسلاگ‌دار) → شناسهٔ واقعی کالای تنانت."""
    tenant = verify_pay_secret(slug, secret)
    mapping: dict = {}
    with tenant_scope(tenant):
        from app.services import storefront_service

        for row in (storefront_service.list_products().get("products") or []):
            pid = str(row.get("id") or "")
            if not pid:
                continue
            # هم شکل slug-دار (از بذر قالب: azmaish-panl-01) و هم خود pid
            mapping[f"{slug}-{pid[:2]}"] = pid
            mapping[pid] = pid
    return {"map": mapping, "slug": slug}


def shop_config(*, slug: str, secret: str) -> dict:
    tenant = verify_pay_secret(slug, secret)
    with tenant_scope(tenant):
        # فروشگاه بی‌درگاه (mock) هم رسیده است: پول مشتری هرگز از سوزان نمی‌گذرد.
        methods = ["receipt"]
        return {"paymentMethods": methods, "slug": slug}


async def attach_receipt(*, slug: str, secret: str, order_no: str, upload) -> dict:
    tenant = verify_pay_secret(slug, secret)
    with tenant_scope(tenant):
        orders = _orders()
        row = next(
            (
                item
                for item in orders
                if str(item.get("id")) == str(order_no or "").strip()
                and str(item.get("status") or "") in ("pending", "awaiting_receipt", "receipt_rejected")
            ),
            None,
        )
        if row is None:
            raise ValueError("سفارش پیدا نشد")
        image_name = ""
        if upload is not None and getattr(upload, "filename", ""):
            data = await upload.read()
            if len(data) > 4_000_000:
                raise ValueError("عکس رسید بزرگ‌تر از حد مجاز است")
            if data:
                from app.services import chat_media_service

                saved = chat_media_service.save(upload.filename, data, upload.content_type or "")
                image_name = str(saved.get("name") or "")
        row["status"] = "awaiting_receipt"
        row["receipt"] = image_name
        row["receiptStatus"] = "waiting"
        _save_orders(orders)
        from app.services import support_service

        support_service.create_ticket(
            subject=f"رسید سفارش {order_no}",
            text="رسید کارت‌به‌کارت بارگذاری شد؛ بررسی و تأیید کنید.",
            order_no=str(order_no),
            image_name=image_name,
        )
        return {"ok": True, "status": "awaiting_receipt"}


def list_receipts() -> list[dict]:
    with tenant_scope(current_tenant()):
        return [
            public_order(row)
            for row in _orders()
            if str(row.get("status") or "") == "awaiting_receipt"
        ]


def review_receipt(*, order_no: str, approve: bool | None = None, note: str = "", decision: str = "") -> dict:
    if approve is None:
        # قرارداد UI «decision» است؛ approve سازگاری قدیمی
        approve = str(decision or "").strip().lower() in {"approve", "approved", "ok", "accept"}
    with tenant_scope(current_tenant()):
        orders = _orders()
        row = next(
            (item for item in orders if str(item.get("id")) == str(order_no or "").strip()),
            None,
        )
        if row is None or str(row.get("status") or "") != "awaiting_receipt":
            raise ValueError("رسیدی با این شماره در انتظار نیست")
        if approve:
            row["gateway"] = "receipt"
            row["receiptStatus"] = "approved"
            # تأیید رسید = پول رسیده؛ موجودی، فروش و کیف پول با همان مسیر درگاه.
            _mark_paid(row, ref_id=str(row.get("receiptRef") or "receipt"))
        else:
            row["status"] = "receipt_rejected"
            row["receiptStatus"] = "rejected"
        row["receiptNote"] = str(note or "").strip()[:300]
        _save_orders(orders)
        out = public_order(row)
        if not approve:
            out["status"] = "receipt_rejected"
        return out


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
        # پرداخت فقط سفارشِ در انتظارِ همان مبلغ را تأیید می‌کند؛ وب‌هوک سفارش نمی‌سازد.
        if existing is None:
            raise ValueError("سفارش متناظر پیدا نشد")
        if int(existing.get("amount") or 0) != int(amount):
            raise ValueError("مبلغ پرداخت با سفارش نمی‌خواند")
        row = existing
        if int(row.get("amount") or 0) <= 0:
            row["amount"] = int(amount)
        _mark_paid(row, ref_id=ref_id)
        _save_orders(orders)
        return public_order(row)
