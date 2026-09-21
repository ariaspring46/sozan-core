from __future__ import annotations

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.services import chat_media_service


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    viewPath: str = Field(default="", max_length=200)
    viewTarget: str = Field(default="", max_length=80)


def _upload(value: object) -> UploadFile | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, UploadFile) and value.filename:
        return value
    return None


async def read_chat_payload(request: Request) -> tuple[str, dict | None, str, str, str, str, str]:
    ctype = request.headers.get("content-type") or ""
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        text = str(form.get("text") or "").strip()
        view_path = str(form.get("viewPath") or "").strip()[:200]
        view_target = str(form.get("viewTarget") or "").strip()[:80]
        confirm_id = str(form.get("confirmId") or "").strip()[:80]
        cancel_id = str(form.get("cancelId") or "").strip()[:80]
        upload = _upload(form.get("file"))
        media = None
        if upload is not None:
            data = await upload.read()
            media = chat_media_service.save(upload.filename, data, upload.content_type or "")
        if not text and not media and not confirm_id and not cancel_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "متن یا فایل لازم است.")
        if len(text) > 4000:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "متن خیلی بلند است.")
        thread_id = str(form.get("threadId") or "").strip()[:32]
        return text, media, view_path, view_target, confirm_id, cancel_id, thread_id
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "بدنه نامعتبر است.") from exc
    body = ChatIn.model_validate(payload)
    thread_id = str(payload.get("threadId") or "").strip()[:32] if isinstance(payload, dict) else ""
    return body.text.strip(), None, body.viewPath.strip(), body.viewTarget.strip(), "", "", thread_id
