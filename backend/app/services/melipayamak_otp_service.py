"""Login OTP through the Melipayamak pattern web service (SendByBaseNumber2).

We build the 6-digit code ourselves and send it as {0} of the approved
template (bodyId from env, default 547036). The ApiKey of the old panel goes
in the password field per rule -110. Every failure keeps a generic message for
the user; the provider's return code lands in the observe event, never with
the phone or the code.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.sms")

TIMEOUT = 12.0

# نگاشت کدهای برگشتی payamak-panel به کلاس خطا (شرح برای رویداد، نه برای کاربر).
RETURN_CODES = {
    "2": "credit",
    "11": "not-in-panel",
    "12": "not-in-panel",
    "18": "bad-number",
    "19": "daily-cap",
    "22": "daily-cap",
    "-2": "quota",
    "-4": "name-or-pass",
    "-5": "name-or-pass",
    "-6": "name-or-pass",
    "-10": "filtered",
    "-108": "bad-recipient",
    "-109": "ip-not-allowed",
    "-110": "name-or-pass",
}
CREDIT_CLASSES = {"credit", "quota", "name-or-pass", "ip-not-allowed"}


class OtpSendError(RuntimeError):
    """Raised when the provider did not accept the send; reason stays generic."""

    def __init__(self, error_class: str, return_code: str = "") -> None:
        super().__init__(f"otp-send-failed:{error_class}")
        self.error_class = error_class
        self.return_code = return_code


def _emit_failure(error_class: str, return_code: str) -> None:
    emit_later(
        kind="sms",
        title="otp-provider-failed",
        surface="auth",
        status="error",
        payload={"errorClass": error_class, "returnCode": return_code},
    )


def classify(return_code: str) -> str:
    return RETURN_CODES.get(str(return_code or "").strip(), "provider")


async def send_otp(phone: str, code: str) -> str:
    """Send the code inside the approved template. Returns the provider recId."""
    username = str(settings.melipayamak_username or "").strip()
    apikey = str(settings.melipayamak_otp_apikey or "").strip()
    body_id = str(settings.melipayamak_body_id or "").strip()
    base = str(settings.melipayamak_pattern_base or "").rstrip("/")
    if not username or not apikey or not body_id:
        _emit_failure("config", "")
        raise OtpSendError("config")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            response = await client.post(
                f"{base}/SendByBaseNumber2",
                json={
                    "username": username,
                    "password": apikey,
                    "to": phone,
                    "from": "",
                    "text": code,
                    "isFlash": "false",
                    "bodyId": body_id,
                },
            )
    except Exception as exc:
        log.warning("melipayamak pattern request failed: %s", type(exc).__name__)
        _emit_failure("network", type(exc).__name__)
        raise OtpSendError("network") from None
    text = (response.text or "").strip()
    if response.status_code >= 400:
        log.warning("melipayamak pattern rejected: http=%s", response.status_code)
        _emit_failure("provider", f"http-{response.status_code}")
        raise OtpSendError("provider", f"http-{response.status_code}")
    # پنل دو شکل موفق می‌دهد: رشتهٔ عددی (recId) یا {"d":"<recId>"} از مسیر JSON.
    if text.startswith("{") and "\"d\"" in text:
        import json as _json

        try:
            inner = str(_json.loads(text).get("d") or "").strip()
        except Exception:
            inner = ""
        if inner.lstrip("-").isdigit():
            text = inner
    digits = text.strip('"').strip()
    if not digits.lstrip("-").isdigit():
        log.warning("melipayamak pattern unexpected body: %s", text[:60])
        _emit_failure("provider", text[:20])
        raise OtpSendError("provider", text[:20])
    # کدهای خطای مثبت پنل (2/11/12/18/19/22) هم رد هستند؛ فقط recId بلند یعنی پذیرفته شد.
    error_class = classify(digits)
    if not digits.startswith("-") and error_class == "provider" and len(digits) >= 15:
        return digits
    log.warning("melipayamak pattern send failed: code=%s", digits)
    _emit_failure(error_class, digits)
    raise OtpSendError(error_class, digits)
