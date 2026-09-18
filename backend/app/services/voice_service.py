from __future__ import annotations

import json
import time

from app.services.llm import complete_json
from app.services.observe_client import emit_later
from app.services.settings_service import get_settings
from app.state_store import read_json, write_json

DEFAULT_VOICE = {
    "summary": "فروشندهٔ گرم کیف و کفش؛ کوتاه و بی‌تعارف.",
    "tone": "گرم، کوتاه، فارسی روزمره",
    "do": ["موجودی را راست بگو", "قیمت را واضح بگو"],
    "dont": ["قول ارسال فوری بدون موجودی", "لحن اداری"],
    "sampleReply": "سلام، موجودی را همین حالا چک می‌کنم و برمی‌گردم.",
    "samples": [],
    "at": 0,
}


def get_voice() -> dict:
    stored = read_json("voice.json", {})
    if not isinstance(stored, dict):
        stored = {}
    out = dict(DEFAULT_VOICE)
    out.update({key: stored[key] for key in DEFAULT_VOICE if key in stored})
    return out


def _save(voice: dict) -> dict:
    write_json("voice.json", voice)
    return voice


def apply_tone(tone_id: str) -> dict:
    from app.services.profile_service import TONES

    preset = TONES.get(tone_id) or TONES["warm"]
    voice = get_voice()
    voice["tone"] = preset["tone"]
    voice["summary"] = preset["summary"]
    voice["sampleReply"] = preset["sampleReply"]
    voice["toneId"] = preset["id"]
    voice["at"] = int(time.time())
    return _save(voice)


def merge_summary(summary: str) -> dict:
    text = summary.strip()
    if not text:
        return get_voice()
    voice = get_voice()
    if not voice.get("summary") or voice.get("summary") == DEFAULT_VOICE["summary"]:
        voice["summary"] = text[:400]
        voice["at"] = int(time.time())
        return _save(voice)
    return voice


def prompt_block() -> str:
    voice = get_voice()
    return (
        f"لحن فروشنده: {voice.get('tone')}\n"
        f"شخصیت: {voice.get('summary')}\n"
        f"بکن: {', '.join(voice.get('do') or [])}\n"
        f"نکن: {', '.join(voice.get('dont') or [])}\n"
        f"نمونه: {voice.get('sampleReply')}"
    )


async def learn(*, platform: str, handle: str, samples: str) -> dict:
    cfg = get_settings()
    previous = get_voice()
    blob = samples.strip()
    parsed = await complete_json(
        """از نوشته‌های فروشنده فقط JSON برگردان.
{"summary":"یک خط شخصیت","tone":"چند کلمه لحن","do":["..."],"dont":["..."],"sampleReply":"یک پاسخ نمونه به مشتری"}""",
        (
            f"فروشگاه: {cfg.get('storeName')} / {cfg.get('storeTagline')}\n"
            f"کانال: {platform} {handle}\n"
            f"لحن قبلی: {json.dumps(previous, ensure_ascii=False)}\n"
            f"نمونه‌ها:\n{blob or 'نمونه جدا نفرستاده؛ از نام فروشگاه حدس بزن.'}"
        ),
        surface="voice",
    )
    voice = get_voice()
    if parsed.get("summary"):
        voice["summary"] = str(parsed["summary"]).strip()[:400]
    if parsed.get("tone"):
        voice["tone"] = str(parsed["tone"]).strip()[:160]
    if isinstance(parsed.get("do"), list):
        voice["do"] = [str(item).strip() for item in parsed["do"] if str(item).strip()][:6]
    if isinstance(parsed.get("dont"), list):
        voice["dont"] = [str(item).strip() for item in parsed["dont"] if str(item).strip()][:6]
    if parsed.get("sampleReply"):
        voice["sampleReply"] = str(parsed["sampleReply"]).strip()[:280]
    if blob:
        kept = [str(item) for item in (voice.get("samples") or []) if str(item).strip()]
        kept.append(blob[:1200])
        voice["samples"] = kept[-8:]
    elif not voice.get("summary"):
        voice["summary"] = f"فروشندهٔ {cfg.get('storeName') or handle}"
    voice["at"] = int(time.time())
    voice["source"] = f"{platform}:{handle}"
    saved = _save(voice)
    emit_later(
        kind="voice",
        surface="voice",
        title="voice-learn",
        payload={"platform": platform, "handle": handle, "hasSamples": bool(blob)},
    )
    return saved


async def draft_reply(customer_text: str, thread: dict | None = None) -> str | None:
    from app.services.llm import _persian_enough
    from app.services.settings_service import get_settings
    from app.services.storefront_service import list_products

    voice = get_voice()
    cfg = get_settings()
    history = ""
    if thread:
        rows = thread.get("messages") or []
        parts = []
        for msg in rows[-8:]:
            role = "مشتری" if msg.get("role") == "inbound" else "فروشنده"
            parts.append(f"{role}: {str(msg.get('text') or '')[:240]}")
        history = "\n".join(parts)
    catalog = []
    try:
        for item in (list_products().get("products") or [])[:8]:
            title = str(item.get("title") or "").strip()
            pid = str(item.get("id") or "").strip()
            price = int(item.get("finalPrice") or item.get("price") or 0)
            label = item.get("priceLabel") or (f"{price} تومان" if price else "")
            if title and pid:
                catalog.append(f"{pid} | {title} | {label}".strip())
    except Exception:
        catalog = []
    media_note = ""
    if thread:
        for msg in reversed(thread.get("messages") or []):
            if msg.get("role") != "inbound":
                continue
            kind = str(msg.get("mediaKind") or "").strip()
            if kind:
                label = {"image": "تصویر", "video": "ویدیو", "audio": "صدا"}.get(kind, kind)
                media_note = f"پیوست مشتری: {label}"
            break
    parsed = await complete_json(
        'تو همان فروشنده‌ای. فقط JSON بده. {"reply":"پاسخ کوتاه فارسی با لحن فروشنده","pay":{"productId":"شناسه کالا","amount":0,"title":""}} اگر مشتری نمی‌خرد pay نده.',
        (
            f"{prompt_block()}\n"
            f"فروشگاه: {cfg.get('storeName') or ''} / {cfg.get('storeTagline') or ''}\n"
            f"کالاها:\n{chr(10).join(catalog) or '—'}\n"
            f"گفتگو:\n{history or customer_text.strip()}\n"
            f"پیام مشتری: {customer_text.strip()}\n"
            f"{media_note}"
        ).strip(),
        surface="inbox",
        max_tokens=700,
    )
    if parsed.get("error"):
        return None
    reply = str(parsed.get("reply") or "").strip()
    if not reply or not _persian_enough(reply):
        return None
    from app.services import pay_service
    from app.services.channel_service import PLATFORMS

    platform = str((thread or {}).get("platform") or "")
    channel = PLATFORMS.get(platform, platform) or "دایرکت"
    customer = str((thread or {}).get("sender") or "مشتری")
    reply = await pay_service.attach_pay_link(
        reply[:1000],
        parsed.get("pay") if isinstance(parsed.get("pay"), dict) else None,
        channel=channel,
        thread_id=str((thread or {}).get("id") or ""),
        customer=customer,
    )
    return reply[:1000]
