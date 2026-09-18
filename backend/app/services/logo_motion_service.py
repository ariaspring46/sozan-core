from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from app.config import settings

# زمان‌بندی ثابت استینگ — مدل لوکال فقط شدت را تنظیم می‌کند
DEFAULT_BOARD = {
    "duration": 6.0,
    "fps": 30,
    "energy": 1.0,
}

SIZES = {
    "reel": (1080, 1920),
    "feed": (1080, 1080),
    "wide": (1920, 1080),
}

BG = (18, 16, 14)
ACCENT = (196, 92, 38)
SOFT = (232, 168, 124)
EMBER = (255, 186, 120)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _ease(t: float) -> float:
    t = _clamp(t)
    return 1 - (1 - t) ** 3


def _ease_in_out(t: float) -> float:
    t = _clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _smooth(t: float, a: float, b: float) -> float:
    if b <= a:
        return 1.0 if t >= a else 0.0
    return _ease_in_out((t - a) / (b - a))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mul_alpha(im: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return im
    out = im.copy()
    a = out.split()[-1].point(lambda p: int(p * _clamp(alpha)))
    out.putalpha(a)
    return out


def _knockout_dark(im: Image.Image, thresh: int = 32) -> Image.Image:
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r <= thresh and g <= thresh and b <= thresh:
                px[x, y] = (r, g, b, 0)
    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im


def _fit(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    im = im.convert("RGBA")
    scale = min(max_w / max(im.width, 1), max_h / max(im.height, 1))
    nw = max(1, int(im.width * scale))
    nh = max(1, int(im.height * scale))
    if (nw, nh) != im.size:
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    return im


def _make_glow(im: Image.Image, radius: int, color: tuple[int, int, int], strength: float = 1.15) -> Image.Image:
    pad = radius * 2
    canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    canvas.paste(im, (pad, pad), im)
    alpha = canvas.split()[-1].filter(ImageFilter.GaussianBlur(radius))
    glow = Image.new("RGBA", canvas.size, (*color, 0))
    glow.putalpha(alpha.point(lambda p: min(255, int(p * strength))))
    return glow.filter(ImageFilter.GaussianBlur(max(1, radius // 3)))


def _radial_bg(w: int, h: int) -> Image.Image:
    sw, sh = max(1, w // 4), max(1, h // 4)
    cx, cy = sw * 0.5, sh * 0.48
    rmax = math.hypot(sw, sh) * 0.62
    img = Image.new("RGB", (sw, sh), BG)
    px = img.load()
    inner = (42, 24, 16)
    mid = (26, 18, 14)
    for y in range(sh):
        dy = (y - cy) / rmax
        for x in range(sw):
            dx = (x - cx) / rmax
            d = math.sqrt(dx * dx + dy * dy)
            if d < 0.22:
                t = d / 0.22
                r = int(_lerp(inner[0], mid[0], t))
                g = int(_lerp(inner[1], mid[1], t))
                b = int(_lerp(inner[2], mid[2], t))
            else:
                t = _clamp((d - 0.22) / 0.78)
                r = int(_lerp(mid[0], BG[0], t))
                g = int(_lerp(mid[1], BG[1], t))
                b = int(_lerp(mid[2], BG[2], t))
            px[x, y] = (r, g, b)
    return img.resize((w, h), Image.Resampling.LANCZOS).convert("RGBA")


def _vignette(w: int, h: int) -> Image.Image:
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    steps = 28
    for i in range(steps):
        t = i / steps
        inset_x = int(w * 0.02 * t)
        inset_y = int(h * 0.03 * t)
        alpha = int(90 * (t**1.6))
        draw.rectangle((inset_x, inset_y, w - 1 - inset_x, h - 1 - inset_y), outline=(0, 0, 0, alpha), width=max(h // 40, 8))
    return layer.filter(ImageFilter.GaussianBlur(18))


def _soft_matte(w: int, h: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    margin_x, margin_y = int(w * 0.06), int(h * 0.08)
    draw.ellipse((margin_x, margin_y, w - margin_x, h - margin_y), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(max(w, h) // 14))


def _paste(base: Image.Image, layer: Image.Image, *, x: int | None = None, y: int | None = None, alpha: float = 1.0) -> None:
    if alpha <= 0.004:
        return
    layer = _mul_alpha(layer, alpha) if alpha < 0.999 else layer
    px = (base.width - layer.width) // 2 if x is None else x
    py = (base.height - layer.height) // 2 if y is None else y
    base.alpha_composite(layer, (px, py))


def _alpha_wipe(im: Image.Image, progress: float, feather: int = 42) -> Image.Image:
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle((0, 0, int(w * _clamp(progress)), h), fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    out = im.copy()
    out.putalpha(ImageChops.multiply(out.split()[-1], mask))
    return out


def _flame_anchor_x(lockup: Image.Image) -> int:
    bbox = lockup.getbbox()
    if not bbox:
        return lockup.width // 8
    return bbox[0] + int((bbox[2] - bbox[0]) * 0.16)


def _crop_lantern(photo: Image.Image) -> Image.Image:
    w, h = photo.size
    box = (int(w * 0.18), int(h * 0.14), int(w * 0.82), int(h * 0.88))
    return photo.convert("RGBA").crop(box)


class LogoMotionService:
    def __init__(self, brand_dir: Path | None = None) -> None:
        self.brand_dir = brand_dir or settings.brand_path
        self.out_dir = self.brand_dir / "motion"

    def storyboard_from_local_model(self) -> tuple[dict, str]:
        prompt = (
            "فقط یک JSON. کلید energy عددی بین 0.85 و 1.2. "
            "لوگو موشن سوزان: فانوس زنده روشن می‌شود، شعله شعله‌ور، بعد قفل Sozan-Core باز می‌شود."
        )
        board = dict(DEFAULT_BOARD)
        note = "استینگ ثابت سوزان"
        try:
            with httpx.Client(timeout=40.0, trust_env=False) as client:
                res = client.post(
                    f"{settings.local_llm_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.local_llm_token}"},
                    json={
                        "model": settings.chat_llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 80,
                        "temperature": 0.3,
                    },
                )
            res.raise_for_status()
            text = res.json()["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                parsed = json.loads(match.group(0))
                if "energy" in parsed:
                    board["energy"] = float(_clamp(float(parsed["energy"]), 0.85, 1.2))
                note = f"شدت از مدل لوکال {settings.chat_llm_model}"
        except Exception:
            note = f"مدل لوکال در دسترس نبود؛ شدت پیش‌فرض ({settings.chat_llm_model})"
        board["duration"] = 6.0
        board["fps"] = 30
        return board, note

    def render(self, board: dict | None = None) -> dict:
        mark = _knockout_dark(Image.open(self.brand_dir / "logo-mark.png"))
        lockup = _knockout_dark(Image.open(self.brand_dir / "logo.png"))
        lantern = _crop_lantern(Image.open(self.brand_dir / "character.png"))
        if board is None:
            board, note = self.storyboard_from_local_model()
        else:
            note = "زمان‌بندی دستی"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "storyboard.json").write_text(
            json.dumps({"board": board, "note": note, "beats": "lantern → flame → lockup"}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        produced: dict[str, str] = {"note": note}
        for name, size in SIZES.items():
            dest = self.out_dir / f"logo-{name}.mp4"
            self._render_size(mark, lockup, lantern, size, board, dest)
            produced[name] = str(dest)
        poster = self.out_dir / "logo-reel-poster.jpg"
        self._poster_from_video(self.out_dir / "logo-reel.mp4", poster)
        produced["poster"] = str(poster)
        campaign = settings.campaigns_path / "logo-motion" / "out"
        campaign.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.out_dir / "logo-reel.mp4", campaign / "ig-reel.mp4")
        shutil.copy(self.out_dir / "logo-feed.mp4", campaign / "ig-feed-motion.mp4")
        shutil.copy(self.out_dir / "logo-wide.mp4", campaign / "tg-video.mp4")
        shutil.copy(poster, campaign / "ig-reel-poster.jpg")
        return produced

    def _poster_from_video(self, video: Path, dest: Path) -> None:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "4.6", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(dest)],
            check=True,
            capture_output=True,
        )

    def _render_size(
        self,
        mark: Image.Image,
        lockup: Image.Image,
        lantern: Image.Image,
        size: tuple[int, int],
        board: dict,
        dest: Path,
    ) -> None:
        w, h = size
        fps = 30
        duration = 6.0
        n = int(duration * fps)
        energy = float(board.get("energy", 1.0))
        bg = _radial_bg(w, h)
        vig = _vignette(w, h)
        mark_f = _fit(mark, int(w * 0.34), int(h * 0.22))
        lock_f = _fit(lockup, int(w * 0.84), int(h * 0.16 if h > w else 0.20))
        lantern_f = _fit(lantern, int(w * 0.72), int(h * 0.58))
        matte = _soft_matte(lantern_f.width, lantern_f.height)
        lantern_f = lantern_f.copy()
        lantern_f.putalpha(ImageEnhance.Brightness(matte).enhance(1.0))
        mark_glow = _make_glow(mark_f, max(18, mark_f.width // 10), ACCENT, 1.35)
        lock_glow = _make_glow(lock_f, max(14, lock_f.height // 3), ACCENT, 0.9)
        lantern_glow = _make_glow(lantern_f, 28, ACCENT, 0.55)
        flame_x = _flame_anchor_x(lock_f)
        rng = random.Random(7)
        embers = [
            {
                "x": rng.uniform(0.38, 0.62),
                "y": rng.uniform(0.42, 0.62),
                "s": rng.uniform(1.4, 3.6),
                "sp": rng.uniform(0.04, 0.12),
                "ph": rng.uniform(0, math.tau),
                "life": rng.uniform(0.12, 0.9),
            }
            for _ in range(int(36 * energy))
        ]
        bloom = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(bloom)
        br = int(min(w, h) * 0.28)
        cx, cy = w // 2, int(h * 0.46)
        bdraw.ellipse((cx - br, cy - br, cx + br, cy + br), fill=(*ACCENT, 70))
        bloom = bloom.filter(ImageFilter.GaussianBlur(br // 2))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i in range(n):
                t = i / max(n - 1, 1)
                frame = bg.copy()
                flicker = 0.86 + 0.14 * math.sin(t * 17 * energy) + 0.06 * math.sin(t * 41)
                spark = _smooth(t, 0.02, 0.12) * (1 - _smooth(t, 0.55, 0.95))
                _paste(frame, bloom, alpha=0.18 + 0.55 * spark * flicker * energy)

                lantern_a = _smooth(t, 0.03, 0.12) * (1 - _smooth(t, 0.18, 0.28))
                if lantern_a > 0.01:
                    zoom = _lerp(1.04, 1.16, _smooth(t, 0.04, 0.40))
                    lw = max(1, int(lantern_f.width * zoom))
                    lh = max(1, int(lantern_f.height * zoom))
                    floated = lantern_f.resize((lw, lh), Image.Resampling.BILINEAR)
                    gy = int(h * 0.44) - lh // 2 + int(math.sin(t * 5) * 6)
                    _paste(frame, lantern_glow, y=gy - (lantern_glow.height - lh) // 2, alpha=lantern_a * 0.7 * flicker)
                    _paste(frame, floated, y=gy, alpha=lantern_a)

                mark_a = _smooth(t, 0.30, 0.42) * (1 - _smooth(t, 0.46, 0.56))
                if mark_a > 0.01:
                    pop = _ease(_smooth(t, 0.30, 0.44))
                    scale = _lerp(0.62, 1.0, pop) * (1.0 + 0.03 * math.sin(t * 9))
                    mw = max(1, int(mark_f.width * scale))
                    mh = max(1, int(mark_f.height * scale))
                    m = mark_f.resize((mw, mh), Image.Resampling.LANCZOS)
                    g = mark_glow.resize(
                        (max(1, int(mark_glow.width * scale)), max(1, int(mark_glow.height * scale))),
                        Image.Resampling.BILINEAR,
                    )
                    my = int(h * 0.45) - mh // 2
                    _paste(frame, g, y=my - (g.height - mh) // 2, alpha=mark_a * 0.95 * flicker)
                    _paste(frame, m, y=my, alpha=mark_a)

                unfold = _smooth(t, 0.50, 0.70)
                lock_a = _smooth(t, 0.50, 0.60)
                if lock_a > 0.01:
                    piece = _alpha_wipe(lock_f, _lerp(0.30, 1.0, unfold), feather=max(28, lock_f.height))
                    screen_flame = int(_lerp(w / 2, w / 2 - lock_f.width / 2 + flame_x, unfold))
                    lx = int(screen_flame - flame_x)
                    ly = int(h * 0.47) - lock_f.height // 2
                    _paste(
                        frame,
                        lock_glow,
                        x=lx - (lock_glow.width - lock_f.width) // 2,
                        y=ly - (lock_glow.height - lock_f.height) // 2,
                        alpha=lock_a * 0.5 * flicker * unfold,
                    )
                    _paste(frame, piece, x=lx, y=ly, alpha=lock_a)

                self._draw_embers(frame, embers, t, energy, flicker)
                _paste(frame, vig, alpha=0.75)
                frame.convert("RGB").save(tmp_path / f"f{i:04d}.png", optimize=False)

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-framerate",
                    str(fps),
                    "-i",
                    str(tmp_path / "f%04d.png"),
                    "-vf",
                    "eq=contrast=1.07:gamma=0.97:saturation=1.06,unsharp=5:5:0.55:5:5:0.0,format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "17",
                    "-preset",
                    "medium",
                    "-movflags",
                    "+faststart",
                    str(dest),
                ],
                check=True,
                capture_output=True,
            )

    def _draw_embers(self, frame: Image.Image, embers: list[dict], t: float, energy: float, flicker: float) -> None:
        gate = _smooth(t, 0.08, 0.22) * (1 - _smooth(t, 0.78, 0.96))
        if gate <= 0:
            return
        w, h = frame.size
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for e in embers:
            life = (t * 0.9 + e["life"]) % 1.0
            a = gate * (1 - life) * (0.35 + 0.65 * flicker) * energy
            if a < 0.04:
                continue
            x = int((e["x"] + 0.03 * math.sin(t * 6 + e["ph"])) * w)
            y = int((e["y"] - life * e["sp"] - t * 0.08) * h)
            r = max(1, int(e["s"] * (1.2 - life)))
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(*EMBER, int(210 * a)))
        frame.alpha_composite(layer)
