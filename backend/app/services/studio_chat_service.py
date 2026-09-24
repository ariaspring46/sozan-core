from __future__ import annotations

import re
import time
from pathlib import Path
from uuid import UUID, uuid4

from app.services.campaign_service import CampaignService
from app.services.llm import complete_json
from app.services.observe_client import emit_later
from app.services.persian_text import guard_output, sanitize_persian
from app.services.tenant_lock import tenant_file_lock
from app.state_store import read_json, write_json

STUDIO_SYSTEM = """تو استودیوی محتوای سوزان هستی. فقط یک شیء JSON برگردان؛ متن بیرون JSON ننویس.
کلیدها: reply, title, subtitle, cta, instagram, telegram, whatsapp, compose, imagePrompt.
reply خلاصهٔ فارسی همان پست است که به کاربر نشان می‌دهیم؛ نام فیلد یا «متن فارسی» ننویس.
سؤال نپرس و جزئیات نخواه. اگر چیزی کم است از نام فروشگاه و کالاها کپشن واقعی بساز.
اگر احوال‌پرسی است title و کپشن را خالی بگذار، compose را false کن، reply را یک جملهٔ کوتاه بگذار.
اگر کاربر پست، استوری، ریلز، ویدیو یا کپشن خواست هر سه کپشن را پر کن و compose را true کن:
- instagram: کپشن فید، هشتگ کم، حدود ۲۵۰ تا ۴۰۰ کاراکتر
- telegram: متن کانال بدون هشتگ زیاد، حداکثر ۴۰۰ کاراکتر
- whatsapp: پیام کوتاه دوستانه، بدون هشتگ اینستاگرامی، حداکثر ۲۸۰ کاراکتر
imagePrompt را انگلیسی بنویس: product photo, no text, no logos, no people."""
STUB_COPY = frozenset({"متن فارسی", "تیتر کوتاه", "title", "reply", "cta", "subtitle"})

GREETING_TOKENS = frozenset(
    {
        "سلام",
        "درود",
        "خوبی",
        "چطوری",
        "چخبر",
        "خبر",
        "چه",
        "مرسی",
        "ممنون",
        "که",
        "هستی",
        "تو",
        "کی",
    }
)
GREETINGS = frozenset(
    {
        "سلام",
        "درود",
        "خوبی",
        "چطوری",
        "چخبر",
        "چه خبر",
        "مرسی",
        "ممنون",
        "که هستی",
        "تو کی هستی",
        "سلام خوبی",
        "سلام چطوری",
    }
)
CAPTION_LIMITS = {"instagram": 2200, "telegram": 1024, "whatsapp": 1024}
PUNCT = re.compile(r"[؟?،,!.؛;]+")


def _is_greeting(text: str) -> bool:
    stripped = PUNCT.sub(" ", text.replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک"))
    words = [item for item in stripped.split() if item]
    if not words or len(words) > 3:
        return False
    joined = " ".join(words)
    if joined in GREETINGS:
        return True
    return all(word in GREETING_TOKENS for word in words)


def _messages() -> list[dict]:
    rows = read_json("studio-messages.json", [])
    return rows if isinstance(rows, list) else []


def messages_by_id(ids: set[str]) -> dict[str, dict]:
    wanted = {str(item) for item in ids if str(item)}
    if not wanted:
        return {}
    found: dict[str, dict] = {}
    for row in _messages():
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or "")
        if ident in wanted:
            found[ident] = row
    return found


def _save(rows: list[dict]) -> None:
    running = [
        row
        for row in rows[:-80]
        if isinstance(row.get("compose"), dict) and row["compose"].get("status") == "running"
    ]
    kept: list[dict] = []
    seen: set[str] = set()
    for row in running + rows[-80:]:
        ident = str(row.get("id") or "")
        if ident and ident in seen:
            continue
        if ident:
            seen.add(ident)
        kept.append(row)
    write_json("studio-messages.json", kept)


def _clip_captions(captions: dict) -> dict:
    out = {}
    for key, limit in CAPTION_LIMITS.items():
        out[key] = sanitize_persian(_real_copy(captions.get(key), limit=limit), limit=limit)
    return out


def _real_copy(text: object, *, limit: int = 400) -> str:
    value = str(text or "").strip()
    if not value or value in STUB_COPY:
        return ""
    return value[:limit]


def _studio_prompt(spoken: str, *, media: dict | None) -> str:
    cfg = {}
    try:
        from app.services.settings_service import get_settings

        cfg = get_settings() or {}
    except Exception:
        cfg = {}
    goods = []
    try:
        from app.services.storefront_service import list_products

        for item in (list_products().get("products") or [])[:8]:
            title = str(item.get("title") or "").strip()
            if title:
                goods.append(title)
    except Exception:
        goods = []
    history = []
    for row in _messages()[-10:]:
        role = "کاربر" if row.get("role") == "user" else "استودیو"
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        if text.startswith("بگو برای اینستاگرام"):
            continue
        if role == "استودیو" and "چه پستی" in text and not row.get("captions"):
            continue
        history.append(f"{role}: {text[:240]}")
    history = history[-6:]
    blob = (
        f"فروشگاه: {cfg.get('storeName') or 'فروشگاه'}\n"
        f"شعار: {cfg.get('storeTagline') or ''}\n"
        f"کالاها: {', '.join(goods) or 'ویترین فروشگاه'}\n"
        f"گفتگو:\n{chr(10).join(history) or spoken}"
    )
    if media:
        blob += f"\nپیوست: {media.get('kind')}"
    return blob


def snapshot() -> dict:
    expire_stale_compose(600)
    return {"messages": _messages(), "composing": any_composing()}


def _attr(row: object, name: str, default: object = "") -> object:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _compose_status(row: dict) -> str:
    compose = row.get("compose") if isinstance(row.get("compose"), dict) else {}
    return str(compose.get("status") or "")


def _copy_rows(copies: object) -> list[dict]:
    out = []
    for copy in copies or []:
        body = str(_attr(copy, "body") or "")
        if not body.strip():
            continue
        out.append({"channel": str(_attr(copy, "channel") or ""), "body": body})
    return out


def _asset_rows(assets: object) -> list[dict]:
    out = []
    for asset in assets or []:
        rel = str(_attr(asset, "rel_path") or "")
        name = Path(rel).name
        if not name:
            continue
        out.append(
            {
                "kind": str(_attr(asset, "kind") or ""),
                "channel": str(_attr(asset, "channel") or ""),
                "format": str(_attr(asset, "format") or ""),
                "name": name,
                "relPath": rel,
            }
        )
    return out


def _draft_item(row: dict) -> dict | None:
    captions = row.get("captions") if isinstance(row.get("captions"), dict) else {}
    copies = _copy_rows(
        [{"channel": key, "body": captions.get(key)} for key in ("instagram", "telegram", "whatsapp")]
    )
    assets = []
    for item in row.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        assets.append(
            {
                "kind": str(item.get("kind") or ""),
                "channel": "",
                "format": "",
                "name": name,
                "relPath": "",
            }
        )
    status = _compose_status(row)
    if not copies and not assets and not status:
        return None
    return {
        "id": str(row.get("id") or ""),
        "title": "پیش‌نویس",
        "copies": copies,
        "assets": assets,
        "compose": status,
    }


STUDIO_JSON_TOKENS = 1600


async def _studio_json(prompt: str) -> dict:
    parsed = await complete_json(STUDIO_SYSTEM, prompt, surface="studio", max_tokens=STUDIO_JSON_TOKENS)
    if parsed.get("error") != "llm_bad_json":
        return parsed
    return await complete_json(
        STUDIO_SYSTEM,
        f"{prompt}\nفقط یک شیء JSON برگردان، بدون توضیح.",
        surface="studio",
        max_tokens=STUDIO_JSON_TOKENS + 600,
    )


def content_library(campaigns: list) -> dict:
    expire_stale_compose(600)
    compose_by: dict[str, str] = {}
    drafts: list[dict] = []
    rows = [row for row in _messages() if isinstance(row, dict)]
    for row in rows:
        if not isinstance(row, dict) or row.get("role") == "user":
            continue
        cid = str(row.get("campaignId") or "")
        status = _compose_status(row)
        if cid and status:
            if status == "running" or compose_by.get(cid) != "running":
                compose_by[cid] = status
        if not cid:
            draft = _draft_item(row)
            if draft:
                drafts.append(draft)
    items = []
    for campaign in campaigns or []:
        cid = str(_attr(campaign, "id") or "")
        copies = _copy_rows(_attr(campaign, "copies", []))
        assets = _asset_rows(_attr(campaign, "assets", []))
        status = compose_by.get(cid, "")
        if not copies and not assets and not status:
            continue
        title = str(_attr(campaign, "title") or "").strip() or "بدون عنوان"
        items.append(
            {
                "id": cid,
                "title": title,
                "copies": copies,
                "assets": assets,
                "compose": status,
            }
        )
    seen = {str(item.get("id") or "") for item in items}
    for row in rows:
        if not isinstance(row, dict) or row.get("role") == "user":
            continue
        cid = str(row.get("campaignId") or "")
        if not cid or cid in seen:
            continue
        item = _draft_item(row)
        if not item:
            continue
        item["id"] = cid
        item["title"] = "کمپین"
        items.append(item)
        seen.add(cid)
    return {"items": items, "drafts": drafts}


def any_composing() -> bool:
    for row in _messages():
        compose = row.get("compose") if isinstance(row.get("compose"), dict) else {}
        if compose.get("status") == "running":
            return True
    return False


async def attach_still(campaigns: CampaignService, campaign_id, media: dict | None) -> bool:
    return await _attach_still(campaigns, campaign_id, media)


async def _attach_still(campaigns: CampaignService, campaign_id, media: dict | None) -> bool:
    from app.services import chat_media_service

    if not media or str(media.get("kind") or "") != "image":
        return False
    path = chat_media_service.resolve(str(media.get("name") or ""))
    await campaigns.save_raw(campaign_id, "feed.png", path.read_bytes())
    return True


def copy_outputs(items: list[dict]) -> list[dict]:
    return _copy_outputs(items)


def _copy_outputs(items: list[dict]) -> list[dict]:
    from app.services import chat_media_service

    attachments = []
    for item in items:
        path = Path(item["path"])
        if not path.is_file():
            continue
        saved = chat_media_service.copy_file(path)
        attachments.append({"kind": saved["kind"], "name": saved["name"], "source": path.name})
    return attachments


def fallback_attachment(media: dict | None) -> list[dict]:
    return _fallback_attachment(media)


def _fallback_attachment(media: dict | None) -> list[dict]:
    if not media:
        return []
    kind = str(media.get("kind") or "")
    name = str(media.get("name") or "")
    if kind in {"image", "video"} and name:
        return [{"kind": kind, "name": name}]
    return []


def _update_message(message_id: str, fn) -> dict | None:
    ident = str(message_id or "").strip()
    with tenant_file_lock("studio"):
        rows = _messages()
        target = None
        for row in rows:
            if str(row.get("id") or "") == ident:
                target = row
                break
        if target is None:
            return None
        fn(target)
        _save(rows)
        return {"messages": rows, "row": target}


def set_compose(message_id: str, compose: dict) -> None:
    def apply(row: dict) -> None:
        row["compose"] = compose

    _update_message(message_id, apply)


def finish_compose(
    message_id: str,
    attachments: list[dict],
    *,
    status: str,
    error: str = "",
    job_id: str = "",
) -> bool:
    skipped = False

    def apply(row: dict) -> None:
        nonlocal skipped
        compose = row.get("compose") if isinstance(row.get("compose"), dict) else {}
        current = str(compose.get("jobId") or "")
        if job_id and current and current != job_id:
            skipped = True
            return
        row["compose"] = {
            "status": status,
            "startedAt": compose.get("startedAt") if compose else time.time(),
            "jobId": current or job_id,
            "error": error,
        }
        if attachments:
            row["attachments"] = attachments
            row["mediaKind"] = attachments[0]["kind"]
            row["mediaName"] = attachments[0]["name"]
        if status == "ready":
            text = str(row.get("text") or "")
            if "در حال ساخت" in text:
                row["text"] = text.replace(" در حال ساخت تصویر و ویدیو است.", "").replace("در حال ساخت تصویر و ویدیو است.", "").strip()

    updated = _update_message(message_id, apply)
    return bool(updated) and not skipped


def touch_compose_start(message_id: str, job_id: str) -> None:
    ident = str(job_id or "").strip()

    def apply(row: dict) -> None:
        compose = row.get("compose") if isinstance(row.get("compose"), dict) else {}
        if str(compose.get("jobId") or "") != ident:
            return
        if compose.get("status") != "running":
            return
        compose["startedAt"] = time.time()
        row["compose"] = compose

    _update_message(message_id, apply)


def expire_stale_compose(stale_sec: int) -> None:
    now = time.time()
    with tenant_file_lock("studio"):
        rows = _messages()
        changed = False
        for row in rows:
            compose = row.get("compose") if isinstance(row.get("compose"), dict) else None
            if not compose or compose.get("status") != "running":
                continue
            started = float(compose.get("startedAt") or 0)
            if started and now - started > stale_sec:
                compose["status"] = "failed"
                compose["error"] = "ساخت طول کشید؛ دوباره بساز."
                changed = True
                emit_later(
                    kind="studio",
                    surface="studio",
                    title="compose-failed",
                    status="failed",
                    stage="watchdog",
                    turn_id=str(row.get("id") or ""),
                    operation_id=str(row.get("campaignId") or ""),
                    payload={"error": "stale"},
                )
        if changed:
            _save(rows)


async def chat(text: str, campaigns: CampaignService, media: dict | None = None) -> dict:
    from app.services import chat_media_service, studio_compose_service

    raw = text.strip()
    spoken = chat_media_service.spoken_text(raw, media)
    user_msg = {"id": str(uuid4()), "role": "user", "text": spoken, "at": int(time.time())}
    if media:
        user_msg["mediaKind"] = media["kind"]
        user_msg["mediaName"] = media["name"]
    with tenant_file_lock("studio"):
        rows = _messages()
        rows.append(user_msg)
        _save(rows)
    emit_later(
        kind="chat",
        surface="studio",
        title="studio-user",
        conversation_id="studio",
        turn_id=user_msg["id"],
        payload={"role": "user", "text": spoken, "id": user_msg["id"]},
    )
    if _is_greeting(spoken) and not media:
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": "بگو برای اینستاگرام، تلگرام یا واتساپ چه پستی می‌خواهی. تصویر کالا را هم می‌توانی پیوست کنی.",
            "at": int(time.time()),
        }
        with tenant_file_lock("studio"):
            rows = _messages()
            rows.append(assistant)
            _save(rows)
        emit_later(
            kind="chat",
            surface="studio",
            title="studio-assistant",
            conversation_id="studio",
            turn_id=assistant["id"],
            payload={"role": "assistant", "text": assistant["text"], "id": assistant["id"]},
        )
        return {"messages": rows, "campaignId": ""}
    prompt = _studio_prompt(spoken, media=media)
    parsed = await _studio_json(prompt)
    if parsed.get("error"):
        reply = str(parsed.get("reply") or "مدل پاسخ نداد. پیام را دوباره بفرست.").strip()
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply,
            "at": int(time.time()),
        }
        with tenant_file_lock("studio"):
            rows = _messages()
            rows.append(assistant)
            _save(rows)
        emit_later(
            kind="chat",
            surface="studio",
            title="studio-assistant",
            conversation_id="studio",
            turn_id=assistant["id"],
            status="failed",
            stage="llm",
            payload={"role": "assistant", "text": reply, "id": assistant["id"], "error": True},
        )
        return {"messages": rows, "campaignId": ""}
    title = _real_copy(parsed.get("title"), limit=80) or "کمپین جدید"
    subtitle = _real_copy(parsed.get("subtitle"), limit=120)
    cta = _real_copy(parsed.get("cta"), limit=40) or "ببین"
    captions = _clip_captions(
        {
            "instagram": parsed.get("instagram"),
            "telegram": parsed.get("telegram"),
            "whatsapp": parsed.get("whatsapp") or parsed.get("telegram") or parsed.get("instagram"),
        }
    )
    reply = _real_copy(parsed.get("reply"), limit=400)
    if not reply:
        reply = captions["instagram"][:180] or captions["telegram"][:180] or captions["whatsapp"][:180]
    reply = guard_output(reply)
    image_prompt = str(parsed.get("imagePrompt") or "").strip()
    slug = f"c{uuid4().hex[:12]}"
    campaign_id = ""
    attachments: list[dict] = []
    has_copy = bool(captions["instagram"] or captions["telegram"] or captions["whatsapp"])
    want_compose = parsed.get("compose") is True or bool(media and media.get("kind") == "image")
    if has_copy and parsed.get("compose") is not False:
        want_compose = True
    if parsed.get("compose") is False and not (media and media.get("kind") == "image"):
        want_compose = False
    if not has_copy and not want_compose:
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply or "بگو چه پستی می‌خواهی؛ کپشن را همین‌جا می‌نویسم.",
            "at": int(time.time()),
        }
        with tenant_file_lock("studio"):
            rows = _messages()
            rows.append(assistant)
            _save(rows)
        return {"messages": rows, "campaignId": ""}
    try:
        campaign = await campaigns.create(
            slug=slug,
            pillar="shop",
            title=title,
            subtitle=subtitle,
            cta=cta,
            instagram_caption=captions["instagram"],
            telegram_caption=captions["telegram"],
            whatsapp_caption=captions["whatsapp"],
        )
        campaign_id = str(campaign.id)
        await _attach_still(campaigns, campaign.id, media)
    except Exception as exc:
        emit_later(
            kind="studio",
            surface="studio",
            title="campaign-create-failed",
            status="failed",
            conversation_id="studio",
            payload={"error": str(exc)[:200]},
        )
        attachments = _fallback_attachment(media)
    if not reply:
        reply = f"کمپین «{title}» آماده شد." if campaign_id else "کپشن را نوشتم؛ کمپین ذخیره نشد."
    if want_compose and campaign_id:
        reply = f"{reply} در حال ساخت تصویر و ویدیو است."
    assistant = {
        "id": str(uuid4()),
        "role": "assistant",
        "text": reply,
        "at": int(time.time()),
        "captions": captions,
        **({"campaignId": campaign_id} if campaign_id else {}),
        **({"attachments": attachments} if attachments else {}),
    }
    if attachments:
        assistant["mediaKind"] = attachments[0]["kind"]
        assistant["mediaName"] = attachments[0]["name"]
    with tenant_file_lock("studio"):
        rows = _messages()
        rows.append(assistant)
        _save(rows)
    if want_compose and campaign_id:
        studio_compose_service.start(
            message_id=assistant["id"],
            campaign_id=campaign_id,
            media=media,
            title=title,
            image_prompt=image_prompt,
        )
        with tenant_file_lock("studio"):
            rows = _messages()
    emit_later(
        kind="chat",
        surface="studio",
        title="studio-assistant",
        conversation_id="studio",
        turn_id=assistant["id"],
        operation_id=campaign_id,
        payload={"role": "assistant", "text": assistant["text"], "id": assistant["id"], "campaignId": campaign_id},
    )
    return {"messages": rows, "campaignId": campaign_id}


def mark_published(message_id: str, platform: str) -> dict:
    key = str(platform or "").strip().lower()
    ident = str(message_id or "").strip()
    if key not in {"instagram", "telegram", "whatsapp"} or not ident:
        raise ValueError("پیام یا کانال ارسال نامعتبر است")
    now = int(time.time())

    def apply(row: dict) -> None:
        published = dict(row.get("published") or {}) if isinstance(row.get("published"), dict) else {}
        published[key] = now
        row["published"] = published

    result = _update_message(ident, apply)
    if result is None:
        raise ValueError("پیام استودیو پیدا نشد")
    return {"messages": result["messages"], "ok": True}


def recently_published(message_id: str, platform: str, window: int = 60) -> bool:
    ident = str(message_id or "").strip()
    key = str(platform or "").strip().lower()
    for row in _messages():
        if str(row.get("id") or "") != ident:
            continue
        published = row.get("published") if isinstance(row.get("published"), dict) else {}
        ts = float(published.get(key) or 0)
        return bool(ts) and time.time() - ts < window
    return False


def update_captions(message_id: str, captions: dict) -> dict:
    clipped = _clip_captions(captions if isinstance(captions, dict) else {})
    campaign_id = ""

    def apply(row: dict) -> None:
        nonlocal campaign_id
        row["captions"] = clipped
        campaign_id = str(row.get("campaignId") or "")

    result = _update_message(message_id, apply)
    if result is None:
        raise ValueError("پیام استودیو پیدا نشد")
    return {"messages": result["messages"], "captions": clipped, "campaignId": campaign_id}


async def regenerate(*, message_id: str, part: str, campaigns: CampaignService, media: dict | None = None) -> dict:
    from app.services import studio_compose_service

    ident = str(message_id or "").strip()
    with tenant_file_lock("studio"):
        rows = _messages()
        target = None
        for row in rows:
            if str(row.get("id") or "") == ident and row.get("role") == "assistant":
                target = row
                break
        if target is None:
            raise ValueError("پیام استودیو پیدا نشد")
        kind = part.strip().lower()
        campaign_id = str(target.get("campaignId") or "")
        captions = dict(target.get("captions") or {}) if isinstance(target.get("captions"), dict) else {}
    if kind == "caption":
        parsed = await complete_json(
            STUDIO_SYSTEM,
            (
                "همین پست را با کپشن تازه بنویس. کپشن قبلی اینستاگرام: "
                f"{captions.get('instagram') or ''}\nتلگرام: {captions.get('telegram') or ''}\n"
                f"واتساپ: {captions.get('whatsapp') or ''}"
            ),
            surface="studio",
            max_tokens=1600,
        )
        if parsed.get("error"):
            raise ValueError(str(parsed.get("reply") or "مدل کپشن تازه نداد."))
        instagram = str(parsed.get("instagram") or captions.get("instagram") or "")
        telegram = str(parsed.get("telegram") or captions.get("telegram") or "")
        whatsapp = str(parsed.get("whatsapp") or captions.get("whatsapp") or telegram)
        clipped = _clip_captions({"instagram": instagram, "telegram": telegram, "whatsapp": whatsapp})
        reply = str(parsed.get("reply") or "").strip()

        def apply(row: dict) -> None:
            row["captions"] = clipped
            if reply:
                row["text"] = reply

        result = _update_message(ident, apply)
        if campaign_id:
            await campaigns.update_copy(
                UUID(campaign_id),
                title=None,
                subtitle=None,
                cta=None,
                instagram_caption=clipped["instagram"],
                telegram_caption=clipped["telegram"],
                whatsapp_caption=clipped["whatsapp"],
            )
        emit_later(
            kind="studio",
            surface="studio",
            title="caption-regenerated",
            turn_id=ident,
            operation_id=campaign_id,
            payload={"ok": True},
        )
        return {"messages": (result or {}).get("messages") or _messages()}
    if kind == "image":
        if not campaign_id:
            raise ValueError("کمپین این پست نیست")
        if media and str(media.get("kind") or "") == "image":
            await _attach_still(campaigns, UUID(campaign_id), media)
        studio_compose_service.start(
            message_id=ident,
            campaign_id=campaign_id,
            media=media,
            title=str(target.get("text") or "")[:80],
            image_prompt="",
        )
        return {"messages": _messages()}
    raise ValueError("فقط عکس یا کپشن را می‌توان دوباره ساخت")
