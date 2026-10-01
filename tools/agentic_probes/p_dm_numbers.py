# Number guard with the real _claims and a real nudge; the model does call stock, then states a WRONG price.
import asyncio, tempfile, time
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import inbox_agent_service as ia, storefront_service

def call(name, **args): return {"id": f"c{time.monotonic_ns()}", "name": name, "arguments": args}
def scripted(steps):
    n = {"i": 0}
    async def fake(messages, *, allow_payment, timeout):
        s = steps[min(n["i"], len(steps) - 1)]; n["i"] += 1
        return s[0], s[1], {"teacher": "fake"}
    return fake
async def hint(_s): return "stock"

root = Path(tempfile.mkdtemp())
with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(root)), patch.object(ia, "emit_later"), \
     patch.object(ia, "intent_hint", hint):
    storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=3, sku="n1")
    Q = "برای هدیهٔ تولد چی پیشنهاد می‌دید؟ قیمتش چنده؟"
    for wrong in ("قیمت گردنبند نقره ۱۹۹۰۰۰۰ تومان است",          # raw digits (control)
                  "قیمت گردنبند نقره ۱٬۵۰۰٬۰۰۰ تومان است",        # Persian thousands separator
                  "قیمت گردنبند نقره 1,500,000 تومان است",        # Latin comma
                  "قیمت گردنبند نقره یک و نیم میلیون تومان است"):  # words
        with patch.object(ia, "_complete", scripted([("", [call("stock", product="گردنبند نقره")]), (wrong, [])])):
            reply = asyncio.run(ia.answer(Q, thread={"sender": "x"}, source="battery"))
        print(("BLOCKED " if reply == ia.HANDOFF_LINE else "LEAKED  ") + f"{wrong!r} -> {reply!r}")
