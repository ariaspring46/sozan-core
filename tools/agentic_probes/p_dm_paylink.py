# If the model calls payment_link twice in one turn (parallel calls or a second round), how many orders/links?
import asyncio, tempfile, time
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import inbox_agent_service as ia, storefront_service

orders = []
async def fake_order(**kw):
    orders.append(kw); return {"payUrl": f"https://pay.example/o{len(orders)}", "amount": kw["amount"], "title": kw["title"]}
def call(name, **args): return {"id": f"c{time.monotonic_ns()}", "name": name, "arguments": args}
def scripted(steps):
    n = {"i": 0}
    async def fake(messages, *, allow_payment, timeout):
        s = steps[min(n["i"], len(steps) - 1)]; n["i"] += 1
        return s[0], s[1], {}
    return fake

root = Path(tempfile.mkdtemp())
with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(root)), patch.object(ia, "emit_later"), \
     patch("app.services.pay_service.create_order", fake_order), patch.object(ia, "_seller_has_own_gateway", lambda: True), \
     patch.object(ia, "_dry_gateway", lambda: False):
    storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=3, sku="n1")
    storefront_service.add_product(title="دستبند طلا", price=4200000, stock=2, sku="d1")
    Q = "لینک پرداخت بفرستید"     # explicit buy, no product named -> model path with payment allowed
    steps = [("", [call("payment_link", product="گردنبند نقره", qty=1), call("payment_link", product="گردنبند نقره", qty=1)]),
             ("", [call("payment_link", product="گردنبند نقره", qty=5)]),
             ("لینک پرداخت آماده است", [])]
    with patch.object(ia, "_complete", scripted(steps)):
        reply = asyncio.run(ia.answer(Q, thread={"sender": "x", "id": "t1"}, source="battery"))
    print("orders created:", len(orders), [o["qty"] for o in orders]); print("reply:", reply)
