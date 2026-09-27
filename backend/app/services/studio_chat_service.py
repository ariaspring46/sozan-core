from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from uuid import UUID, uuid4

from app.services.campaign_service import CampaignService
from app.services.claims_guard import check as _claim_check
from app.services.llm import complete_json
from app.services.observe_client import emit_later
from app.services.persian_text import guard_output, sanitize_persian
from app.services.tenant_lock import tenant_file_lock
from app.state_store import read_json, write_json

STUDIO_SYSTEM = """تو استودیوی محتوای سوزان هستی. فقط یک شیء JSON برگردان؛ متن بیرون JSON ننویس.
کلیدها فقط این‌هاست: reply, instagram, telegram, whatsapp, imagePrompt, editKind.
کپشن را مشتری می‌خواند. در کپشن از ساخت عکس، زاویه، پس‌زمینه و آماده شدن عکس حرف نزن. آن حرف فقط مال reply است.
ویژگی کالا (جنس، اجزا، اندازه، دوام، اصالت، موجودی، ارسال، ضمانت، قیمت) را فقط اگر در حرف فروشنده یا کاتالوگ آمده بنویس. حس و سبک آزاد است.
اگر اسم کالا معلوم است و کاربر پست، استوری، ریلز، کپشن یا عکس خواست، هر سه کپشن را فارسی، دربارهٔ خود کالا، و بدون هشتگ لاتین پر کن.
اگر اسم کالا معلوم نیست، هر سه کپشن را خالی بگذار.
هر کپشن را با جملهٔ کامل و نقطه تمام کن. فقط دربارهٔ کالای همین درخواست بنویس.
اسم کالا باید در هر سه کپشن بیاید.
imagePrompt یک جملهٔ انگلیسی است و ویژگی نگفته را در آن نیاور. اگر کالا گردنبند است بنویس full necklace laid out in a long loop. واژهٔ فارسی ممنوع.
editKind یکی از background، scene، none است. background یعنی فقط پس‌زمینه عوض شود. scene یعنی کالا داخل صحنهٔ تازه برود، مثل جعبه یا دست یا کنار شیء دیگر.
جملهٔ «در حال ساخت» را ننویس؛ کد آن را اضافه می‌کند.
instagram حدود ۲۵۰ تا ۴۰۰ کاراکتر، telegram حداکثر ۴۰۰، whatsapp حداکثر ۲۸۰."""
STUB_COPY = frozenset({"متن فارسی", "تیتر کوتاه", "title", "reply", "cta", "subtitle", "کمپین جدید", "ببین"})

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


_CLAIM_WORDS = ("خالص", "طلا", "الماس", "یاقوت", "عیار", "پلاتین", "برلیان")
_FLUFF = ("کیفیت بالا", "منحصر به فرد")
_SALES_CLAIMS = ("چرم طبیعی", "قابل سفارش", "ارسال رایگان", "ضمانت", "قیمت مناسب")
_HASHTAG_GUARDED = ("طلا", "الماس", "یاقوت", "پلاتین", "برلیان", "نقره", "چرم", "ابریشم", "فیروزه", "طبیعی", "ضمانت", "رایگان", "پرفروش", "دستساز", "دست‌ساز", "لاکچری", "فانتزی", "بدل", "بدلی")
_BACKSTAGE = ("عکس", "تصویر", "پس‌زمینه", "پس زمینه", "آماده شد", "آماده می‌کنیم", "آماده ميكنيم", "زاویه", "زاويه")
ASK_NAME = "اسم کالا و یکی دو ویژگی‌اش را بگو تا کپشن بنویسم."
SAMPLE_PHOTO = "این عکس نمونه است، نه عکس کالای خودت؛ عکس کالا را بفرست تا روی پس‌زمینهٔ تازه بنشانمش."
CLOSEUP_PHOTO = "برای کیفیت بهتر، عکسی نزدیک‌تر از کالا بفرست."
_PROMPT_FIELD = re.compile(
    r"(?:جنس|زاویه|پس‌زمینه|پس زمینه|رنگ|نور)\s*[:：]\s*.*?(?=(?:جنس|زاویه|پس‌زمینه|پس زمینه|رنگ|نور)\s*[:：]|[.!?؟\n]|$)"
)


def _strip_latin_tags(text: str) -> str:
    cleaned = re.sub(r"#[A-Za-z][\w-]*", "", text or "")
    cleaned = re.sub(r"[A-Za-z][A-Za-z0-9_-]*", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ،")


def _claim_source(spoken: str, allowed: str = "") -> str:
    return f"{spoken or ''} {allowed or ''}"


def _sentence_unclaimed(sentence: str, source: str) -> bool:
    if re.search(r"دست[\s\u200c-]*ساز", sentence) and not re.search(r"دست[\s\u200c-]*ساز", source):
        return True
    for word in (*_CLAIM_WORDS, *_FLUFF):
        if word in source:
            continue
        if re.search(rf"(?<![\u0600-\u06FF]){re.escape(word)}(?![\u0600-\u06FF])", sentence):
            return True
    return False


def _drop_unclaimed(text: str, spoken: str, allowed: str = "") -> str:
    source = _claim_source(spoken, allowed)
    parts = re.split(r"(?<=[.!؟\n])\s+", text or "")
    kept = [part for part in parts if part.strip() and not _sentence_unclaimed(part, source)]
    cleaned = re.sub(r"\s{2,}", " ", " ".join(kept))
    cleaned = re.sub(r"\s+([،.])", r"\1", cleaned).strip(" ،")
    if cleaned:
        return cleaned
    if _sentence_unclaimed(text or "", source):
        return _title_from_spoken(spoken)
    return ""


def _drop_prompt_fields(text: str) -> str:
    cleaned = _PROMPT_FIELD.sub(" ", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ،")


def _drop_sales_claims(text: str, spoken: str, allowed: str = "") -> str:
    source = _claim_source(spoken, allowed)
    cleaned = text or ""
    for claim in _SALES_CLAIMS:
        if claim in cleaned and claim not in source:
            cleaned = cleaned.replace(claim, " ")
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ،")


def _thin_caption(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    bare = value.strip(" .!؟")
    if _is_greeting(bare):
        return True
    return len(bare.split()) < 4


def _repair_rewrite(captions: dict, subject: str = "") -> dict:
    bodies = [str(captions.get(key) or "") for key in ("instagram", "telegram", "whatsapp")]
    best = max(bodies, key=len) if bodies else ""
    if _thin_caption(best):
        return captions
    if subject and subject not in best:
        return captions
    return {key: (best if _thin_caption(str(value or "")) else value) for key, value in captions.items()}


def progress_clause(*, image: bool, video: bool) -> str:
    if image and video:
        return "در حال ساخت تصویر و ویدیو است."
    if image:
        return "در حال ساخت تصویر است."
    if video:
        return "در حال ساخت ویدیو است."
    return ""


def _drop_video_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?؟])\s+", text or "")
    kept = [part for part in parts if part.strip() and "ویدیو" not in part and "ویدئو" not in part]
    return re.sub(r"\s{2,}", " ", " ".join(kept)).strip()


def _strip_progress(text: str) -> str:
    cleaned = text or ""
    for sentence in (
        "در حال ساخت تصویر و ویدیو است.",
        "در حال ساخت تصویر و ویدیو است",
        "در حال ساخت تصویر است.",
        "در حال ساخت تصویر است",
        "در حال ساخت ویدیو است.",
        "در حال ساخت ویدیو است",
    ):
        cleaned = cleaned.replace(sentence, " ")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _named_product(spoken: str) -> str:
    subject = _title_from_spoken(spoken)
    if not subject or subject in {"کالا", "کالای پیوست‌شده", "عکس", "تصویر"}:
        return ""
    if any(mark in subject for mark in ("همین کالا", "این کالا", "همین عکس", "این عکس", "پس‌زمینه", "پس زمینه")):
        return ""
    return subject


def _unnamed_product_request(spoken: str) -> bool:
    if not any(mark in (spoken or "") for mark in ("همین کالا", "این کالا", "همین عکس", "این عکس")):
        return False
    return not _named_product(spoken)


def _has_backstage(text: str) -> bool:
    return any(word in (text or "") for word in _BACKSTAGE)


def _drop_backstage(text: str) -> str:
    parts = re.split(r"(?<=[.!?؟\n])\s+", text or "")
    kept = [part for part in parts if part.strip() and not _has_backstage(part)]
    return re.sub(r"\s{2,}", " ", " ".join(kept)).strip()


def _missing_subject(captions: dict, subject: str) -> bool:
    words = [word for word in (subject or "").split() if len(word) > 1]
    if not words:
        return False
    for key in ("instagram", "telegram", "whatsapp"):
        text = str(captions.get(key) or "")
        if any(word not in text for word in words):
            return True
    return False


def _facts_text(spoken: str, extra: str = "") -> str:
    return f"{spoken or ''}\n{extra or ''}".strip()


def _drop_claim_sentences(text: str, claims: list[str]) -> str:
    parts = re.split(r"(?<=[.!?؟\n])\s+", text or "")
    kept = [part for part in parts if part.strip() and not any(claim and claim in part for claim in claims)]
    return re.sub(r"\s{2,}", " ", " ".join(kept)).strip()


def _edit_kind(parsed: dict, spoken: str, has_media: bool) -> str:
    kind = str((parsed or {}).get("editKind") or "").strip().lower()
    if kind in {"background", "scene", "none"}:
        return "" if kind == "none" else kind
    if not has_media:
        return ""
    if any(mark in (spoken or "") for mark in ("جعبه", "روی دست", "کادو", "مخمل")):
        return "scene"
    return "background"


def _clip_captions(captions: dict, *, spoken: str = "", drop_unclaimed: bool = False, allowed: str = "") -> dict:
    out = {}
    for key, limit in CAPTION_LIMITS.items():
        text = sanitize_persian(_strip_latin_tags(_real_copy(captions.get(key), limit=limit)), limit=limit)
        text = _drop_prompt_fields(text)
        text = _drop_sales_claims(text, spoken, allowed)
        if drop_unclaimed:
            text = _drop_unclaimed(text, spoken, allowed)
        if spoken:
            before = text
            text = _drop_foreign(text, spoken)
            if before and not text:
                subject = _title_from_spoken(spoken)
                text = f"{subject}." if subject else ""
        out[key] = _settle_caption(text)
    return out


def _settle_caption(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if re.search(r"[.!?؟]$", value):
        return value
    marks = [item.start() for item in re.finditer(r"[.!?؟]", value)]
    if marks:
        return value[: marks[-1] + 1].strip()
    return f"{value}."


def _foreign_subjects(spoken: str) -> list[str]:
    from app.services.turn_parse import parse_turn

    current = spoken or ""
    found: list[str] = []
    for row in _messages():
        if not isinstance(row, dict) or row.get("role") != "user":
            continue
        subject = parse_turn(str(row.get("text") or "")).subject
        if len(subject) < 3 or subject in current or subject in found:
            continue
        found.append(subject)
    return found


def _drop_foreign(text: str, spoken: str) -> str:
    cleaned = text or ""
    for subject in _foreign_subjects(spoken):
        if subject not in cleaned:
            continue
        parts = re.split(r"(?<=[.!؟\n])\s+", cleaned)
        kept = [part for part in parts if subject not in part]
        cleaned = re.sub(r"\s{2,}", " ", " ".join(kept)).strip()
    return cleaned


def _catalog_blob() -> str:
    try:
        from app.services.storefront_service import list_products

        rows = list_products().get("products") or []
    except Exception:
        return ""
    return " ".join(f"{row.get('title') or ''} {row.get('description') or ''}" for row in rows if isinstance(row, dict))


def _no_overlay_text(spoken: str) -> bool:
    from app.services.turn_parse import parse_turn

    return parse_turn(spoken).no_overlay


def _catalog_title(title: str) -> str:
    value = str(title or "").strip()
    if not value:
        return ""
    if re.search(r"[✨👋…]", value):
        return ""
    if re.search(r"[A-Za-z]{3,}", value) and not re.search(r"[\u0600-\u06FF]", value):
        return ""
    if any(mark in value for mark in ("آزمایش", "پست آزمایشی", "انتظارش را نداشتید")):
        return ""
    return value


_FORMAT_WORDS = ("اینستاگرام", "تلگرام", "واتساپ", "استوری", "ریلز", "کپشن", "پست", "کمپین", "عکس", "تصویر")


def _title_from_spoken(spoken: str) -> str:
    from app.services.turn_parse import parse_turn

    return parse_turn(spoken).subject


def _overlay_title(raw: str, spoken: str) -> str:
    return _title_from_spoken(spoken)[:36]


def _revises_caption(spoken: str) -> bool:
    from app.services.turn_parse import parse_turn

    return parse_turn(spoken).revise


def _latest_campaign_message(campaign_id: str = "") -> dict | None:
    preferred = str(campaign_id or "").strip()
    if preferred:
        for row in reversed(_messages()):
            if isinstance(row, dict) and str(row.get("campaignId") or "") == preferred:
                return row
    for row in reversed(_messages()):
        if isinstance(row, dict) and row.get("role") != "user" and str(row.get("campaignId") or "").strip():
            return row
    return None


def _local_post(spoken: str) -> dict:
    subject = _title_from_spoken(spoken) or "کالا"
    caption = f"{subject}."
    return {
        "reply": f"پست {subject} آماده شد.",
        "title": "" if _no_overlay_text(spoken) else subject,
        "subtitle": "",
        "cta": "",
        "instagram": caption,
        "telegram": caption,
        "whatsapp": caption,
        "compose": True,
        "imagePrompt": f"product photo of {subject}, studio light, no text, no logos, no people",
    }


def _image_prompt(parsed: dict, spoken: str) -> str:
    raw = str((parsed or {}).get("imagePrompt") or "").strip()
    if raw and not re.search(r"[\u0600-\u06FF]", raw):
        return raw[:800]
    return "studio product photograph, soft light, plain background, no text, no logos, no people"


def _hashtag_only(spoken: str) -> bool:
    text = spoken or ""
    if "هشتگ" not in text:
        return False
    return not any(mark in text for mark in ("پست", "استوری", "ریلز", "کپشن", "عکس", "تصویر"))


def _hashtag_list(text: str, spoken: str = "") -> list[str]:
    found = re.findall(r"#[\u0600-\u06FF0-9_‌]+", text or "")
    banned = [word for word in _HASHTAG_GUARDED if word not in (spoken or "")]
    uniq: list[str] = []
    for tag in found:
        if tag in uniq or any(word in tag for word in banned):
            continue
        uniq.append(tag)
    return uniq[:10]


def _tag_root(tag: str) -> str:
    return tag.lstrip("#").replace("\u200c", "").split("_")[0]


def _repeated_root(tags: list[str]) -> bool:
    roots = [_tag_root(tag) for tag in tags if tag]
    if len(roots) < 2:
        return False
    top = max(roots.count(root) for root in set(roots))
    return top > len(roots) / 2


def _balance_roots(tags: list[str]) -> list[str]:
    kept = [tag for tag in tags if tag]
    while _repeated_root(kept):
        roots = [_tag_root(tag) for tag in kept]
        dominant = max(set(roots), key=roots.count)
        for index in range(len(kept) - 1, -1, -1):
            if _tag_root(kept[index]) == dominant:
                del kept[index]
                break
        else:
            break
    return kept


def _normalize_hashtags(text: str, spoken: str = "") -> str:
    return " ".join(_hashtag_list(text, spoken))


def _guard_subject(spoken: str) -> str:
    if _unnamed_product_request(spoken):
        return ""
    return _named_product(spoken) or _title_from_spoken(spoken)


def _captions_of(parsed: dict, old: dict | None = None, *, spoken: str, allowed: str) -> dict:
    previous = old or {}
    return _clip_captions(
        {
            "instagram": parsed.get("instagram") or previous.get("instagram"),
            "telegram": parsed.get("telegram") or previous.get("telegram"),
            "whatsapp": parsed.get("whatsapp") or previous.get("whatsapp") or parsed.get("telegram") or previous.get("instagram"),
        },
        spoken=spoken,
        drop_unclaimed=True,
        allowed=allowed,
    )


def _caption_backstage(captions: dict) -> bool:
    return any(_has_backstage(str(captions.get(key) or "")) for key in ("instagram", "telegram", "whatsapp"))


def _needs_caption_retry(parsed: dict) -> bool:
    for key in ("instagram", "telegram", "whatsapp"):
        raw = str((parsed or {}).get(key) or "").strip()
        if len(raw) >= 80 and not re.search(r"[.!?؟]$", raw):
            return True
    return False


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
    blob = (
        f"درخواست همین جمله: {spoken}\n"
        f"فروشگاه: {cfg.get('storeName') or 'فروشگاه'}\n"
        f"شعار: {cfg.get('storeTagline') or ''}\n"
        "فقط دربارهٔ همین جمله بنویس. کالای پیام‌های قبلی را نام نبر.\n"
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


STUDIO_JSON_TOKENS = 2400
HASHTAG_SYSTEM = """فقط یک شیء JSON با کلیدهای reply, instagram, telegram, whatsapp.
کاربر فقط هشتگ خواسته. instagram را با ۵ تا ۱۰ هشتگ فارسی پر کن؛ هر کدام با # شروع شود و با فاصله جدا شوند.
ترکیب: خود کالا، سبکِ گفته‌شده، کاربرد اگر گفته شده (مثل هدیه)، و نام فروشگاه.
چندکلمه‌ای را با زیرخط بنویس، مثل #گردنبند_شیک.
ریشه یعنی کلمهٔ قبل از زیرخط. #گردنبند_شیک ریشهٔ گردنبند است.
حداکثر نیمی از هشتگ‌ها با نام کالا شروع شوند. بقیه با سبک، کاربرد یا نام فروشگاه شروع شوند، مثل #استایل_روزمره #هدیه #فروشگاه.
telegram و whatsapp همان هشتگ‌ها باشند. جملهٔ تبلیغاتی و عکس ننویس.
reply یک جملهٔ کامل فارسی باشد.
جنس، فلز، و نوع (فانتزی، بدل) را در هشتگ نیاور مگر اینکه کاربر همان را گفته باشد."""


async def _outside_claims(text: str, facts: str) -> list[str]:
    return await _claim_check(text, facts, complete=complete_json)


async def _purge_text(text: str, facts: str) -> str:
    claims = await _outside_claims(text, facts)
    if not claims:
        return text
    return _drop_claim_sentences(text, claims)


async def _studio_json(prompt: str, max_tokens: int = STUDIO_JSON_TOKENS) -> dict:
    parsed = await complete_json(STUDIO_SYSTEM, prompt, surface="studio", max_tokens=max_tokens)
    if parsed.get("error") != "llm_bad_json":
        return parsed
    return await complete_json(
        STUDIO_SYSTEM,
        f"{prompt}\nفقط یک شیء JSON برگردان، بدون توضیح.",
        surface="studio",
        max_tokens=max_tokens + 600,
    )


async def _ensure_english_prompt(parsed: dict, spoken: str, facts: str = "") -> dict:
    raw = str((parsed or {}).get("imagePrompt") or "").strip()
    if raw and not re.search(r"[\u0600-\u06FF]", raw):
        return parsed
    follow = await complete_json(
        "فقط JSON با کلید imagePrompt. یک جملهٔ انگلیسی. ویژگی‌ای که در facts نیست ننویس. اگر کالا گردنبند است بنویس full necklace laid out in a long loop. واژهٔ فارسی ممنوع.",
        f"{spoken}\nfacts:\n{facts}",
        surface="studio",
        max_tokens=220,
    )
    text = str(follow.get("imagePrompt") or "").strip()
    updated = dict(parsed or {})
    if text and not re.search(r"[\u0600-\u06FF]", text):
        updated["imagePrompt"] = text
    else:
        updated["imagePrompt"] = _image_prompt({}, spoken)
    return updated


async def _write_hashtags(spoken: str, into_id: str) -> dict:
    shop = ""
    try:
        from app.services.settings_service import get_settings

        shop = str((get_settings() or {}).get("storeName") or "")
    except Exception:
        shop = ""
    prompt = f"{spoken}\nنام فروشگاه: {shop or 'فروشگاه'}"
    def _tags_of(payload: dict) -> str:
        if payload.get("error"):
            return ""
        listed = _balance_roots(_hashtag_list(_normalize_hashtags(str(payload.get("instagram") or ""), spoken), spoken))
        return " ".join(listed)

    parsed = await complete_json(HASHTAG_SYSTEM, prompt, surface="studio", max_tokens=900)
    tags = _tags_of(parsed)
    if tags.count("#") < 5 or _repeated_root(_hashtag_list(tags, spoken)):
        parsed = await complete_json(HASHTAG_SYSTEM, prompt, surface="studio", max_tokens=900)
        tags = _tags_of(parsed)
    facts = _facts_text(spoken, _catalog_blob())
    tags = " ".join(_balance_roots(_hashtag_list(_normalize_hashtags(await _purge_text(tags, facts), spoken), spoken)))
    if tags.count("#") < 5 or _repeated_root(_hashtag_list(tags, spoken)):
        reply = "هشتگ‌ها را نتوانستم بنویسم. دوباره بگو."
        captions = {"instagram": "", "telegram": "", "whatsapp": ""}
    else:
        captions = {"instagram": tags, "telegram": tags, "whatsapp": tags}
        reply = _settle_caption(str(parsed.get("reply") or "هشتگ‌ها آماده شد.")) or "هشتگ‌ها آماده شد."
    assistant = {
        "id": str(uuid4()),
        "role": "assistant",
        "text": reply or "هشتگ‌ها آماده شد.",
        "at": int(time.time()),
        "captions": captions,
    }
    rows = _put_assistant(assistant, into_id)
    emit_later(
        kind="chat",
        surface="studio",
        title="studio-assistant",
        conversation_id="studio",
        turn_id=assistant["id"],
        payload={"role": "assistant", "text": assistant["text"], "id": assistant["id"]},
    )
    return {"messages": rows, "campaignId": ""}


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
        saved = chat_media_service.copy_file(path, sweep=False)
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


def begin_placeholder() -> str:
    ident = str(uuid4())
    row = {
        "id": ident,
        "role": "assistant",
        "text": "در حال ساخت.",
        "at": int(time.time()),
        "compose": {"status": "running", "startedAt": time.time(), "jobId": ident},
    }
    with tenant_file_lock("studio"):
        rows = _messages()
        rows.append(row)
        _save(rows)
    return ident


def _put_assistant(assistant: dict, into_id: str = "") -> list[dict]:
    if into_id:
        assistant["id"] = into_id

        def apply(row: dict) -> None:
            row.clear()
            row.update(assistant)

        updated = _update_message(into_id, apply)
        if updated:
            return updated["messages"]
    with tenant_file_lock("studio"):
        rows = _messages()
        rows.append(assistant)
        _save(rows)
        return rows


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
            row["text"] = _strip_progress(str(row.get("text") or ""))

    updated = _update_message(message_id, apply)
    return bool(updated) and not skipped


def append_note(message_id: str, sentence: str) -> None:
    note = (sentence or "").strip()
    if not note:
        return

    def apply(row: dict) -> None:
        text = str(row.get("text") or "")
        if note not in text:
            row["text"] = f"{text} {note}".strip()

    _update_message(message_id, apply)


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


async def _rewrite_existing(
    spoken: str,
    prior: dict,
    campaigns: CampaignService,
    into_id: str = "",
) -> dict:
    old = prior.get("captions") if isinstance(prior.get("captions"), dict) else {}
    campaign_id = str(prior.get("campaignId") or "")
    prior_blob = " ".join(str(old.get(key) or "") for key in ("instagram", "telegram", "whatsapp"))
    allowed = f"{_catalog_blob()} {prior_blob}"
    saved = str(prior.get("subject") or "")
    facts = _facts_text(f"{prior.get('facts') or ''}\n{spoken}", _catalog_blob())
    parsed: dict = {}
    try:
        parsed = await asyncio.wait_for(
            complete_json(
                STUDIO_SYSTEM,
                (
                    "همین پست را با دستور کاربر بازنویس. عکس نساز. compose را false کن. "
                    "هر سه کانال را با جملهٔ کامل بازنویس؛ هیچ‌کدام فقط «سلام» نباشد.\n"
                    f"اسم کالا «{saved}» باید در هر سه کانال باشد.\n"
                    f"دستور: {spoken}\n"
                    f"facts:\n{facts}\n"
                    f"کپشن اینستاگرام: {old.get('instagram') or ''}\n"
                    f"تلگرام: {old.get('telegram') or ''}\n"
                    f"واتساپ: {old.get('whatsapp') or ''}"
                ),
                surface="studio",
                max_tokens=STUDIO_JSON_TOKENS,
            ),
            timeout=90,
        )
    except Exception:
        parsed = {"error": "timeout"}
    if parsed.get("error"):
        captions = {
            "instagram": str(old.get("instagram") or ""),
            "telegram": str(old.get("telegram") or ""),
            "whatsapp": str(old.get("whatsapp") or ""),
        }
        reply = "کپشن همان پست ماند. دوباره کوتاه‌تر بگو."
    else:
        captions = _captions_of(parsed, old, spoken=spoken, allowed=allowed)
        if not captions["instagram"]:
            captions = _clip_captions(old, spoken=spoken, drop_unclaimed=True, allowed=allowed)
        reply = _real_copy(parsed.get("reply"), limit=400) or "کپشن همان پست عوض شد."
        if saved and _missing_subject(captions, saved):
            again = await complete_json(
                STUDIO_SYSTEM,
                f"بازنویسی را تکرار کن. اسم «{saved}» باید در هر سه کانال باشد.\nدستور: {spoken}\nfacts:\n{facts}",
                surface="studio",
                max_tokens=STUDIO_JSON_TOKENS,
            )
            if not again.get("error"):
                captions = _captions_of(again, old, spoken=spoken, allowed=allowed)
                reply = _real_copy(again.get("reply"), limit=400) or reply
    reply = _drop_sales_claims(_drop_prompt_fields(reply), spoken, allowed)
    captions = _repair_rewrite(captions, saved)
    if saved and _missing_subject(captions, saved):
        captions = _repair_rewrite(
            {
                "instagram": str(old.get("instagram") or ""),
                "telegram": str(old.get("telegram") or ""),
                "whatsapp": str(old.get("whatsapp") or ""),
            },
            saved,
        )
    captions = {key: _settle_caption(_drop_backstage(str(value or ""))) for key, value in captions.items()}
    captions = _repair_rewrite(captions, saved)
    claims = await _outside_claims("\n".join([reply, *captions.values()]), facts)
    if claims:
        reply = _drop_claim_sentences(reply, claims)
        captions = {key: _settle_caption(_drop_claim_sentences(str(value or ""), claims)) for key, value in captions.items()}
        captions = _repair_rewrite(captions, saved)
        if saved and _missing_subject(captions, saved):
            captions = _repair_rewrite(
                {
                    "instagram": str(old.get("instagram") or ""),
                    "telegram": str(old.get("telegram") or ""),
                    "whatsapp": str(old.get("whatsapp") or ""),
                },
                saved,
            )
    reply = guard_output(reply)

    def apply(row: dict) -> None:
        row["captions"] = captions
        row["text"] = reply

    updated = _update_message(str(prior.get("id") or ""), apply)
    placeholder = str(into_id or "").strip()
    if placeholder and placeholder != str(prior.get("id") or ""):

        def finish(row: dict) -> None:
            row["text"] = reply
            row["captions"] = captions
            if campaign_id:
                row["campaignId"] = campaign_id
            compose = dict(row.get("compose") or {}) if isinstance(row.get("compose"), dict) else {}
            compose["status"] = "done"
            compose.pop("error", None)
            row["compose"] = compose

        updated = _update_message(placeholder, finish) or updated
    rows = (updated or {}).get("messages") or _messages()
    try:
        if campaign_id:
            await campaigns.update_copy(
                UUID(campaign_id),
                title=None,
                subtitle=None,
                cta=None,
                instagram_caption=captions["instagram"],
                telegram_caption=captions["telegram"],
                whatsapp_caption=captions["whatsapp"],
            )
    except Exception:
        campaign_id = ""
    return {"messages": rows, "campaignId": campaign_id}


async def chat(text: str, campaigns: CampaignService, media: dict | None = None, into_id: str = "") -> dict:
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
        rows = _put_assistant(assistant, into_id)
        emit_later(
            kind="chat",
            surface="studio",
            title="studio-assistant",
            conversation_id="studio",
            turn_id=assistant["id"],
            payload={"role": "assistant", "text": assistant["text"], "id": assistant["id"]},
        )
        return {"messages": rows, "campaignId": ""}
    if _hashtag_only(spoken):
        return await _write_hashtags(spoken, into_id)
    preferred = ""
    try:
        from app.services.router_service import thread_campaign_id

        preferred = thread_campaign_id()
    except Exception:
        preferred = ""
    prior = _latest_campaign_message(preferred) if _revises_caption(spoken) else None
    if prior:
        return await _rewrite_existing(spoken, prior, campaigns, into_id=into_id)
    prompt = _studio_prompt(spoken, media=media)
    parsed = await _studio_json(prompt)
    if _needs_caption_retry(parsed):
        parsed = await _studio_json(
            f"{prompt}\nهر کپشن را با نقطه تمام کن.",
            max_tokens=STUDIO_JSON_TOKENS + 800,
        )
    named = any(mark in spoken for mark in ("انگشتر", "گردنبند", "گوشواره", "آویز", "فیروزه", "کفش", "پیراهن", "کیف", "دستبند"))
    if parsed.get("error") and named:
        parsed = await _studio_json(prompt)
    if parsed.get("error") and (_revises_caption(spoken) or not named):
        reply = str(parsed.get("reply") or "مدل پاسخ نداد. پیام را دوباره بفرست.").strip()
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply,
            "at": int(time.time()),
        }
        rows = _put_assistant(assistant, into_id)
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
    if parsed.get("error"):
        parsed = _local_post(spoken)
    allowed = _catalog_blob()
    title = "" if _no_overlay_text(spoken) else _title_from_spoken(spoken)
    subtitle = ""
    cta = ""
    captions = _captions_of(parsed, spoken=spoken, allowed=allowed)
    has_media = bool(media and media.get("kind") == "image")
    subject_name = _named_product(spoken)
    facts = _facts_text(spoken, allowed)
    if _unnamed_product_request(spoken):
        captions = {key: "" for key in captions}
    elif _caption_backstage(captions):
        parsed = await _studio_json(f"{prompt}\nدر کپشن از عکس، تصویر، پس‌زمینه، زاویه و آماده شدن عکس حرف نزن.")
        captions = _captions_of(parsed, spoken=spoken, allowed=allowed)
        if _caption_backstage(captions):
            captions = {key: _settle_caption(_drop_backstage(str(value or ""))) for key, value in captions.items()}
    if subject_name and any(_thin_caption(str(captions.get(key) or "")) for key in ("instagram", "telegram", "whatsapp")):
        again = await _studio_json(
            f"{prompt}\nهر سه کپشن را با دست‌کم دو جملهٔ کامل بنویس و اسم «{subject_name}» در هر کدام باشد. "
            f"ویژگی را فقط از facts بنویس.\nfacts:\n{facts}"
        )
        if not again.get("error"):
            parsed = again
            captions = _captions_of(parsed, spoken=spoken, allowed=allowed)
    reply = _real_copy(parsed.get("reply"), limit=400)
    if not reply:
        reply = captions["instagram"][:180] or captions["telegram"][:180] or captions["whatsapp"][:180]
    reply = guard_output(_drop_sales_claims(_drop_prompt_fields(reply), spoken, allowed))
    if _unnamed_product_request(spoken) and ASK_NAME not in reply:
        reply = f"{reply} {ASK_NAME}".strip()
    image_prompt = _image_prompt(parsed, spoken)
    slug = f"c{uuid4().hex[:12]}"
    campaign_id = ""
    attachments: list[dict] = []
    has_copy = bool(captions["instagram"] or captions["telegram"] or captions["whatsapp"])
    want_compose = has_media or has_copy
    if want_compose:
        parsed = await _ensure_english_prompt(parsed, spoken, facts)
        image_prompt = _image_prompt(parsed, spoken)
        blob = "\n".join([reply, image_prompt, *[str(captions.get(key) or "") for key in captions]])
        claims = await _outside_claims(blob, facts)
        if claims:
            reply = guard_output(_drop_claim_sentences(reply, claims))
            image_prompt = _drop_claim_sentences(image_prompt, claims)
            captions = {
                key: _settle_caption(_drop_claim_sentences(str(value or ""), claims)) for key, value in captions.items()
            }
        if subject_name and (_missing_subject(captions, subject_name) or not any(captions.values())):
            parsed = await _studio_json(
                f"{prompt}\nاسم «{subject_name}» در هر سه کپشن باشد. ویژگی را فقط از facts بنویس.\nfacts:\n{facts}"
            )
            captions = _captions_of(parsed, spoken=spoken, allowed=allowed)
            claims = await _outside_claims("\n".join(str(captions.get(key) or "") for key in captions), facts)
            if claims:
                captions = {
                    key: _settle_caption(_drop_claim_sentences(str(value or ""), claims)) for key, value in captions.items()
                }
        if _caption_backstage(captions):
            captions = {key: _settle_caption(_drop_backstage(str(value or ""))) for key, value in captions.items()}
        captions = _repair_rewrite(captions, subject_name)
        has_copy = bool(captions["instagram"] or captions["telegram"] or captions["whatsapp"])
    if not has_copy and not want_compose:
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply or "بگو چه پستی می‌خواهی؛ کپشن را همین‌جا می‌نویسم.",
            "at": int(time.time()),
        }
        rows = _put_assistant(assistant, into_id)
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
    reply = _strip_progress(reply)
    if want_compose and campaign_id and not has_media and subject_name and SAMPLE_PHOTO not in reply:
        reply = f"{reply} {SAMPLE_PHOTO}".strip()
    if want_compose and campaign_id:
        image_queued, video_queued = studio_compose_service.queued_outputs(has_image=True)
        if not video_queued:
            reply = _drop_video_sentences(reply)
        clause = progress_clause(image=image_queued, video=video_queued)
        if clause:
            reply = f"{reply} {clause}".strip()
    assistant = {
        "id": str(uuid4()),
        "role": "assistant",
        "text": reply,
        "at": int(time.time()),
        "captions": captions,
        "subject": subject_name,
        "facts": facts,
        **({"campaignId": campaign_id} if campaign_id else {}),
        **({"attachments": attachments} if attachments else {}),
        **({"imagePrompt": image_prompt} if image_prompt else {}),
    }
    if attachments:
        assistant["mediaKind"] = attachments[0]["kind"]
        assistant["mediaName"] = attachments[0]["name"]
    rows = _put_assistant(assistant, into_id)
    if want_compose and campaign_id:
        story = any(mark in spoken for mark in ("استوری", "ریلز"))
        studio_compose_service.start(
            message_id=assistant["id"],
            campaign_id=campaign_id,
            media=media,
            title=title,
            image_prompt=image_prompt,
            width=1080,
            height=1920 if story else 1080,
            edit=_edit_kind(parsed, spoken, has_media) == "scene",
            edit_kind=_edit_kind(parsed, spoken, has_media),
            subject=_guard_subject(spoken),
        )
        if os.environ.get("SOZAN_WORKER") == "1":
            await studio_compose_service.drain()
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
        prompt = str(target.get("imagePrompt") or "").strip()
        if not prompt or re.search(r"[\u0600-\u06FF]", prompt):
            prompt = _image_prompt({}, "")
        studio_compose_service.start(
            message_id=ident,
            campaign_id=campaign_id,
            media=media,
            title=str(target.get("text") or "")[:80],
            image_prompt=prompt,
        )
        return {"messages": _messages()}
    raise ValueError("فقط عکس یا کپشن را می‌توان دوباره ساخت")
