# Same probe, but inside a long-lived event loop (as in the FastAPI process / worker).
import asyncio, json, tempfile, time
from unittest.mock import patch
from app.config import settings
from app.services import observe_client as oc

tmp = tempfile.mkdtemp()
calls = {"post": 0}
async def down(body):
    calls["post"] += 1
    await asyncio.sleep(0.01)
    return False

async def main():
    path = oc.outbox_path()
    path.write_text("".join(json.dumps({"i": i}) + "\n" for i in range(oc._OUTBOX_MAX_ROWS)))
    oc._flush_cooldown_until = time.time() + 999   # isolate the append path from flush
    oc.emit_later(kind="inbox", title="one-real-event")   # one ordinary event while observe is down
    for sec in (1, 2, 3, 5):
        await asyncio.sleep(1 if sec < 5 else 2)
        rows = oc.load_outbox()
        selfev = sum(1 for r in rows if r.get("title") == "observe-outbox-dropped")
        markers = sum(1 for r in rows if "dropped" in r and "title" not in r)
        orig = sum(1 for r in rows if "i" in r)
        tasks = len(asyncio.all_tasks()) - 1
        print(f"t={sec}s posts={calls['post']} live-tasks={tasks} rows={len(rows)} self-events={selfev} drop-markers={markers} original-left={orig}")

with patch.object(settings, "state_dir", tmp), patch.object(oc, "_post_event", new=down):
    asyncio.run(main())
