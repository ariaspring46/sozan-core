# F7 end-to-end: a real DM through the production inbox path (handle_inbound -> maybe_auto_reply
# -> voice_service.draft_reply -> inbox_agent.answer). Does customer memory / a training example get written?
import asyncio, tempfile
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import inbox_service, storefront_service, customer_memory_service, inbox_agent_service

root = Path(tempfile.mkdtemp())
events = []
def rec(**kw): events.append(kw.get("title"))
async def no_model(**_): raise AssertionError("model should not be needed")

async def run():
    out = await inbox_service.handle_inbound(platform="telegram", sender="علی", text="سایز ۳۸ مانتو کرپ هست؟",
                                             sender_id="1", chat_id="9", external_id="9:1")
    await inbox_service.drain_auto_replies(); inbox_service.cancel_deferred_auto_replies()
    return out

with tenant_scope("09120001111"), patch.object(settings, "state_dir", str(root)), \
     patch("app.services.plan_service.current", return_value={"autoReply": "draft"}), \
     patch("app.services.inbox_agent_service.complete_tools", no_model), \
     patch("app.services.inbox_agent_service.emit_later", side_effect=rec), \
     patch("app.services.inbox_service.emit_later"), \
     patch("app.services.training_log.consent_enabled", return_value=True), \
     patch("app.services.customer_memory_service.consent_enabled", return_value=True):
    storefront_service.add_product(title="مانتو کرپ", price=1000000, stock=4, sku="m1")
    out = asyncio.run(run())
    tid = out["thread"]["id"]
    th = inbox_service.get_thread(tid)
    draft = [m for m in th["messages"] if m.get("kind") == "draft"]
    print("draft produced:", bool(draft), "|", (draft[-1]["text"][:70] if draft else ""))
    print("customer-memory after production DM:", customer_memory_service.snapshot())
    print("train-example events from production DM:", events.count("train-example"))
    events.clear()
    asyncio.run(inbox_agent_service.answer("سایز ۳۸ مانتو کرپ هست؟", thread={"sender": "علی"}, source="real"))
    print("customer-memory after source='real':", customer_memory_service.snapshot())
    print("train-example events with source='real':", events.count("train-example"))
