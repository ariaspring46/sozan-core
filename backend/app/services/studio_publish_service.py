from __future__ import annotations

from pathlib import Path

from app.services import (
    channel_service,
    chat_media_service,
    instagram_service,
    public_media_service,
    studio_chat_service,
    telegram_service,
    unipile_service,
    whatsapp_service,
)
from app.services.observe_client import emit_later

PLATFORMS = {"telegram", "instagram", "whatsapp"}
KIND_TTL = {"image": 3600, "video": 7200}
CAPTION_LIMITS = {"instagram": 2200, "telegram": 1024, "whatsapp": 1024}
LABELS = {"instagram": "اینستاگرام", "telegram": "تلگرام", "whatsapp": "واتساپ"}


def _row(platform: str) -> dict:
    row = channel_service.account_for_platform(platform)
    if row is None or not channel_service.is_connected(row):
        raise ValueError("این کانال وصل نیست. از بیشتر → کانال‌ها حساب را ثبت کن.")
    return row


def _path(name: str) -> Path:
    return chat_media_service.resolve(name)


def _persian_provider_error(exc: BaseException) -> str:
    text = str(exc)[:200]
    if isinstance(exc, ValueError):
        return str(exc)
    return "ارسال به کانال نشد. اتصال را در کانال‌ها بررسی کن."


async def publish(
    *,
    platform: str,
    caption: str,
    media_name: str,
    media_kind: str,
    message_id: str = "",
    campaign_id: str = "",
    force: bool = False,
) -> dict:
    key = platform.strip().lower()
    if key not in PLATFORMS:
        raise ValueError("ارسال استودیو فقط برای اینستاگرام، تلگرام و واتساپ است.")
    kind = media_kind.strip().lower()
    if kind not in {"image", "video"}:
        raise ValueError("فقط تصویر یا ویدیو را می‌توان فرستاد.")
    if not str(media_name or "").strip():
        raise ValueError("فایل ارسال نیست.")
    if message_id.strip() and not force and studio_chat_service.recently_published(message_id.strip(), key):
        extra = {"messages": studio_chat_service.snapshot()["messages"]}
        return {"ok": True, "skipped": True, "platform": key, "message": "به‌تازگی ارسال شده؛ برای ارسال دوباره تأیید کن", **extra}
    path = _path(media_name)
    text = (caption or "").strip()[: CAPTION_LIMITS[key]]
    row = _row(key)
    try:
        if key == "telegram":
            target = channel_service.post_target_for(row)
            if not target:
                raise ValueError("مقصد پست تلگرام نیست. بات را ادمین کانال کن و آیدی کانال را بگذار.")
            token = channel_service.token_for(row)
            if kind == "video":
                await telegram_service.send_video(token=token, chat_id=target, path=path, caption=text)
            else:
                await telegram_service.send_photo(token=token, chat_id=target, path=path, caption=text)
        elif key == "instagram":
            unipile_id = channel_service.unipile_account_id(row)
            if unipile_id:
                await unipile_service.publish_media(account_id=unipile_id, path=path, caption=text, kind=kind)
            else:
                url = public_media_service.public_url(name=path.name, ttl=KIND_TTL[kind])
                token = channel_service.token_for(row)
                if kind == "video":
                    await instagram_service.publish_reel(token=token, video_url=url, caption=text)
                else:
                    await instagram_service.publish_image(token=token, image_url=url, caption=text)
        else:
            creds = channel_service.credentials_for(row)
            target = channel_service.post_target_for(row)
            if not target:
                raise ValueError("شماره مقصد واتساپ نیست. در کانال‌ها مقصد ارسال را بگذار.")
            await whatsapp_service.send_media(
                token=channel_service.token_for(row),
                phone_number_id=str(creds.get("phoneNumberId") or ""),
                to=target,
                path=path,
                caption=text,
            )
    except ValueError:
        emit_later(
            kind="publish",
            surface="studio",
            title="publish-failed",
            status="failed",
            turn_id=message_id,
            operation_id=campaign_id,
            payload={"platform": key, "kind": kind, "error": "validation"},
        )
        raise
    except Exception as exc:
        emit_later(
            kind="publish",
            surface="studio",
            title="publish-failed",
            status="failed",
            turn_id=message_id,
            operation_id=campaign_id,
            payload={"platform": key, "kind": kind, "error": type(exc).__name__, "errorClass": type(exc).__name__},
        )
        raise ValueError(_persian_provider_error(exc)) from exc
    extra: dict = {}
    if message_id.strip():
        extra = studio_chat_service.mark_published(message_id.strip(), key)
    emit_later(
        kind="publish",
        surface="studio",
        title="publish-ok",
        status="ready",
        turn_id=message_id,
        operation_id=campaign_id,
        payload={"platform": key, "kind": kind},
    )
    return {"ok": True, "platform": key, "message": f"به {LABELS[key]} ارسال شد.", **extra}
