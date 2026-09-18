from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from app.state_store import tenant_dir

IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}
AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}

KIND_TYPES = {"image": IMAGE_TYPES, "video": VIDEO_TYPES, "audio": AUDIO_TYPES}
KIND_MAX = {"image": 8_000_000, "video": 24_000_000, "audio": 8_000_000}
CAPTION = {
    "image": "یک تصویر فرستادم.",
    "video": "یک ویدیو فرستادم.",
    "audio": "یک پیام صوتی فرستادم.",
}


def media_dir() -> Path:
    path = tenant_dir() / "chat-media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def kind_of(content_type: str, filename: str) -> str | None:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in IMAGE_TYPES:
        return "image"
    if mime in VIDEO_TYPES:
        return "video"
    if mime in AUDIO_TYPES:
        return "audio"
    suffix = Path(filename or "").suffix.lower()
    for kind, mapping in KIND_TYPES.items():
        if suffix in mapping.values():
            return kind
    return None


def mime_for(filename: str, kind: str = "") -> str:
    suffix = Path(filename).suffix.lower()
    for mapping in KIND_TYPES.values():
        for mime, ext in mapping.items():
            if ext == suffix:
                return mime
    if kind == "video":
        return "video/mp4"
    if kind == "audio":
        return "audio/webm"
    return "image/png"


def copy_file(path: Path) -> dict:
    kind = kind_of("", path.name) or "image"
    return save(path.name, path.read_bytes(), mime_for(path.name, kind))


def save(filename: str, data: bytes, content_type: str) -> dict:
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "فایل خالی است.")
    kind = kind_of(content_type, filename)
    if not kind:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "فقط تصویر، ویدیو یا صدا.")
    if len(data) > KIND_MAX[kind]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "فایل بزرگ‌تر از حد مجاز است.")
    mime = (content_type or "").split(";")[0].strip().lower()
    ext = KIND_TYPES[kind].get(mime) or Path(filename).suffix.lower()
    if ext not in KIND_TYPES[kind].values():
        ext = next(iter(KIND_TYPES[kind].values()))
    name = f"{uuid4().hex}-{kind}{ext}"
    dest = media_dir() / name
    dest.write_bytes(data)
    return {"kind": kind, "name": name, "mime": mime or f"{kind}/*"}


def resolve(name: str) -> Path:
    safe = Path(name).name
    if safe != name or not safe:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام نامعتبر است")
    root = media_dir().resolve()
    path = (root / safe).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "فایل نیست")
    return path


def caption(kind: str) -> str:
    return CAPTION.get(kind, "یک فایل فرستادم.")


def spoken_text(text: str, media: dict | None) -> str:
    raw = (text or "").strip()
    if not media:
        return raw
    note = caption(str(media.get("kind") or ""))
    return f"{raw}\n({note})".strip() if raw else note
