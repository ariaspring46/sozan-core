# F5: does GET /shop block the event loop while the factory status subprocess runs?
import asyncio, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope, write_json
from app.api import shop as shop_api
from app.services import shop_service

tmp = Path(tempfile.mkdtemp())
script = tmp / "tools" / "factory.py"; script.parent.mkdir(parents=True)
script.write_text("import time, json; time.sleep(0.5); print(json.dumps({'status': 'running'}))\n")  # a 0.5 s factory status call

async def main():
    gaps = []
    async def ticker():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01); now = time.perf_counter(); gaps.append(now - last); last = now
    t = asyncio.create_task(ticker())
    await asyncio.sleep(0.1)
    t0 = time.perf_counter()
    await asyncio.gather(*(shop_api.get_shop(_user=None) for _ in range(3)))   # three panels polling at once
    took = time.perf_counter() - t0
    await asyncio.sleep(0.05)
    t.cancel()
    print(f"3 concurrent GET /shop took {took:.2f}s (serial, not parallel); worst event-loop stall: {max(gaps):.2f}s")

with patch.object(settings, "state_dir", str(tmp / "state")), patch.object(type(settings), "factory_script", property(lambda s: script)), \
     patch.object(shop_service, "FACTORY_PYTHON", sys.executable), tenant_scope("09120001111"):
    write_json("shop.json", {"slug": "demo", "jobId": "job-1", "status": "building"})
    asyncio.run(main())
