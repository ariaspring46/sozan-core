# Router turn lock: two concurrent turns on one thread; a crashed holder (dead pid); a slow model past the 20s lease.
import asyncio, os, tempfile, time
from unittest.mock import AsyncMock, patch
from app.config import settings
from app.state_store import tenant_scope, write_json, read_json
from app.services import router_service as rs

def slow_model(sec):
    async def complete(messages, tools):
        await asyncio.sleep(sec); return {"text": "باشه", "tool_calls": [], "usage": {}}
    return complete

async def both():
    async def one(tag, delay):
        await asyncio.sleep(delay)
        try:
            await rs.turn("یه سوال کلی دارم درباره کسب و کار", complete=slow_model(1.0)); return f"{tag}:ok"
        except rs.RouterBusy: return f"{tag}:RouterBusy"
    return await asyncio.gather(one("A", 0), one("B", 0.2))

with patch.object(settings, "state_dir", tempfile.mkdtemp()), patch("app.services.router_embed.rescue_tool", new=AsyncMock(return_value="")), \
     patch.object(rs, "_emit"), tenant_scope("09129900001"):
    print("concurrent:", asyncio.run(both()))
    rs._bind_thread("")
    name = rs._busy_name()
    write_json(name, {"token": "x", "pid": 999999, "until": time.time() + 999, "key": ""})   # holder process died
    try:
        asyncio.run(rs.turn("سلام", complete=slow_model(0))); print("dead-pid lock: reclaimed OK")
    except rs.RouterBusy: print("dead-pid lock: STUCK")
    print("busy file after turn:", read_json(name, {}))
