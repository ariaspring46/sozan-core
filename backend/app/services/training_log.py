"""Training-example log for the qwen3.8-27b finetune (finetune-data-plan.md).

One JSONL row per example, sent as an observe event of kind `train`; observe on
the home machine appends it to ~/local-ai/sozan-train/raw/<date>/<task>.jsonl.
Rules that cannot be negotiated: the seller's consent key `sozanImprove`
(«کمک به بهتر شدن سوزان», default on) gates every record; voice material is
never recorded at all; every text passes mask_pii here even if the caller
already masked it; the tenant is stored only as an HMAC hash, so deletion by
request stays possible and the raw phone never lands in the dataset.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import uuid4

from app.config import settings
from app.services.observe_client import emit_later
from app.services.pii_mask import mask_pii
from app.services.pipeline_release import BEHAVIOR_VERSION, hub_release_id

CONSENT_KEY = "sozanImprove"
TASKS = ("router", "shop_edit", "caption", "inbox_reply", "site_design")
SOURCES = ("real", "battery", "synthetic")

_FALSE = {"0", "false", "off", "no", "خاموش"}


def consent_enabled() -> bool:
    """کلید «کمک به بهتر شدن سوزان»: پنل (training.json) + روی‌نویسی سراسری از تنظیمات."""
    from app.services.settings_service import allows_training, get_settings

    if not allows_training():
        return False
    try:
        raw = get_settings().get(CONSENT_KEY)
    except Exception:
        return True
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() not in _FALSE
    return bool(raw)


def tenant_hash() -> str:
    from app.state_store import current_tenant

    phone = str(current_tenant() or "")
    if not phone:
        return ""
    return hmac.new(str(settings.jwt_secret or "").encode(), phone.encode(), hashlib.sha256).hexdigest()[:16]


def _masked_messages(messages: list[dict]) -> list[dict]:
    safe = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        safe.append({**msg, "content": mask_pii(str(msg.get("content") or ""))})
    return safe


def build_example(
    *,
    task: str,
    messages: list[dict],
    output: dict | None = None,
    tools: list[str] | None = None,
    labels: dict | None = None,
    teacher: str = "",
    source: str = "real",
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    surface: str = "",
) -> dict | None:
    """Contract row, or None when this turn must not be recorded."""
    if task not in TASKS:
        return None
    if source == "voice":
        return None
    if not consent_enabled():
        return None
    out = dict(output or {})
    text = mask_pii(str(out.get("text") or "")).strip()
    if not text:
        return None
    src = source if source in SOURCES else "real"
    out["text"] = text
    return {
        "id": str(uuid4()),
        "ts": time.time(),
        "task": task,
        "tenant": tenant_hash(),
        "source": src,
        "release": hub_release_id(),
        "promptVersion": BEHAVIOR_VERSION,
        "teacher": str(teacher or ""),
        "messages": _masked_messages(messages),
        "tools": [str(name) for name in (tools or []) if str(name).strip()],
        "output": out,
        "labels": dict(labels or {}),
        "latencyMs": int(latency_ms or 0),
        "costUsd": float(cost_usd or 0.0),
        "surface": str(surface or ""),
    }


def log_example(**kwargs: Any) -> str:
    """Build and send one example. Returns its id, or "" when nothing is recorded."""
    example = build_example(**kwargs)
    if example is None:
        return ""
    emit_later(kind="train", title="train-example", surface=str(example.get("surface") or "train"), payload=example)
    return str(example["id"])


def log_label(example_id: str, labels: dict, *, tenant: str = "") -> str:
    """A label that arrives later (edit, 👍/👎, publish). The nightly build joins it."""
    eid = str(example_id or "").strip()
    rows = labels if isinstance(labels, dict) else {}
    if not eid or not rows or not consent_enabled():
        return ""
    row = {
        "exampleId": eid,
        "labels": rows,
        "ts": time.time(),
        "tenant": tenant_hash(),
    }
    emit_later(kind="train", title="train-label", surface="train", payload=row)
    return eid


def fingerprint(row: dict) -> str:
    """Stable hash of the conversation pair, for the nightly near-duplicate drop."""
    payload = {
        "m": [str(msg.get("content") or "") for msg in row.get("messages") or []],
        "o": str((row.get("output") or {}).get("text") or ""),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
