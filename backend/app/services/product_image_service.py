from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from app.services import chat_media_service, storefront_service

MAX_BYTES = 8_000_000
MAX_SIDE = 1600


def store(data: bytes, content_type: str, filename: str) -> str:
    if not data:
        raise ValueError("فایل خالی است")
    if len(data) > MAX_BYTES:
        raise ValueError("فایل بزرگ‌تر از حد مجاز است")
    kind = chat_media_service.kind_of(content_type, filename)
    if kind != "image":
        raise ValueError("فقط تصویر کالا قابل آپلود است")
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError("این فایل تصویر معتبر نیست") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode in {"RGBA", "LA", "P"}:
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size
    longest = max(width, height)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / float(longest)
        img = img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    from app.services.channel_scan_service import _scan_dir

    name = f"{uuid4().hex}.jpg"
    dest = _scan_dir() / name
    img.save(dest, "JPEG", quality=88, optimize=True)
    return name


def remove_if_unreferenced(name: str) -> bool:
    from app.services.channel_scan_service import _scan_dir

    safe = Path(str(name or "")).name
    if not safe:
        return False
    if safe in storefront_service.referenced_image_names():
        return False
    path = _scan_dir() / safe
    if not path.is_file():
        return False
    path.unlink()
    return True
