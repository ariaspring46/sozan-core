from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEFAULT_ABOUT = """سوزان دستیار فروش برای کسب‌وکار ایرانی است.

سه کار می‌کند:

۱) فروشگاه در چت — حس و کالا را می‌گویی؛ سایت ساخته می‌شود.
۲) استودیو — کپشن و تصویر برای تلگرام و دایرکت اینستاگرام.
۳) صندوق و فروش — پیام مشتری، پرداخت و انبار یک‌جا.
"""


class BrandRepository:
    def __init__(self, brand_dir: Path, fonts_dir: Path) -> None:
        self.brand_dir = brand_dir
        self.fonts_dir = fonts_dir
        self.profile_path = brand_dir / "profile.json"
        self.logo_path = brand_dir / "logo.png"
        self.character_path = brand_dir / "character.png"

    def get(self) -> dict:
        self.brand_dir.mkdir(parents=True, exist_ok=True)
        if not self.profile_path.exists():
            data = {"name": "سوزان", "description": DEFAULT_ABOUT.strip() + "\n"}
            self.save(data)
        else:
            data = json.loads(self.profile_path.read_text(encoding="utf-8"))
            data.setdefault("name", "سوزان")
            data.setdefault("description", "")
        self.ensure_logo()
        data["has_logo"] = self.logo_path.is_file()
        data["has_character"] = self.character_path.is_file()
        return data

    def save(self, data: dict) -> dict:
        self.brand_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": (data.get("name") or "سوزان").strip() or "سوزان",
            "description": data.get("description") or "",
        }
        self.profile_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        payload["has_logo"] = self.logo_path.is_file()
        payload["has_character"] = self.character_path.is_file()
        return payload

    def save_image(self, dest: Path, raw: bytes) -> Path:
        self.brand_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        img = Image.open(dest).convert("RGBA")
        img.save(dest, "PNG")
        return dest

    def save_logo(self, raw: bytes) -> Path:
        return self.save_image(self.logo_path, raw)

    def save_character(self, raw: bytes) -> Path:
        return self.save_image(self.character_path, raw)

    def ensure_logo(self) -> Path:
        if self.logo_path.is_file():
            return self.logo_path
        from app.config import settings

        packaged = settings.brand_path / "logo.png"
        if packaged.is_file():
            self.brand_dir.mkdir(parents=True, exist_ok=True)
            self.logo_path.write_bytes(packaged.read_bytes())
            return self.logo_path
        font_path = self.fonts_dir / "Vazirmatn-Bold.ttf"
        font = ImageFont.truetype(str(font_path), 96)
        probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        bbox = draw.textbbox((0, 0), "سوزان", font=font, direction="rtl", language="fa")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = 28
        canvas = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((0, 0, canvas.width - 1, canvas.height - 1), radius=20, fill=(28, 25, 22, 230))
        draw.text(
            (canvas.width - pad, pad - bbox[1]),
            "سوزان",
            font=font,
            fill=(196, 92, 38, 255),
            anchor="rt",
            direction="rtl",
            language="fa",
        )
        canvas.save(self.logo_path, "PNG")
        return self.logo_path
