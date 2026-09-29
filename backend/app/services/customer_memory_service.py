"""Customer memory (plan §7.4): a few masked facts per customer, one line in
the system prompt.

The agent calls `remember` after a real turn and `_prompt_block` while building
the system prompt. Only shop-relevant facts are kept — sizes, colors, product
names, counts — as masked snippets keyed by a hash of the thread's sender, so
no name, phone, or address ever lands here. Consent (`sozanImprove`) gates the
write like every other training artifact; voice turns are refused outright.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

from app.config import settings
from app.services.tenant_lock import tenant_file_lock
from app.state_store import read_json, write_json

FILE = "customer-memory.json"
CAP = 400
_ENTRIES_PER_CUSTOMER = 6
_MAX_FACT_CHARS = 160
_MAX_BLOCK_CHARS = 420

_FACT = re.compile(
    r"(سایز|اندازه|رنگ|جنس|مدل)\s+([^\n.,،;؛!؟]{2,40})"
)
_ITEM = re.compile(r"(برداشتید|خریدید|گرفتید|پسندیدید|خواستید)[^\n.]{0,60}")
_PRICE = re.compile(r"[^\n]{0,30}(زیر|تا|حدود)\s*[۰-۹0-9]{4,}[^\n]{0,12}تومان")


def _fold(text: str) -> str:
    return str(text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


def _mask(text: str) -> str:
    from app.services.pii_mask import mask_pii

    return mask_pii(str(text or ""))


def consent_enabled() -> bool:
    from app.services.training_log import consent_enabled as training_consent

    return training_consent()


def customer_key(sender: str) -> str:
    phone = str(sender or "").strip()
    if not phone:
        return ""
    return hmac.new(str(settings.jwt_secret or "").encode(), phone.encode(), hashlib.sha256).hexdigest()[:16]


def remember(thread: dict | None, sentence: str) -> bool:
    """Record masked facts from one real customer turn. Voice never reaches here."""
    sender = str((thread or {}).get("sender") or "").strip()
    key = customer_key(sender)
    text = _mask(_fold(str(sentence or "")).strip())
    if not key or not text or not consent_enabled():
        return False
    facts: list[str] = []
    for match in _FACT.finditer(text):
        facts.append(f"{match.group(1)} {match.group(2).strip()}")
    for match in _ITEM.finditer(text):
        facts.append(match.group(0).strip())
    for match in _PRICE.finditer(text):
        facts.append(match.group(0).strip())
    if not facts:
        return False
    # Keep the informative ones; a fact fully contained in another is noise.
    facts = [fact for fact in (fact[:_MAX_FACT_CHARS] for fact in facts[:6]) if fact]
    facts = [fact for fact in facts if not any(fact != other and fact in other for other in facts)][:3]
    with tenant_file_lock("customer-memory"):
        store = read_json(FILE, {})
        if not isinstance(store, dict):
            store = {}
        row = store.setdefault(key, {"facts": [], "turns": 0, "lastAt": 0})
        if not isinstance(row, dict):
            row = {"facts": [], "turns": 0, "lastAt": 0}
        known = [str(fact) for fact in (row.get("facts") or [])]
        for fact in facts:
            if fact not in known:
                known.append(fact)
        row["facts"] = known[-_ENTRIES_PER_CUSTOMER:]
        row["turns"] = int(row.get("turns") or 0) + 1
        row["lastAt"] = int(time.time())
        store[key] = row
        if len(store) > CAP:
            for old in sorted(store, key=lambda k: int(store[k].get("lastAt") or 0))[: len(store) - CAP]:
                store.pop(old, None)
        write_json(FILE, store)
    return True


def _prompt_block(thread: dict | None) -> str:
    key = customer_key(str((thread or {}).get("sender") or ""))
    if not key:
        return ""
    store = read_json(FILE, {})
    row = store.get(key) if isinstance(store, dict) else None
    if not isinstance(row, dict):
        return ""
    facts = [str(fact) for fact in (row.get("facts") or []) if str(fact).strip()]
    if not facts:
        return ""
    shown = "؛ ".join(facts[-3:])[:_MAX_BLOCK_CHARS]
    return f"حافظهٔ مشتری (از گفت‌وگوهای پیشین، برای گرم‌تر گرفتن جواب): {shown}. اگر مطمئن نیستی، از او بپرس."


def forget(sender: str) -> bool:
    key = customer_key(sender)
    if not key:
        return False
    with tenant_file_lock("customer-memory"):
        store = read_json(FILE, {})
        if isinstance(store, dict) and key in store:
            store.pop(key, None)
            write_json(FILE, store)
            return True
    return False


def snapshot() -> dict:
    store = read_json(FILE, {})
    if not isinstance(store, dict):
        return {"customers": 0, "facts": 0}
    return {
        "customers": len(store),
        "facts": sum(len((row or {}).get("facts") or []) for row in store.values() if isinstance(row, dict)),
    }
