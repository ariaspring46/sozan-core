"""A shop order from the shopper's click to delivery, through the real HTTP endpoints (2026-10-10).

The owner's acceptance scenario: the customer orders, payment is checked with its trusted source (the gateway's
verify), stock is checked and taken, the seller ships with a tracking code, the customer is told, the order is
delivered, and every step is in the order's operation log. The failure paths stop safely: an unverified payment,
too little stock, two shoppers on the last unit, a seller who does not confirm.

Only the world outside Sozan is replaced: the bank (zarinpal request/verify), the SMS provider, the AI voice. The
storefront checkout, the bank callback, the seller's chat with its confirmation cards, the event sweep, the public
order page and the panel's order list are the real code paths. Every step is a named check, so a failure says which
step broke; `python -m app.scenarios.order_lifecycle_test` prints the steps as a report.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import events as events_api, pay as pay_api, router_chat as chat_api
from app.config import settings
from app.database import get_session
from app.security import get_current_user
from app.services import pay_service, router_service, seller_events, settings_service, storefront_service
from app.state_store import read_json, set_tenant, tenant_scope, write_json

SELLER = "09120000777"
SLUG = "sara-jewels"
SECRET = "scenario-pay-secret"
MERCHANT = "0b5c1f2e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"
SHOPPER = "09121234567"
_VOICE_PATCHES: list = []


def setUpModule() -> None:
    for name, empty in (("complete_json", {"error": "llm_unreachable"}), ("complete_text_chat", None)):
        started = patch(f"app.services.shop_voice_service.{name}", new=AsyncMock(return_value=empty))
        started.start()
        _VOICE_PATCHES.append(started)


def tearDownModule() -> None:
    while _VOICE_PATCHES:
        _VOICE_PATCHES.pop().stop()


class Shop:
    """One seller with a turquoise ring (stock 2) and a clean state directory. `gateway`: the seller's own Zarinpal
    merchant, or «receipt» (no gateway: the shopper pays card-to-card and uploads the receipt)."""

    def __init__(self, gateway: str = "zarinpal") -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.steps: list[tuple[str, bool, str]] = []
        self.sms = AsyncMock(return_value="1" * 18)
        self.verify = AsyncMock(return_value={"ok": True, "refId": "REF-1", "code": 100})
        self._authority = 0
        self.patches = [
            patch.object(settings, "state_dir", self.tmp.name),
            # observe events and the local model go nowhere: run on the hub, they would land in production's monitor
            patch.object(settings, "local_llm_url", "http://127.0.0.1:1/v1"),
            patch.object(settings, "melipayamak_order_body_id", "777"),
            patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")),
            patch("app.services.catalog_sync_service.sync_live", return_value={"live": False, "reason": "no-build-dir"}),
            patch("app.services.payment_service.zarinpal_request", new=AsyncMock(side_effect=self._bank_request)),
            patch("app.services.payment_service.zarinpal_verify", new=self.verify),
            patch("app.services.melipayamak_otp_service.send_pattern", new=self.sms),
            patch("app.services.wallet_service.consume_sms", return_value={"charged": 0}),
            # a shop without its own gateway takes card-to-card receipts once Sozan's payments are on
            patch.object(settings, "payments_enabled", True),
            patch.object(settings, "zarinpal_merchant_id", "11111111-1111-1111-1111-111111111111"),
        ]
        for item in self.patches:
            item.start()
        with tenant_scope(SELLER):
            write_json("shop.json", {"slug": SLUG, "paySecret": SECRET, "brand": "جواهری سارا"})
            if gateway == "zarinpal":
                settings_service.save_settings({"paymentGateway": "zarinpal", "paymentMerchantId": MERCHANT})
            self.ring = storefront_service.add_product(title="انگشتر فیروزه", price=500000, stock=2, sku="ring")["product"]
        app = FastAPI()
        for module in (pay_api, chat_api, events_api):
            app.include_router(module.router)

        async def seller():
            set_tenant(SELLER)  # what get_current_user does for a real login
            return SimpleNamespace(phone=SELLER, role="admin", is_active=True)

        async def session():
            yield MagicMock()

        app.dependency_overrides[get_current_user] = seller
        app.dependency_overrides[get_session] = session
        self.client = TestClient(app)

    async def _bank_request(self, **kwargs) -> dict:
        self._authority += 1
        authority = f"A{self._authority:035d}"
        return {"authority": authority, "startPayUrl": f"https://payment.zarinpal.com/pg/StartPay/{authority}"}

    def close(self) -> None:
        for item in self.patches:
            item.stop()
        router_service._THREAD.set("")
        self.tmp.cleanup()

    # ---- the record

    def check(self, step: str, ok: object, detail: str = "") -> bool:
        self.steps.append((step, bool(ok), detail))
        return bool(ok)

    def broken(self) -> list[str]:
        return [f"{step}: {detail}" for step, ok, detail in self.steps if not ok]

    # ---- what the shopper does

    def checkout(self, qty: int = 1, *, name: str = "مریم", phone: str = SHOPPER, address: str = "تهران، خیابان آزادی، پلاک ۱۲") -> tuple[int, dict]:
        res = self.client.post(
            "/p/shop/checkout",
            json={"slug": SLUG, "secret": SECRET, "name": name, "phone": phone, "address": address, "lines": [{"productId": self.ring["id"], "qty": qty}]},
        )
        return res.status_code, res.json()

    def bank_returns(self, order: dict, status: str = "OK") -> str:
        authority = str(order.get("startPayUrl") or order.get("url") or "").rsplit("/", 1)[-1]
        res = self.client.get("/pay/zarinpal/callback", params={"Authority": authority, "Status": status}, follow_redirects=False)
        return str(res.headers.get("location") or "")

    def upload_receipt(self, order_id: str) -> int:
        res = self.client.post(
            f"/p/orders/{order_id}/receipt",
            data={"slug": SLUG, "secret": SECRET},
            files={"file": ("receipt.png", b"\x89PNG" + b"0" * 64, "image/png")},
        )
        return res.status_code

    def public(self, order_id: str) -> dict:
        return self.client.get(f"/p/{order_id}/status").json()

    # ---- what the seller does

    def say(self, text: str = "", **fields) -> dict:
        res = self.client.post("/chat", headers={"Idempotency-Key": uuid4().hex}, json={"text": text, **fields})
        return res.json()

    def chat(self) -> dict:
        return self.client.get("/chat").json()

    def orders(self) -> list[dict]:
        return self.client.get("/wallet/orders").json()["orders"]

    # ---- what is stored

    def order(self, order_id: str) -> dict:
        with tenant_scope(SELLER):
            return pay_service.get_order(order_id) or {}

    def stock(self) -> int:
        with tenant_scope(SELLER):
            return next(int(row["stock"]) for row in storefront_service.list_products()["products"] if row["id"] == self.ring["id"])

    def sales(self) -> int:
        with tenant_scope(SELLER):
            return len(storefront_service.list_sales()["sales"])

    def events(self, order_id: str) -> list[str]:
        return [str(item.get("event")) for item in self.order(order_id).get("history") or []]

    def sweep(self, later: float) -> int:
        with tenant_scope(SELLER):
            return seller_events.sweep_shop(time.time() + later)

    def seller_texts(self) -> str:
        return "\n".join(str(row.get("text") or "") for row in self.chat().get("messages") or [])


_PII = ("customer", "customerMobile", "address", "history", "threadId")
DAY = 86400


def happy_path(shop: Shop) -> None:
    status, made = shop.checkout()
    order_id = str(made.get("orderId") or made.get("id") or "")
    shop.check("۱. مشتری سفارش ثبت می‌کند", status == 200 and order_id and made.get("status") == "pending", f"{status} {made}")
    shop.check("۱. پیش از پرداخت موجودی برداشته نمی‌شود", shop.stock() == 2, f"stock={shop.stock()}")

    location = shop.bank_returns(made)
    verified = shop.verify.await_args.kwargs if shop.verify.await_args else {}
    shop.check(
        "۲. پرداخت با تأیید خود درگاه ثبت می‌شود",
        shop.order(order_id).get("status") == "paid" and verified.get("amount_toman") == 500000 and "pay=ok" in location,
        f"status={shop.order(order_id).get('status')} verify={verified} location={location}",
    )
    shop.check("۳. موجودی کم و فروش ثبت می‌شود", shop.stock() == 1 and shop.sales() == 1, f"stock={shop.stock()} sales={shop.sales()}")
    shop.check("۳. فروشنده در چت باخبر می‌شود", "سفارش تازه پرداخت شد" in shop.seller_texts(), shop.seller_texts()[-200:])
    shop.check("۳. نشان چت برای پیام تازهٔ سوزان", shop.client.get("/events/unseen").json().get("count", 0) >= 1, "")

    out = shop.say("سفارش مریم رو فرستادم کد رهگیری 123456789012")
    card = out.get("pendingConfirm") or {}
    shop.check(
        "۴. ارسال از چت کارت تأیید می‌خواهد",
        card.get("tool") == "update_order" and "پیامک" in str(card.get("summary")) and not shop.order(order_id).get("stage"),
        str(card.get("summary")),
    )
    shop.say(confirmId=card.get("id", ""))
    row = shop.order(order_id)
    shop.check("۴. سفارش «ارسال‌شده» با کد رهگیری", row.get("stage") == "shipped" and row.get("tracking") == "123456789012", f"{row.get('stage')} {row.get('tracking')}")

    sent = shop.sms.await_args
    shop.check(
        "۵. مشتری با پیامک خبر می‌گیرد",
        sent is not None and sent.args[0] == SHOPPER and "123456789012" in sent.args[1] and order_id in sent.args[1],
        str(sent.args if sent else "no sms"),
    )
    page = shop.public(order_id)
    shop.check(
        "۵. صفحهٔ سفارش مشتری مرحله و کد رهگیری را نشان می‌دهد، بی دادهٔ شخصی",
        page.get("stage") == "shipped" and page.get("tracking") == "123456789012" and page.get("hasAddress") and not any(key in page for key in _PII),
        str(sorted(page)),
    )

    shop.check("۶. پیش از یک هفته یادآوری تحویل نمی‌آید", shop.sweep(DAY) == 0, "")
    shop.sweep(8 * DAY)
    card = shop.chat().get("pendingConfirm") or {}
    shop.check("۶. پس از یک هفته سوزان خودش کارت «تحویل‌شده» می‌آورد", card.get("tool") == "update_order" and "تحویل‌شده" in str(card.get("summary")), str(card))
    shop.say(confirmId=card.get("id", ""))
    shop.check("۶. با تأیید فروشنده تحویل ثبت می‌شود", shop.order(order_id).get("stage") == "delivered", str(shop.order(order_id).get("stage")))

    shop.check(
        "۷. همهٔ مرحله‌ها در گزارش عملیات سفارش",
        shop.events(order_id) == ["created", "paid", "shipped", "notified", "reminded", "delivered"],
        str(shop.events(order_id)),
    )
    panel = next((item for item in shop.orders() if item.get("id") == order_id), {})
    shop.check("۷. پنل فروشنده نام، شماره، آدرس و تاریخچه را دارد", panel.get("customerMobile") == SHOPPER and panel.get("address") and panel.get("history"), str(sorted(panel)))


def failure_paths(shop: Shop) -> None:
    status, made = shop.checkout()
    order_id = str(made.get("orderId") or "")
    location = shop.bank_returns(made, status="NOK")
    shop.check(
        "خطا ۱. بانک «ناموفق» برگرداند: سفارش ناموفق، موجودی و فروش دست‌نخورده",
        shop.order(order_id).get("status") == "failed" and shop.stock() == 2 and shop.sales() == 0 and "pay=cancel" in location,
        f"{shop.order(order_id).get('status')} stock={shop.stock()} sales={shop.sales()} {location}",
    )
    shop.check("خطا ۱. شکست پرداخت در گزارش عملیات", shop.events(order_id) == ["created", "failed"], str(shop.events(order_id)))

    status, made = shop.checkout()
    order_id = str(made.get("orderId") or "")
    shop.verify.side_effect = ValueError("not paid")
    location = shop.bank_returns(made)
    shop.verify.side_effect = None
    shop.check(
        "خطا ۲. «OK» در نشانی ولی تأیید درگاه رد کرد: پرداخت ثبت نمی‌شود",
        shop.order(order_id).get("status") == "pending" and shop.stock() == 2 and shop.sales() == 0 and "pay=fail" in location,
        f"{shop.order(order_id).get('status')} stock={shop.stock()} {location}",
    )

    status, made = shop.checkout(qty=5)
    shop.check(
        "خطا ۳. بیش از موجودی: لینک پرداخت ساخته نمی‌شود",
        status == 400 and "فقط ۲ عدد" in str(made.get("detail")),
        f"{status} {made}",
    )

    _s1, first = shop.checkout(qty=2, name="مریم")
    _s2, second = shop.checkout(qty=1, name="رضا", phone="09351112233")
    shop.bank_returns(first)
    shop.bank_returns(second)
    late = shop.order(str(second.get("orderId")))
    shop.check(
        "خطا ۴. دو خریدار روی آخرین عدد: پول ثبت، سفارش «نیازمند اقدام»، موجودی منفی نمی‌شود",
        late.get("status") == "paid" and isinstance(late.get("needsAction"), dict) and shop.stock() == 0,
        f"{late.get('status')} {late.get('needsAction')} stock={shop.stock()}",
    )
    texts = shop.seller_texts()
    shop.check("خطا ۴. فروشنده در چت باخبر می‌شود، بی شمارهٔ مشتری", "موجودی کم بود" in texts and "0935" not in texts, texts[-300:])
    page = shop.public(str(second.get("orderId")))
    shop.check("خطا ۴. صفحهٔ عمومی همین سفارش دادهٔ مشتری ندارد", not any(key in page for key in _PII), str(sorted(page)))
    shop.check("خطا ۴. پس از یک روز یادآوری «نیازمند اقدام»", shop.sweep(DAY + 60) >= 1 and "هنوز «نیازمند اقدام» است" in shop.seller_texts(), "")

    out = shop.say("سفارش مریم رو فرستادم کد رهگیری 555555555")
    card = out.get("pendingConfirm") or {}
    sms_before = shop.sms.await_count
    shop.say(cancelId=card.get("id", ""))
    shop.check(
        "خطا ۵. فروشنده تأیید نکرد: هیچ تغییری و هیچ پیامکی",
        card.get("tool") == "update_order" and not shop.order(str(first.get("orderId"))).get("stage") and shop.sms.await_count == sms_before,
        str(card.get("summary")),
    )


def receipt_path(shop: Shop) -> None:
    status, made = shop.checkout(address="")
    order_id = str(made.get("orderId") or made.get("id") or "")
    shop.check("کارت‌به‌کارت ۱. سفارش بی درگاه با روش رسید ثبت می‌شود", status == 200 and shop.order(order_id).get("gateway") == "receipt", f"{status} {made}")
    shop.check("کارت‌به‌کارت ۲. مشتری رسید را می‌فرستد", shop.upload_receipt(order_id) == 200 and shop.order(order_id).get("status") == "awaiting_receipt", str(shop.order(order_id).get("status")))
    card = shop.chat().get("pendingConfirm") or {}
    shop.check(
        "کارت‌به‌کارت ۳. سوزان خودش کارت «تأیید رسید» می‌آورد؛ تا تأیید چیزی پرداخت‌شده نیست",
        card.get("tool") == "approve_receipt" and "پول به حسابت" in str(card.get("summary")) and shop.stock() == 2,
        str(card),
    )
    shop.say(confirmId=card.get("id", ""))
    shop.check("کارت‌به‌کارت ۴. با تأیید فروشنده پرداخت، موجودی و فروش ثبت می‌شود", shop.order(order_id).get("status") == "paid" and shop.stock() == 1 and shop.sales() == 1, f"{shop.order(order_id).get('status')} stock={shop.stock()}")
    res = shop.client.post(f"/p/orders/{order_id}/address", json={"address": "شیراز، خیابان زند، کوچهٔ ۸، پلاک ۴"})
    shop.check("کارت‌به‌کارت ۵. مشتری آدرس را در صفحهٔ سفارشش می‌نویسد", res.status_code == 200 and res.json().get("hasAddress") and "address" not in res.json(), res.text[:200])
    res = shop.client.post(f"/pay/orders/{order_id}/stage", json={"stage": "shipped", "tracking": "۹۸۷۶۵۴۳۲۱", "carrier": "تیپاکس"})
    out = res.json()
    shop.check("کارت‌به‌کارت ۶. فروشنده از پنل ارسال می‌کند و مشتری پیامک می‌گیرد", res.status_code == 200 and out.get("tracking") == "987654321" and out.get("notified") == "sms", res.text[:200])
    shop.check("کارت‌به‌کارت ۷. گزارش عملیات", shop.events(order_id) == ["created", "receipt", "paid", "address", "shipped", "notified"], str(shop.events(order_id)))
    res = shop.client.post(f"/p/orders/{order_id}/address", json={"address": "آدرس دیگری پس از ارسال، پلاک ۹"})
    shop.check("کارت‌به‌کارت ۸. پس از ارسال آدرس عوض نمی‌شود", res.status_code == 400, res.text[:200])


class OrderLifecycleTests(unittest.TestCase):
    def _run(self, path, gateway: str = "zarinpal") -> None:
        shop = Shop(gateway)
        try:
            path(shop)
        finally:
            shop.close()
        self.assertTrue(shop.steps)
        self.assertEqual(shop.broken(), [])

    def test_happy_path(self) -> None:
        self._run(happy_path)

    def test_failure_paths(self) -> None:
        self._run(failure_paths)

    def test_card_to_card(self) -> None:
        self._run(receipt_path, gateway="receipt")


def report() -> int:
    """The steps as the owner reads them; exit code 1 when any step broke."""
    setUpModule()
    bad = 0
    try:
        for title, path, gateway in (
            ("مسیر درست (درگاه خود فروشنده)", happy_path, "zarinpal"),
            ("مسیرهای خطا", failure_paths, "zarinpal"),
            ("کارت‌به‌کارت", receipt_path, "receipt"),
        ):
            shop = Shop(gateway)
            try:
                path(shop)
            finally:
                shop.close()
            print(f"\n{title}")
            for step, ok, detail in shop.steps:
                print(f"  {'✓' if ok else '✗'} {step}" + ("" if ok else f"\n      {detail[:300]}"))
                bad += 0 if ok else 1
    finally:
        tearDownModule()
    print(f"\n{'همهٔ مرحله‌ها درست' if not bad else f'{bad} مرحله خراب'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(report())
