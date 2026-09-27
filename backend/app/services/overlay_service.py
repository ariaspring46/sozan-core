from __future__ import annotations

from dataclasses import dataclass
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
BAR = (18, 16, 14)


@dataclass
class CaptionPlace:
    box: tuple[int, int, int, int]
    bar: int = 0


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def subject_box(img: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of pixels that are not the corner background."""
    rgb = img.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    corners = (
        pixels[2, 2],
        pixels[width - 3, 2],
        pixels[2, height - 3],
        pixels[width - 3, height - 3],
    )
    bg = tuple(sum(pixel[channel] for pixel in corners) // 4 for channel in range(3))
    step = max(1, min(width, height) // 180)
    min_x, min_y, max_x, max_y = width, height, 0, 0
    found = False
    for y in range(0, height, step):
        for x in range(0, width, step):
            pixel = pixels[x, y]
            if max(abs(pixel[channel] - bg[channel]) for channel in range(3)) > 28:
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return (int(width * 0.25), int(height * 0.25), int(width * 0.75), int(height * 0.75))
    pad = int(min(width, height) * 0.02)
    return (
        max(0, min_x - pad),
        max(0, min_y - pad),
        min(width, max_x + step + pad),
        min(height, max_y + step + pad),
    )


def _block_height(draw, *, title, subtitle, cta, title_font, sub_font, cta_font, max_w, wrap) -> int:
    height = 0
    if title:
        lines = wrap(draw, title, title_font, max_w) or [title]
        height += len(lines) * (title_font.size + 10)
    if subtitle:
        lines = wrap(draw, subtitle, sub_font, max_w) or [subtitle]
        height += 8 + len(lines) * (sub_font.size + 8)
    if cta:
        height += 18 + cta_font.size + 28
    return height


def place_caption(
    width: int,
    height: int,
    subject: tuple[int, int, int, int],
    block_h: int,
    margin: int,
) -> CaptionPlace:
    """Put the caption in empty space. If it would touch the subject, use a bottom bar."""
    gap = 16
    need = block_h + gap
    bands: list[tuple[int, int]] = []
    if subject[1] - margin >= need:
        bands.append((subject[1] - margin, margin))
    below = height - subject[3] - margin
    if below >= need:
        y = subject[3] + gap
        if y + block_h > height - margin:
            y = height - margin - block_h
        bands.append((below, y))
    bands.sort(key=lambda item: item[0], reverse=True)
    for _room, y in bands:
        box = (margin, y, width - margin, y + block_h)
        if not _overlap(box, subject):
            return CaptionPlace(box)
    bar = max(block_h + 28, int(height * 0.16))
    bar = min(bar, int(height * 0.28))
    return CaptionPlace((margin, height - bar + 12, width - margin, height - 12), bar=bar)


def _shade_limits(box: tuple[int, int, int, int], subject: tuple[int, int, int, int]) -> tuple[int, int]:
    top = box[1] - 8
    bottom = box[3] + 8
    if box[3] <= subject[1]:
        bottom = min(bottom, subject[1])
    elif box[1] >= subject[3]:
        top = max(top, subject[3])
    return top, bottom


def _cover_image(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - tw) // 2
    top = (resized.height - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _photo_above_bar(photo: Image.Image, bar: int) -> Image.Image:
    width, height = photo.size
    photo_h = max(1, height - bar)
    fitted = _cover_image(photo, (width, photo_h))
    canvas = Image.new("RGB", (width, height), BAR)
    canvas.paste(fitted, (0, 0))
    return canvas


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

    def _shade_band(self, base: Image.Image, top: int, bottom: int) -> None:
        """A short, light shade only behind the caption, never across the product."""
        top = max(0, top)
        bottom = min(base.height, bottom)
        if bottom - top < 2:
            return
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        span = bottom - top
        for index, y in enumerate(range(top, bottom)):
            peak = 1 - abs((index / max(span - 1, 1)) * 2 - 1)
            alpha = int(88 * peak)
            draw.line([(0, y), (base.width, y)], fill=(18, 16, 14, alpha))
        base.alpha_composite(overlay)

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
        covered = self._cover(src, size)
        w, h = covered.size
        margin = int(w * 0.08 if format_name != "story" else w * 0.10)
        max_w = w - margin * 2
        title_size = 64 if format_name == "feed" else (56 if format_name == "wide" else 72)
        title_font = self._font(True, title_size)
        sub_font = self._font(False, 32 if format_name != "story" else 34)
        cta_font = self._font(True, 28)
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        block_h = _block_height(
            probe,
            title=title,
            subtitle=subtitle,
            cta=cta,
            title_font=title_font,
            sub_font=sub_font,
            cta_font=cta_font,
            max_w=max_w,
            wrap=self._wrap,
        )
        product = subject_box(covered)
        placed = place_caption(w, h, product, block_h, margin)
        if placed.bar:
            img = _photo_above_bar(covered, placed.bar).convert("RGBA")
        else:
            img = covered.convert("RGBA")
            shade_top, shade_bottom = _shade_limits(placed.box, product)
            self._shade_band(img, shade_top, shade_bottom)
        draw = ImageDraw.Draw(img)

        if logo_path and logo_path.is_file():
            logo_box = self._logo_box(img.size, logo_path, margin=margin, format_name=format_name)
            logo_clear = product[1] > int(h * 0.16) if placed.bar else not _overlap(logo_box, product)
            if logo_clear:
                self._paste_logo(img, logo_path, margin=margin, format_name=format_name)

        y = placed.box[1]
        if title:
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

    def _logo_size(self, logo_path: Path, *, format_name: str) -> tuple[int, int]:
        logo = Image.open(logo_path)
        target_h = 88 if format_name == "story" else (72 if format_name == "feed" else 64)
        scale = target_h / max(logo.height, 1)
        return max(1, int(logo.width * scale)), target_h

    def _logo_box(self, size: tuple[int, int], logo_path: Path, *, margin: int, format_name: str) -> tuple[int, int, int, int]:
        width, _height = size
        logo_w, logo_h = self._logo_size(logo_path, format_name=format_name)
        x = width - margin - logo_w
        y = int(size[1] * 0.045)
        return (x, y, x + logo_w, y + logo_h)

    def _paste_logo(self, base: Image.Image, logo_path: Path, *, margin: int, format_name: str) -> None:
        logo = Image.open(logo_path).convert("RGBA")
        logo_w, logo_h = self._logo_size(logo_path, format_name=format_name)
        logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        x = base.width - margin - logo.width
        y = int(base.height * 0.045)
        base.alpha_composite(logo, (x, y))
