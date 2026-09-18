"""لوگو موشن داستان‌محور سوزان — «آذر از آینده آمده».

حدود ۵ ثانیه، ۳۰ فریم‌برثانیه. رندر فریم‌به‌فریم با Pillow، انکد با ffmpeg.
کاملاً مستقل — هیچ وابستگی به پروژهٔ سوزان ندارد.

داستان (زمان‌بندی نرمال‌شده ۰ تا ۱):
  0.00–0.14  «آینده»    نقطهٔ نور در تاریکی پیدا می‌شود؛ موج‌های حلقه‌ای زمان
  0.14–0.38  «سفر»      نور شعله‌ور می‌شود؛ آذر از نور کوچک و درخشان فرومی‌آید و فرود می‌آید
  0.38–0.58  «فرود»      آذر می‌نشیند؛ حلقهٔ فرود پخش می‌شود؛ جرقه‌ها می‌پاشند
  0.58–0.76  «بیداری»    نفس‌کشیدن آرام؛ درخشش مسی جان می‌گیرد
  0.76–1.00  «سوزان»     وردمارک «سوزان» می‌آید؛ قفل نهایی
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import settings

BOARD = {
    "duration": 5.0,
    "fps": 30,
    "story": "آذر از آینده آمده: نور → سفر → فرود → بیداری → سوزان",
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
LIGHT = (255, 224, 180)

RTL = {"direction": "rtl", "language": "fa"}


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
    out = im.copy()
    a = out.split()[-1].point(lambda p: int(p * _clamp(alpha)))
    out.putalpha(a)
    return out


def _paste(base: Image.Image, layer: Image.Image, *, x: int | None = None, y: int | None = None, alpha: float = 1.0) -> None:
    if alpha <= 0.004:
        return
    layer = _mul_alpha(layer, alpha) if alpha < 0.999 else layer
    px = (base.width - layer.width) // 2 if x is None else x
    py = (base.height - layer.height) // 2 if y is None else y
    base.alpha_composite(layer, (px, py))


def _knockout_light(im: Image.Image, bg_ref: tuple[int, int, int] = (251, 249, 238)) -> Image.Image:
    """پس‌زمینهٔ کرم/روشن را شفاف می‌کند (برعکس knockout_dark سرویس قبلی)."""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    br, bg_, bb = bg_ref
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            dist = max(abs(r - br), abs(g - bg_), abs(b - bb))
            if dist < 14:
                px[x, y] = (r, g, b, 0)
            elif dist < 46:
                px[x, y] = (r, g, b, int(a * ((dist - 14) / 32)))
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
    cx, cy = sw * 0.5, sh * 0.42
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


def _wordmark(w: int, fonts_dir: Path) -> Image.Image:
    """«سوزان» با Vazirmatn-Bold در رنگ مسی — قفل نهایی."""
    font = ImageFont.truetype(str(fonts_dir / "Vazirmatn-Bold.ttf"), max(64, int(w * 0.085)))
    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), "سوزان", font=font, **RTL)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = int(w * 0.06)
    canvas = Image.new("RGBA", (tw + pad * 2, th + pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((canvas.width - pad, pad - bbox[1]), "سوزان", font=font, fill=ACCENT, anchor="rt", **RTL)
    return canvas


def _draw_rings(
    frame: Image.Image,
    *,
    cx: float,
    cy: float,
    t: float,
    gate: float,
    r_max: float,
    count: int = 3,
    color: tuple[int, int, int],
    width: int,
    squash: float = 1.0,
) -> None:
    """حلقه‌های موجی (زمان/فرود) از نقطهٔ (cx, cy) پخش می‌شوند."""
    if gate <= 0.004:
        return
    w, h = frame.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i in range(count):
        phase = (t * 1.6 + i / count) % 1.0
        r = phase * r_max
        alpha = int(180 * gate * (1 - phase))
        if alpha < 6 or r < 2:
            continue
        ry = max(2, r * squash)
        draw.ellipse((cx - r, cy - ry, cx + r, cy + ry), outline=(*color, alpha), width=width)
    frame.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2)))


def _draw_light(frame: Image.Image, cx: int, cy: int, radius: int, alpha: float) -> None:
    if alpha <= 0.01 or radius < 1:
        return
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*LIGHT, int(255 * alpha)))
    halo = radius * 3
    draw.ellipse((cx - halo, cy - halo, cx + halo, cy + halo), fill=(*SOFT, int(70 * alpha)))
    frame.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(2, radius // 2 + 6))))


def _draw_embers(frame: Image.Image, embers: list[dict], t: float, gate: float, flicker: float) -> None:
    if gate <= 0:
        return
    w, h = frame.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for e in embers:
        life = (t * e["speed"] + e["seed"]) % 1.0
        a = gate * (1 - life) * (0.35 + 0.65 * flicker)
        if a < 0.04:
            continue
        x = int((e["x"] + e["sway"] * math.sin(t * e["sway_hz"] + e["ph"])) * w)
        y = int((e["y"] - life * e["rise"]) * h)
        r = max(1, int(e["s"] * (1.2 - life)))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*EMBER, int(210 * a)))
    frame.alpha_composite(layer)


def _transform_sprite(base: Image.Image, sx: float, sy: float, angle: float) -> Image.Image:
    """کشسانی/فشردگی + چرخش اسپرایت — حرکت کارتونی خود موجود."""
    w = max(1, int(base.width * sx))
    h = max(1, int(base.height * sy))
    im = base.resize((w, h), Image.Resampling.BILINEAR)
    if abs(angle) > 0.15:
        im = im.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(0, 0, 0, 0))
    return im


def _hop(t: float, t0: float, dur: float, height: float) -> tuple[float, float]:
    """پرش کوچک: (ارتفاع، ضریب کشسانی). کشیده می‌شود وسط پرواز، فشرده موقع فرود."""
    if t < t0 or t > t0 + dur:
        return 0.0, 1.0
    p = (t - t0) / dur
    arc = math.sin(math.pi * p)
    return height * arc, 1.0 + 0.06 * arc


def _draw_ember_pulse(frame: Image.Image, cx: int, cy: int, radius: int, alpha: float) -> None:
    """تپش جرقهٔ سینه — موجود زنده است."""
    if alpha <= 0.01 or radius < 2:
        return
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*EMBER, int(120 * alpha)))
    frame.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius // 2 + 4)))


class AzarMotionService:
    def __init__(self, brand_dir: Path | None = None, character: Path | None = None) -> None:
        self.brand_dir = brand_dir or settings.brand_path
        self.character = character or (self.brand_dir / "azar-seed128.png")
        self.out_dir = self.brand_dir / "motion"

    def render(self) -> dict:
        sprite = _knockout_light(Image.open(self.character))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "storyboard.json").write_text(
            json.dumps(
                {
                    "board": BOARD,
                    "character": self.character.name,
                    "beats": [
                        {"t": "0.00-0.14", "name": "آینده", "desc": "نقطهٔ نور می‌آید؛ حلقه‌های زمان"},
                        {"t": "0.14-0.38", "name": "سفر", "desc": "آذر از نور فرومی‌آید؛ می‌غلتد و پایین می‌آید"},
                        {"t": "0.38-0.58", "name": "فرود", "desc": "نشستن با فشردگی؛ حلقهٔ فرود؛ پاشش جرقه"},
                        {"t": "0.58-0.76", "name": "بیداری", "desc": "نفس‌کشیدن، تاب بدن، تپش جرقهٔ سینه، پرش کوچک"},
                        {"t": "0.76-1.00", "name": "سوزان", "desc": "پرش حال‌آمدن؛ وردمارک می‌آید؛ قفل نهایی"},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        produced: dict[str, str] = {}
        for name, size in SIZES.items():
            dest = self.out_dir / f"azar-{name}.mp4"
            self._render_size(sprite, size, dest)
            produced[name] = str(dest)
        poster = self.out_dir / "azar-poster.jpg"
        self._poster_from_video(self.out_dir / "azar-reel.mp4", poster, at=4.3)
        produced["poster"] = str(poster)
        return produced

    def _poster_from_video(self, video: Path, dest: Path, *, at: float) -> None:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-q:v", "3", str(dest)],
            check=True,
            capture_output=True,
        )

    def _render_size(self, sprite: Image.Image, size: tuple[int, int], dest: Path) -> None:
        w, h = size
        fps = BOARD["fps"]
        duration = BOARD["duration"]
        n = int(duration * fps)
        bg = _radial_bg(w, h)
        vig = _vignette(w, h)
        azar_f = _fit(sprite, int(w * 0.72), int(h * 0.52))
        azar_glow = _make_glow(azar_f, 30, ACCENT, 0.75)
        word_f = _fit(_wordmark(w, settings.fonts_path), int(w * 0.86), int(h * 0.14))
        word_glow = _make_glow(word_f, max(12, word_f.height // 3), ACCENT, 0.85)

        rng = random.Random(11)
        embers = [
            {
                "x": rng.uniform(0.30, 0.70),
                "y": rng.uniform(0.46, 0.78),
                "s": rng.uniform(1.4, 3.8),
                "rise": rng.uniform(0.06, 0.16),
                "speed": rng.uniform(0.5, 1.1),
                "seed": rng.uniform(0.0, 1.0),
                "sway": rng.uniform(0.0, 0.03),
                "sway_hz": rng.uniform(3.0, 7.0),
                "ph": rng.uniform(0, math.tau),
            }
            for _ in range(40)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i in range(n):
                t = i / max(n - 1, 1)
                frame = bg.copy()
                flicker = 0.86 + 0.14 * math.sin(t * 17) + 0.06 * math.sin(t * 41)
                cx = w / 2
                light_cy = h * 0.20

                # ── «آینده» — نقطهٔ نور و حلقه‌های زمان ──
                light_a = _smooth(t, 0.00, 0.06) * (1 - _smooth(t, 0.30, 0.40))
                if light_a > 0.01:
                    light_r = _lerp(4, 26, _ease(_smooth(t, 0.00, 0.22)))
                    _draw_light(frame, int(cx), int(light_cy), int(light_r), light_a)
                    _draw_rings(
                        frame,
                        cx=cx,
                        cy=light_cy,
                        t=t,
                        gate=_smooth(t, 0.02, 0.08) * (1 - _smooth(t, 0.30, 0.42)),
                        r_max=min(w, h) * 0.30,
                        count=3,
                        color=SOFT,
                        width=3,
                    )

                # ── «سفر» — آذر از نور فرومی‌آید، می‌غلتد و فرود می‌آید ──
                travel = _smooth(t, 0.14, 0.38)
                landed = t >= 0.38
                if travel > 0.01 or landed:
                    azar_a = _smooth(t, 0.14, 0.22)
                    scale = _lerp(0.28, 1.0, _ease(travel))
                    ground_y = int(h * 0.72)
                    sx, sy, angle, x_off, hop = 1.0, 1.0, 0.0, 0, 0.0
                    if not landed:
                        # غلت‌خوردن در سفر از آینده
                        angle = _lerp(-20.0, 0.0, _ease(travel)) + 5.0 * math.sin(t * 26) * (1 - travel)
                        x_off = int(26 * math.sin(t * 9) * (1 - travel))
                    else:
                        # فشردگی لحظهٔ فرود (squash)
                        pulse = (1 - _smooth(t, 0.38, 0.46)) * _smooth(t, 0.372, 0.39)
                        sy = 1.0 - 0.085 * pulse
                        sx = 1.0 + 0.075 * pulse
                        # نفس‌کشیدن — لنگر در پا (~1.2 بار در ثانیه)
                        br = math.sin(t * math.tau * 1.2 * duration)
                        sy *= 1.0 - 0.016 * br
                        sx *= 1.0 + 0.011 * br
                        # تاب آرام بدن (~0.6 بار در ثانیه)
                        angle = 1.3 * math.sin(t * math.tau * 0.6 * duration)
                        # پرش شیفت‌بازی بعد از فرود
                        hop, st = _hop(t, 0.55, 0.09, int(h * 0.016))
                        sy *= st
                        sx *= 1.0 / st
                        # پرش حال‌آمدن وقتی وردمارک می‌آید
                        hop2, st2 = _hop(t, 0.76, 0.08, int(h * 0.011))
                        hop += hop2
                        sy *= st2
                        sx *= 1.0 / st2

                    aw = max(1, int(azar_f.width * scale))
                    ah = max(1, int(azar_f.height * scale))
                    azar_img = _transform_sprite(azar_f, scale * sx, scale * sy, angle)
                    glow_img = _transform_sprite(azar_glow, scale * sx, scale * sy, angle)
                    y_from = int(light_cy - ah * 0.5)
                    y_to = ground_y - azar_img.height
                    ay = int(_lerp(y_from, y_to, _ease_in_out(travel)))
                    if landed:
                        ay = y_to - int(hop)
                    ax = int(cx - azar_img.width / 2) + x_off
                    gy = ay - (glow_img.height - azar_img.height) // 2
                    _paste(frame, glow_img, x=ax + (azar_img.width - glow_img.width) // 2, y=gy, alpha=azar_a * (0.5 + 0.3 * flicker))
                    _paste(frame, azar_img, x=ax, y=ay, alpha=azar_a)
                    sprite_cx = ax + azar_img.width // 2
                    sprite_cy = ay + int(azar_img.height * 0.58)
                    if landed:
                        # تپش جرقهٔ سینه (~0.8 بار در ثانیه)
                        pulse_a = (0.45 + 0.55 * max(0.0, math.sin(t * math.tau * 0.8 * duration))) ** 2
                        _draw_ember_pulse(frame, sprite_cx, sprite_cy, max(4, int(azar_img.width * 0.085)), pulse_a * azar_a)

                # ── «فرود» — حلقهٔ فرود و پاشش جرقه ──
                landing_gate = _smooth(t, 0.38, 0.42) * (1 - _smooth(t, 0.52, 0.62))
                if landing_gate > 0.01:
                    _draw_rings(
                        frame,
                        cx=cx,
                        cy=h * 0.725,
                        t=t * 2.2,
                        gate=landing_gate,
                        r_max=w * 0.44,
                        count=2,
                        color=ACCENT,
                        width=6,
                        squash=0.22,
                    )

                # ── جرقه‌ها: سفر (بالارونده) بعد از فرود (پاشش آرام) ──
                ember_gate = _smooth(t, 0.16, 0.24) * (1 - _smooth(t, 0.90, 0.99))
                if landed:
                    ember_gate = max(ember_gate, _smooth(t, 0.38, 0.44) * (1 - _smooth(t, 0.86, 0.97)))
                _draw_embers(frame, embers, t, ember_gate, flicker)

                # ── «بیداری» — نفس درخشان پشت آذر (~0.9 بار در ثانیه) ──
                if landed:
                    breath = 0.35 + 0.25 * math.sin(t * math.tau * 0.9 * duration)
                    bloom = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    bdraw = ImageDraw.Draw(bloom)
                    br = int(min(w, h) * 0.20)
                    bcy = int(h * 0.72) - azar_f.height // 2
                    bdraw.ellipse((cx - br, bcy - br, cx + br, bcy + br), fill=(*ACCENT, int(60 * breath * flicker)))
                    frame.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(br // 2)))

                # ── «سوزان» — وردمارک ──
                word_a = _smooth(t, 0.74, 0.84)
                if word_a > 0.01:
                    slide = _lerp(26, 0, _ease(_smooth(t, 0.74, 0.86)))
                    wx = int(cx - word_f.width / 2)
                    wy = int(h * 0.78) + int(slide)
                    _paste(frame, word_glow, x=wx - (word_glow.width - word_f.width) // 2, y=wy - (word_glow.height - word_f.height) // 2, alpha=word_a * 0.6 * flicker)
                    _paste(frame, word_f, x=wx, y=wy, alpha=word_a)

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