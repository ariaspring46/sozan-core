# Probe: once the outbox is at cap and observe is down, does one event start a self-sustaining chain?
import asyncio, json, tempfile, threading, time
from unittest.mock import patch
from app.config import settings
from app.services import observe_client as oc

tmp = tempfile.mkdtemp()
calls = {"post": 0}
async def down(body):
    calls["post"] += 1
    await asyncio.sleep(0.01)   # observe unreachable (fast refusal)
    return False

with patch.object(settings, "state_dir", tmp), patch.object(oc, "_post_event", new=down):
    path = oc.outbox_path()
    path.write_text("".join(json.dumps({"i": i}) + "\n" for i in range(oc._OUTBOX_MAX_ROWS)))
    t0 = threading.active_count()
    oc._append_outbox({"real": "one"})        # a single new event while at cap
    for sec in (1, 2, 3):
        time.sleep(1)
        rows = oc.load_outbox()
        dropped_events = sum(1 for r in rows if r.get("title") == "observe-outbox-dropped")
        real = sum(1 for r in rows if "i" in r)
        print(f"t={sec}s posts={calls['post']} threads={threading.active_count()-t0} rows={len(rows)} self-events={dropped_events} original-rows-left={real}")
