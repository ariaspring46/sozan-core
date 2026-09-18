from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZES = {
    "feed": (1080, 1080),
    "story": (1080, 1920),
    "wide": (1920, 1080),
}

BG = (18, 16, 14)
INK = (244, 239, 230)
MUTED = (196, 184, 168)
ACCENT = (196, 92, 38)


RTL = {"direction": "rtl", "language": "fa"}


class OverlayService:
    def __init__(self, fonts_dir: Path) -> None:
        self.fonts_dir = fonts_dir
        self.regular = fonts_dir / "Vazirmatn-Regular.ttf"
        self.bold = fonts_dir / "Vazirmatn-Bold.ttf"

    def _font(self, bold: bool, size: int) -> ImageFont.FreeTypeFont:
        path = self.bold if bold else self.regular
        return ImageFont.truetype(str(path), size=size)

    def _cover(self, src: Path, size: tuple[int, int]) -> Image.Image:
        img = Image.open(src).convert("RGB")
        tw, th = size
        scale = max(tw / img.width, th / img.height)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
        left = (img.width - tw) // 2
        top = (img.height - th) // 2
        return img.crop((left, top, left + tw, top + th))

    def _gradient(self, base: Image.Image) -> Image.Image:
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        h = base.height
        band = int(h * 0.48)
        for y in range(band):
            alpha = int(210 * (y / band))
            draw.line([(0, h - band + y), (base.width, h - band + y)], fill=(18, 16, 14, alpha))
        out = base.convert("RGBA")
        out.alpha_composite(overlay)
        return out.convert("RGB")

    def _wrap(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
        words = text.split()
        if not words:
            return []
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = current + " " + word
            if draw.textlength(trial, font=font, direction="rtl", language="fa") <= max_w:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines[:3]

    def render(
        self,
        src: Path,
        dest: Path,
        *,
        title: str,
        subtitle: str,
        cta: str,
        format_name: str,
        wordmark: str = "سوزان",
        logo_path: Path | None = None,
    ) -> Path:
        size = SIZES[format_name]
        img = self._gradient(self._cover(src, size)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        margin = int(w * 0.08 if format_name != "story" else w * 0.10)
        max_w = w - margin * 2

        if logo_path and logo_path.is_file():
            self._paste_logo(img, logo_path, margin=margin, format_name=format_name)
        else:
            mark_font = self._font(True, 36 if format_name != "wide" else 32)
            draw.text((w - margin, int(h * 0.06)), wordmark, font=mark_font, fill=ACCENT, anchor="rt", **RTL)

        title_size = 64 if format_name == "feed" else (56 if format_name == "wide" else 72)
        title_font = self._font(True, title_size)
        sub_font = self._font(False, 32 if format_name != "story" else 34)
        cta_font = self._font(True, 28)

        y = int(h * 0.68) if format_name != "wide" else int(h * 0.58)
        for line in self._wrap(draw, title, title_font, max_w):
            draw.text((w - margin, y), line, font=title_font, fill=INK, anchor="rt", **RTL)
            y += title_font.size + 10
        if subtitle:
            y += 8
            for line in self._wrap(draw, subtitle, sub_font, max_w):
                draw.text((w - margin, y), line, font=sub_font, fill=MUTED, anchor="rt", **RTL)
                y += sub_font.size + 8
        if cta:
            y += 18
            pad_x, pad_y = 28, 14
            label = cta
            tw = draw.textlength(label, font=cta_font, direction="rtl", language="fa")
            box = [w - margin - tw - pad_x * 2, y, w - margin, y + cta_font.size + pad_y * 2]
            draw.rounded_rectangle(box, radius=12, fill=ACCENT)
            draw.text(
                (w - margin - pad_x, y + pad_y),
                label,
                font=cta_font,
                fill=INK,
                anchor="rt",
                **RTL,
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(dest, "PNG")
        return dest

    def _paste_logo(self, base: Image.Image, logo_path: Path, *, margin: int, format_name: str) -> None:
        logo = Image.open(logo_path).convert("RGBA")
        target_h = 88 if format_name == "story" else (72 if format_name == "feed" else 64)
        scale = target_h / max(logo.height, 1)
        logo = logo.resize((max(1, int(logo.width * scale)), target_h), Image.Resampling.LANCZOS)
        x = base.width - margin - logo.width
        y = int(base.height * 0.045)
        base.alpha_composite(logo, (x, y))
