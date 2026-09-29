"""یادآوری تمدید اشتراک: ۳ روز و ۱ روز پیش از پایان، یک پیامک خدماتی از درگاه خود سوزان.

پیش‌فرض بی‌اثر است تا env هاب کلید پیامک سوزان را بگذارد (SMS_SOZAN_*). متن پیامک
ثابت است و دادهٔ شخصی در آن نمی‌ماند؛ فقط یک رویداد پایش می‌ماند.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.config import settings
from app.state_store import iter_tenants, read_json, tenant_scope, write_json

log = logging.getLogger("sozan.billing")

REMINDER_MARK = "renewal-reminder.json"
_DAY = 86400


def _sozan_sms_key() -> str:
    # همان کلید پیامک سوزان که در env هاب است؛ نام اختصاصی اگر بود مقدم است.
    dedicated = str(getattr(settings, "sozan_sms_api_key", "") or "").strip()
    return dedicated or str(settings.sms_ir_api_key or "").strip()


def _sozan_sms_template() -> str:
    dedicated = str(getattr(settings, "sozan_sms_template", "") or "").strip()
    return dedicated or str(settings.sms_ir_template_id or "").strip()


def _days_left(paid_until: int) -> int:
    return int((int(paid_until) - int(time.time())) // _DAY)


async def _send_sms(phone: str, text: str) -> bool:
    key = _sozan_sms_key()
    template = _sozan_sms_template()
    if not key or not template:
        return False
    provider = str(settings.sozan_sms_provider or "smsir").strip().lower()
    try:
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            if provider == "kavenegar":
                response = await client.get(
                    "https://api.kavenegar.com/v1/" + key + "/verify/lookup.json",
                    params={"receptor": phone, "token": text, "template": template},
                )
            else:
                response = await client.post(
                    "https://api.sms.ir/v1/send/verify",
                    headers={"x-api-key": key, "Content-Type": "application/json"},
                    # قالب تأییدشدهٔ SMS_IR پارامتری است؛ متن ثابت در همان قالب می‌نشیند.
                    json={
                        "mobile": phone,
                        "templateId": int(template),
                        "parameters": [{"name": "CODE", "value": text[:120]}],
                    },
                )
        return response.status_code < 400
    except Exception as exc:
        log.warning("renewal sms failed: %s", type(exc).__name__)
        return False


async def run_once() -> dict:
    """همهٔ پلن‌های پرداختی را ببین و برای ۳/۱ روز مانده یادآوری بفرست."""
    sent = 0
    checked = 0
    for phone in iter_tenants():
        with tenant_scope(phone):
            row = read_json("plan.json", {})
            if not isinstance(row, dict):
                continue
            paid_until = int(row.get("paidUntil") or 0)
            if not paid_until:
                continue
            checked += 1
            left = _days_left(paid_until)
            if left not in (1, 3):
                continue
            marks = read_json(REMINDER_MARK, {}, shared=True)
            wanted = f"{paid_until}:{left}"
            if str(marks.get(phone) or "") == wanted:
                continue
            ok = await _send_sms(
                phone,
                "اشتراک سوزان تا ۳ روز دیگر تمام می‌شود؛ از بخش ارتقای پلن تمدید کن." if left == 3 else
                "اشتراک سوزان فردا تمام می‌شود؛ از بخش ارتقای پلن تمدید کن.",
            )
            marks = read_json(REMINDER_MARK, {}, shared=True)
            marks[phone] = wanted if ok else f"fail:{wanted}:{int(time.time())}"
            write_json(REMINDER_MARK, marks, shared=True)
            if ok:
                sent += 1
    return {"checked": checked, "sent": sent}


async def loop() -> None:
    """هر ساعت یک بار؛ فقط وقتی کلید پیامک سوزان پیکربندی است."""
    while True:
        try:
            if _sozan_sms_key() and _sozan_sms_template():
                await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("renewal reminder failed")
        await asyncio.sleep(3600)
