import asyncio, tempfile
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import inbox_agent_service as ia, storefront_service
orders = []
async def fake_order(**kw):
    orders.append(kw); return {"payUrl": "https://pay.example/o", "amount": kw["amount"], "title": kw["title"]}
with tenant_scope("09120001111"), patch.object(settings, "state_dir", tempfile.mkdtemp()), \
     patch("app.services.pay_service.create_order", fake_order), patch.object(ia, "_seller_has_own_gateway", lambda: True), \
     patch.object(ia, "_dry_gateway", lambda: False):
    storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=0, sku="n1")
    storefront_service.add_product(title="دستبند طلا", price=4200000, stock=2, sku="d1")
    print("out of stock :", asyncio.run(ia.run_tool("payment_link", {"product": "گردنبند نقره", "qty": 1}, thread={})))
    print("qty>stock    :", asyncio.run(ia.run_tool("payment_link", {"product": "دستبند طلا", "qty": 5}, thread={})))
    print("orders:", [(o["title"], o["qty"], o["amount"]) for o in orders])
