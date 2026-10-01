# Probe: does an event emitted from sync code (no running loop) keep its tenant?
import asyncio, tempfile, time, threading
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import observe_client as oc

seen = []
async def capture(body):
    seen.append((body.get("tenant"), body.get("title")))
    return True

def sync_path():                       # e.g. code run via asyncio.to_thread / threadpool endpoint
    oc.emit_later(kind="studio", title="from-thread")

async def main():
    with tenant_scope("09120000001"):
        oc.emit_later(kind="studio", title="from-loop")
        await asyncio.to_thread(sync_path)   # to_thread copies the context, but emit_later spawns a raw Thread
        await asyncio.sleep(0.5)

with patch.object(settings, "state_dir", tempfile.mkdtemp()), patch.object(oc, "_post_event", new=capture):
    asyncio.run(main())
for t in seen: print(t)
