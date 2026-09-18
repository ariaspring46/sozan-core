from __future__ import annotations

import json
import time
from pathlib import Path

from config import settings
from engine.compose import compose_campaign_dir, save_brief, zip_out
from engine.llm import complete_json
from engine.persona import character_path, avatar_path, system_prompt

PILLARS = ("shop", "gateway", "panel")
VALID_PILLARS = set(PILLARS)
VALID_MOODS = {
    "setup",
    "wit",
    "panel",
    "gateway",
    "late-night",
    "local",
    "privacy",
    "shop",
}


def _read_state() -> dict:
    path = settings.state_file
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(data: dict) -> None:
    settings.state_path.mkdir(parents=True, exist_ok=True)
    settings.state_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _next_pillar(state: dict) -> str:
    last = str(state.get("lastPillar") or "").strip()
    if last in VALID_PILLARS:
        idx = PILLARS.index(last)
        return PILLARS[(idx + 1) % len(PILLARS)]
    return PILLARS[0]


def _seed_raw(campaign_dir: Path) -> dict:
    """تصاویر خام برند را در raw/ کپی می‌کند با نام‌گذاری که pick درست کار کند."""
    raw = campaign_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    seeded = {}
    char_p = character_path()
    av_p = avatar_path()
    if char_p.is_file():
        dest = raw / "story-character.png"
        dest.write_bytes(char_p.read_bytes())
        seeded["story"] = dest
    if av_p.is_file():
        dest = raw / "feed-character.png"
        dest.write_bytes(av_p.read_bytes())
        seeded["feed"] = dest
    return seeded


async def generate(*, pillar: str | None = None, mood: str | None = None) -> dict:
    """یک کمپین تبلیغاتی برند سوزان تولید می‌کند (تصویر/ویدیو/کپشن) و روی دیسک ذخیره می‌کند."""
    state = _read_state()
    if pillar and pillar not in VALID_PILLARS:
        return {"ok": False, "error": f"ستون نامعتبر: {pillar}. یکی از {', '.join(PILLARS)}."}
    chosen_pillar = pillar or _next_pillar(state)
    if mood and mood not in VALID_MOODS:
        return {"ok": False, "error": f"حال نامعتبر: {mood}."}

    system = system_prompt(chosen_pillar, mood)
    user = f"برای ستون «{chosen_pillar}» سوزان یک پست برند بساز. حال: {mood or 'خودکار'}."
    parsed = await complete_json(system, user)
    if parsed.get("error"):
        return {
            "ok": False,
            "error": str(parsed.get("reply") or parsed.get("error")),
            "pillar": chosen_pillar,
            "mood": mood or "",
        }

    title = str(parsed.get("title") or "").strip() or "سوزان"
    subtitle = str(parsed.get("subtitle") or "").strip()
    cta = str(parsed.get("cta") or "").strip() or "از سوزان بپرس"
    instagram = str(parsed.get("instagram") or "").strip()
    telegram = str(parsed.get("telegram") or "").strip() or instagram
    pillar_from_llm = str(parsed.get("pillar") or "").strip()
    if pillar_from_llm in VALID_PILLARS:
        chosen_pillar = pillar_from_llm
    mood_from_llm = str(parsed.get("mood") or "").strip() or (mood or "")

    slug = f"sozan-{chosen_pillar}-{int(time.time())}"
    campaign_dir = settings.output_path / slug
    campaign_dir.mkdir(parents=True, exist_ok=True)

    brief = {
        "pillar": chosen_pillar,
        "mood": mood_from_llm,
        "title": title,
        "subtitle": subtitle,
        "cta": cta,
        "instagram_caption": instagram,
        "telegram_caption": telegram,
    }
    save_brief(campaign_dir, brief)
    seeded = _seed_raw(campaign_dir)
    if not seeded:
        return {
            "ok": False,
            "slug": slug,
            "error": "تصویر کاراکتر برند پیدا نشد. brand/character.png و brand/character-avatar.png را چک کن.",
        }

    audio = settings.audio_bed_path
    produced = compose_campaign_dir(campaign_dir, fonts_dir=settings.fonts_path, audio_bed=audio)
    archive = zip_out(campaign_dir)

    now = int(time.time())
    history = state.get("history", []) if isinstance(state.get("history"), list) else []
    history.append(
        {
            "slug": slug,
            "pillar": chosen_pillar,
            "mood": mood_from_llm,
            "title": title,
            "at": now,
        }
    )
    history = history[-50:]
    new_state = {
        "lastRunAt": now,
        "lastPillar": chosen_pillar,
        "count": int(state.get("count", 0)) + 1,
        "history": history,
    }
    _write_state(new_state)

    return {
        "ok": True,
        "slug": slug,
        "pillar": chosen_pillar,
        "mood": mood_from_llm,
        "title": title,
        "subtitle": subtitle,
        "cta": cta,
        "out_dir": str(campaign_dir / "out"),
        "zip": str(archive),
        "produced": {k: v for k, v in produced.items() if not k.endswith("-error")},
        "errors": {k: v for k, v in produced.items() if k.endswith("-error")},
    }


def status() -> dict:
    state = _read_state()
    return {
        "enabled": True,
        "cadenceMinutes": settings.cadence_minutes,
        "lastRunAt": state.get("lastRunAt"),
        "lastPillar": state.get("lastPillar"),
        "count": state.get("count", 0),
        "recent": (state.get("history") or [])[-10:],
    }


async def run_scheduled() -> dict | None:
    """اگر از آخرین اجرا بیشتر از cadence_minutes گذشته باشد، یک کمپین تولید می‌کند."""
    state = _read_state()
    last = int(state.get("lastRunAt") or 0)
    now = int(time.time())
    cadence_sec = max(1, settings.cadence_minutes) * 60
    if now - last < cadence_sec:
        return None
    return await generate()


def list_campaigns() -> list[dict]:
    """لیست کمپین‌های تولیدشده روی دیسک."""
    out_dir = settings.output_path
    if not out_dir.is_dir():
        return []
    rows = []
    for path in sorted(out_dir.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        brief_path = path / "brief.json"
        if not brief_path.is_file():
            continue
        try:
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            brief = {}
        rows.append(
            {
                "slug": path.name,
                "pillar": brief.get("pillar", ""),
                "mood": brief.get("mood", ""),
                "title": brief.get("title", path.name),
                "has_zip": (path / f"{path.name}.zip").is_file(),
                "out_files": sorted(p.name for p in (path / "out").iterdir()) if (path / "out").is_dir() else [],
            }
        )
    return rows