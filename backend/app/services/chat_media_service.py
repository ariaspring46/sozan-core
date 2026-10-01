from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from app.state_store import tenant_dir

MEDIA_MAX = 15 * 1024 * 1024
ORPHAN_SEC = 24 * 3600

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
KIND_MAX = {"image": MEDIA_MAX, "video": MEDIA_MAX, "audio": MEDIA_MAX}
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


def copy_file(path: Path, *, sweep: bool = True) -> dict:
    kind = kind_of("", path.name) or "image"
    return save(path.name, path.read_bytes(), mime_for(path.name, kind), sweep=sweep)


def _referenced_names(root: Path) -> set[str]:
    """Every file name mentioned anywhere in this tenant's state files.

    Receipts live in pay-orders.json, ticket images in support-tickets.json,
    customer media in inbox.json, shop chat in shop-messages.json. A file any of
    them names must never be swept as abandoned.
    """
    names: set[str] = set()
    if not root.is_dir():
        return names
    for path in root.glob("*.json"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for token in text.replace('"', " ").replace(",", " ").split():
            if "." in token:
                names.add(Path(token).name)
    return names


def sweep_abandoned(now: float | None = None) -> int:
    root = media_dir()
    clock = time.time() if now is None else now
    referenced = _referenced_names(root.parent)
    removed = 0
    for path in list(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in referenced:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size > MEDIA_MAX or stat.st_mtime < clock - ORPHAN_SEC:
            path.unlink(missing_ok=True)
            removed += 1
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        if path == root or any(path.iterdir()):
            continue
        path.rmdir()
        removed += 1
    return removed


def save(filename: str, data: bytes, content_type: str, *, sweep: bool = True) -> dict:
    if sweep:
        sweep_abandoned()
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
