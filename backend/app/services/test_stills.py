from pathlib import Path

from PIL import Image, ImageDraw


def write_still(path: Path, size: tuple[int, int], tone: tuple[int, int, int]) -> None:
    img = Image.new("RGB", size, tone)
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.ellipse((w * 0.2, h * 0.25, w * 0.8, h * 0.7), outline=(196, 92, 38), width=6)
    draw.rectangle((0, int(h * 0.82), w, h), fill=(18, 16, 14))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
