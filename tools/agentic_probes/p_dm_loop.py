# DM agent loop scenarios with a scripted model (patching inbox_agent_service._complete).
import asyncio, json, tempfile, time
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import inbox_agent_service as ia, storefront_service

def call(name, **args): return {"id": f"c{time.monotonic_ns()}", "name": name, "arguments": args}

def scripted(steps, delay=0.0):
    seen = {"n": 0, "msgs": []}
    async def fake(messages, *, allow_payment, timeout):
        seen["msgs"].append(len(messages))
        if delay: await asyncio.sleep(min(delay, timeout))
        step = steps[min(seen["n"], len(steps) - 1)]
        seen["n"] += 1
        text, calls = step
        return text, calls, {"teacher": "fake"}
    return fake, seen

async def no_hint(_s): return ""
async def no_claims(text, facts): return text

def run(label, question, steps, delay=0.0, thread=None, budget=None):
    fake, seen = scripted(steps, delay)
    events = []
    ps = [patch.object(ia, "_complete", fake), patch.object(ia, "intent_hint", no_hint),
          patch.object(ia, "emit_later", side_effect=lambda **k: events.append(k.get("payload"))),
          patch.object(ia, "_claims", no_claims)]
    if budget is not None: ps.append(patch.object(ia, "INBOX_TURN_BUDGET", budget))
    for p in ps: p.start()
    try:
        t0 = time.monotonic()
        reply = asyncio.run(ia.answer(question, thread=thread or {"sender": "x"}, source="battery"))
        dt = time.monotonic() - t0
    finally:
        for p in ps: p.stop()
    reason = next((e.get("reason") for e in reversed(events) if isinstance(e, dict) and "reason" in e), None)
    print(f"[{label}] model-calls={seen['n']} time={dt:.1f}s reason={reason!r}\n    reply={reply!r}")

root = Path(tempfile.mkdtemp())
with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(root)):
    storefront_service.add_product(title="گردنبند نقره", price=1950000, stock=3, sku="n1")
    Q = "برای هدیهٔ تولد چی پیشنهاد می‌دید؟ قیمتش چنده؟"   # no product named -> goes to the model
    run("A tool-call loop", Q, [("", [call("stock", product="گردنبند")])])
    run("B invented raw price", Q, [("قیمتش ۲۵۰۰۰۰۰ تومان است", [])])
    run("C invented price w/ separators", Q, [("قیمتش ۲٬۵۰۰٬۰۰۰ تومان است", [])])
    run("D invented price in words", Q, [("قیمتش دو میلیون و پانصد تومان است", [])])
    run("E invented 'x million' price", Q, [("قیمتش ۲.۵ میلیون تومنه", [])])
    run("F invented discount %", Q, [("برای شما ۳۰٪ تخفیف داریم", [])])
    run("G payment_link w/o buy", Q, [("", [call("payment_link", product="گردنبند نقره", qty=1)]), ("بفرمایید", [])])
    run("H slow model -> budget", Q, [("", [call("stock", product="گردنبند")])], delay=0.6, budget=2.0)
    run("I unknown tool", Q, [("", [call("delete_shop")]), ("در خدمتم", [])])
