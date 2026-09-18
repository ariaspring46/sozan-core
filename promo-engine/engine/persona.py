"""موجود نماد برند — فانوس آینده.

اسناد هویت برند سوزان را می‌خواند، یک persona ساختاریافته می‌سازد،
و system prompt تولید می‌کند که صدای ثابت فانوس را در محتوای تبلیغاتی الزام می‌کند.
"""
from __future__ import annotations

import re
from pathlib import Path

from config import settings

PILLARS_ORDER = ("shop", "gateway", "panel")
PILLAR_LABELS = {
    "shop": "فروشگاه در چت",
    "gateway": "گیت‌وی ادمین",
    "panel": "پنل فروشنده",
}


def _read(name: str) -> str:
    path = settings.brand_path / name
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """بخشی از markdown را با heading شروع‌شده برمی‌گرداند تا heading بعدی."""
    pattern = rf"^#+\s*{re.escape(heading)}\s*$.*?(?=^#+\s|\Z)"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    return m.group(0).split("\n", 1)[1].strip() if "\n" in m.group(0) else ""


def _list_items(text: str) -> list[str]:
    """خطوط لیست markdown (- ...) را استخراج می‌کند."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("• "):
            items.append(line[2:].strip())
    return items


def _parse_pillars(text: str) -> list[dict]:
    """جدول pillars.md را می‌خواند: شناسه | ستون | حس | CTA"""
    pillars = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("شناسه", "id"):
            continue
        pid = cells[0].strip("`")
        if pid in PILLARS_ORDER:
            pillars.append(
                {
                    "id": pid,
                    "label": cells[1],
                    "feel": cells[2],
                    "cta": cells[3],
                }
            )
    # ترتیب ثابت
    by_id = {p["id"]: p for p in pillars}
    return [by_id[p] for p in PILLARS_ORDER if p in by_id] or pillars


def _parse_templates(templates_dir: Path) -> list[dict]:
    """قالب‌های کپشن را می‌خواند: # قالب: <name> + ## اینستاگرام + ## تلگرام"""
    moods = []
    if not templates_dir.is_dir():
        return moods
    for path in sorted(templates_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s*قالب:\s*(.+)$", text, re.MULTILINE)
        label = title_match.group(1).strip() if title_match else path.stem
        mood_id = path.stem
        instagram = _section(text, "اینستاگرام")
        telegram = _section(text, "تلگرام")
        moods.append(
            {
                "id": mood_id,
                "label": label,
                "instagram": instagram,
                "telegram": telegram,
            }
        )
    return moods


def _parse_palette(text: str) -> dict:
    """جدول پالت visual.md را می‌خواند."""
    palette = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("نقش", "role"):
            continue
        palette[cells[0]] = cells[1]
    return palette


def _parse_forbidden(text: str) -> list[str]:
    """بخش ممنوع از visual.md یا IDENTITY.md را می‌خواند."""
    section = _section(text, "ممنوع")
    if section:
        return _list_items(section)
    section = _section(text, "هرگز در تبلیغ نیاید")
    return _list_items(section)


def load_persona() -> dict:
    """persona ساختاریافته را از اسناد برند می‌سازد."""
    identity = _read("IDENTITY.md")
    character = _read("CHARACTER.md")
    pillars_text = _read("pillars.md")
    visual = _read("visual.md")

    voice = _section(identity, "لحن")
    promise = _section(identity, "وعدهٔ یک خط")
    char_desc = _section(identity, "کاراکتر") or character.strip()
    audience = _section(identity, "مخاطب")
    signature = _section(identity, "امضا")

    forbidden_identity = _list_items(_section(identity, "هرگز در تبلیغ نیاید"))
    forbidden_visual = _parse_forbidden(visual)
    forbidden = forbidden_identity or forbidden_visual

    pillars = _parse_pillars(pillars_text)
    moods = _parse_templates(settings.brand_path / "templates")
    palette = _parse_palette(visual)

    avatar = settings.brand_path / "character-avatar.png"
    character_img = settings.brand_path / "character.png"
    logo = settings.brand_path / "logo-mark.png"
    if not logo.is_file():
        logo = settings.brand_path / "logo.png"

    return {
        "name": "سوزان",
        "character": char_desc,
        "voice": voice,
        "promise": promise,
        "audience": audience,
        "signature": signature,
        "forbidden": forbidden,
        "pillars": pillars,
        "moods": moods,
        "palette": palette,
        "avatar": avatar.name,
        "has_avatar": avatar.is_file(),
        "has_character": character_img.is_file(),
        "has_logo": logo.is_file(),
    }


def avatar_path() -> Path:
    return settings.brand_path / "character-avatar.png"


def character_path() -> Path:
    return settings.brand_path / "character.png"


def logo_path() -> Path:
    mark = settings.brand_path / "logo-mark.png"
    return mark if mark.is_file() else settings.brand_path / "logo.png"


def _pillar_by_id(persona: dict, pillar: str) -> dict | None:
    for p in persona.get("pillars", []):
        if p["id"] == pillar:
            return p
    return None


def _mood_by_id(persona: dict, mood: str | None) -> dict | None:
    if not mood:
        return None
    for m in persona.get("moods", []):
        if m["id"] == mood:
            return m
    return None


def _mood_for_pillar(persona: dict, pillar: str) -> dict | None:
    """اگر mood مشخص نبود، قالبی که با pillar هم‌خانواده است را برمی‌گرداند."""
    return _mood_by_id(persona, pillar)


def system_prompt(pillar: str, mood: str | None = None) -> str:
    """system prompt فارسی می‌سازد که صدای فانوس را در ستون مشخص الزام می‌کند."""
    persona = load_persona()
    p = _pillar_by_id(persona, pillar)
    if p is None:
        p = {"id": pillar, "label": pillar, "feel": "", "cta": ""}

    mood_obj = _mood_by_id(persona, mood) or _mood_for_pillar(persona, pillar)
    example_block = ""
    if mood_obj:
        ig = (mood_obj.get("instagram") or "").strip()
        tg = (mood_obj.get("telegram") or "").strip()
        example_block = (
            f"\n\nقالب مرجع (حال «{mood_obj.get('label', mood_obj.get('id', ''))}»):\n"
            f"اینستاگرام:\n{ig}\n\nتلگرام:\n{tg}\n"
        )

    forbidden = "\n".join(f"- {item}" for item in persona.get("forbidden", [])) or "- چهرهٔ انسان به‌جای فانوس"

    return f"""تو فانوس آینده هستی — موجود نماد برند سوزان. نه انسان؛ پوستهٔ تیره، شعلهٔ گرم، چشم کهربایی.
صدای تو {persona.get('voice', 'کوتاه، گرم، غیرشرکتی، با شوخ‌طبعی خشک')}.
وعدهٔ یک خط: {persona.get('promise', 'در چت می‌سازی. از گیت‌وی می‌چرخانی. از پنل می‌فروشی.')}

این پست برای ستون «{p['label']}» است.
حس این ستون: {p.get('feel', '')}
CTA این ستون: {p.get('cta', '')}
{example_block}
ممنوعات (هرگز در متن نیاید):
{forbidden}

متن فارسی، کوتاه، بدون لحن اداری. هشتگ انگلیسی نگذار مگر نام برند.
کپشن اینستاگرام ۲ تا ۵ خط + ۳ تا ۶ هشتگ فارسی. کپشن تلگرام کوتاه‌تر.
تیتر حداکثر دو خط. CTA یک عبارت کوتاه.

فقط JSON برگردان:
{{"title":"تیتر کوتار فارسی","subtitle":"","cta":"عبارت کوتاه","instagram":"کپشن اینستاگرام","telegram":"کپشن تلگرام","pillar":"{pillar}","mood":"{mood or ''}"}}"""