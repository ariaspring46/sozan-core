from __future__ import annotations

import json
import zipfile
from pathlib import Path

from config import settings
from engine.overlay import OverlayService
from engine.persona import load_persona
from engine.video import VideoComposeService

FEED_NAMES = ("feed", "square", "1x1")
STORY_NAMES = ("story", "reel", "9x16", "portrait")
WIDE_NAMES = ("wide", "16x9", "landscape")


def load_brief(campaign_dir: Path) -> dict:
    path = campaign_dir / "brief.json"
    if not path.exists():
        raise FileNotFoundError(f"brief.json missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_brief(campaign_dir: Path, brief: dict) -> None:
    campaign_dir.mkdir(parents=True, exist_ok=True)
    (campaign_dir / "brief.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _pick(raw: Path, needles: tuple[str, ...]) -> list[Path]:
    files = sorted(p for p in raw.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    matched = [p for p in files if any(n in p.stem.lower() for n in needles)]
    return matched or files


def _about_block() -> str:
    try:
        persona = load_persona()
        return persona.get("promise", "") or ""
    except Exception:
        return ""


def write_captions(out: Path, brief: dict, about: str = "") -> Path:
    ig = brief.get("instagram_caption") or ""
    tg = brief.get("telegram_caption") or ""
    about_block = ""
    if about.strip():
        about_block = "\n\n## درباره سوزان\n\n" + about.strip() + "\n"
    text = (
        "# کپشن‌ها\n\n## اینستاگرام\n\n"
        + ig.strip()
        + "\n\n## تلگرام\n\n"
        + tg.strip()
        + about_block
    )
    dest = out / "captions.md"
    dest.write_text(text, encoding="utf-8")
    return dest


def compose_campaign_dir(
    campaign_dir: Path,
    *,
    fonts_dir: Path,
    audio_bed: Path | None,
    logo: Path | None = None,
) -> dict[str, str]:
    """brief.json + raw/ → out/ (overlays + videos + captions). مستقل از پروژهٔ سوزان."""
    brief = load_brief(campaign_dir)
    raw = campaign_dir / "raw"
    out = campaign_dir / "out"
    overlays = campaign_dir / "overlays"
    out.mkdir(parents=True, exist_ok=True)
    overlay = OverlayService(fonts_dir)
    video = VideoComposeService()

    if logo is None or not logo.is_file():
        from engine.persona import logo_path

        logo = logo_path()

    title = brief["title"]
    subtitle = brief.get("subtitle") or ""
    cta = brief.get("cta") or ""
    render_kw = dict(title=title, subtitle=subtitle, cta=cta, logo_path=logo)

    produced: dict[str, str] = {}
    feed_src = _pick(raw, FEED_NAMES)[0]
    story_list = _pick(raw, STORY_NAMES)
    wide_list = _pick(raw, WIDE_NAMES)

    produced["ig-feed"] = str(
        overlay.render(feed_src, out / "ig-feed.png", format_name="feed", **render_kw)
    )
    produced["tg-post"] = str(
        overlay.render(feed_src, out / "tg-post.png", format_name="feed", **render_kw)
    )
    story_src = story_list[0]
    produced["ig-story"] = str(
        overlay.render(story_src, out / "ig-story.png", format_name="story", **render_kw)
    )
    if wide_list:
        produced["tg-wide"] = str(
            overlay.render(wide_list[0], out / "tg-wide.png", format_name="wide", **render_kw)
        )

    # reel: تا ۵ فریم story (یا پر با feed)
    reel_frames: list[Path] = []
    sources = story_list[:5] if len(story_list) >= 2 else (story_list + _pick(raw, FEED_NAMES))[:5]
    for i, src in enumerate(sources[:5]):
        frame = overlays / f"reel-{i:02d}.png"
        overlay.render(src, frame, format_name="story", **render_kw)
        reel_frames.append(frame)
    audio = audio_bed if audio_bed and audio_bed.exists() else None
    try:
        produced["ig-reel"] = str(
            video.compose(reel_frames, out / "ig-reel.mp4", format_name="reel", audio=audio)
        )
    except Exception as exc:
        produced["ig-reel-error"] = str(exc)[-400:]

    if wide_list:
        wide_frames = []
        for i, src in enumerate((wide_list + _pick(raw, FEED_NAMES))[:4]):
            frame = overlays / f"wide-{i:02d}.png"
            overlay.render(src, frame, format_name="wide", **render_kw)
            wide_frames.append(frame)
        try:
            produced["tg-video"] = str(
                video.compose(wide_frames, out / "tg-video.mp4", format_name="wide", audio=audio)
            )
        except Exception as exc:
            produced["tg-video-error"] = str(exc)[-400:]

    write_captions(out, brief, _about_block())
    produced["captions"] = str(out / "captions.md")
    return produced


def zip_out(campaign_dir: Path) -> Path:
    out = campaign_dir / "out"
    dest = campaign_dir / f"{campaign_dir.name}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out))
    return dest