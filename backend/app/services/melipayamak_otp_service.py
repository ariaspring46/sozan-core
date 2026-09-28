"""Login OTP through the Melipayamak console service.

The provider builds and texts the code itself; it hands the code back in the
response. The API key travels inside the request URL, so no log line, event or
exception text here may ever contain the URL — only the error class.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.observe_client import emit_later

log = logging.getLogger("sozan.sms")

TIMEOUT = 12.0


class OtpSendError(RuntimeError):
    """Raised when the provider did not hand back a code; reason stays generic."""

    def __init__(self, error_class: str) -> None:
        super().__init__(f"otp-send-failed:{error_class}")
        self.error_class = error_class


def _credit_or_key_problem(http_status: int, status_text: str) -> bool:
    text = status_text.lower()
    return (
        http_status in {401, 402, 403}
        or "credit" in text
        or "اعتبار" in status_text
        or "key" in text
        or "کلید" in status_text
        or "apikey" in text
    )


def _emit_failure(error_class: str, http_status: int) -> None:
    emit_later(
        kind="sms",
        title="otp-provider-failed",
        surface="auth",
        status="error",
        payload={"errorClass": error_class, "http": http_status},
    )


async def send_otp(phone: str) -> str:
    """Send the OTP SMS and return the code the provider generated."""
    apikey = str(settings.melipayamak_otp_apikey or "").strip()
    if not apikey:
        _emit_failure("config", 0)
        raise OtpSendError("config")
    url = f"{str(settings.melipayamak_otp_base or '').rstrip('/')}/{apikey}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            response = await client.post(url, json={"to": phone})
    except Exception as exc:
        # فقط نام نوع خطا؛ آدرس (که کلید داخلش است) هرگز لاگ نمی‌شود.
        log.warning("melipayamak otp request failed: %s", type(exc).__name__)
        _emit_failure("network", 0)
        raise OtpSendError("network") from None
    body: dict = {}
    try:
        loaded = response.json()
        if isinstance(loaded, dict):
            body = loaded
    except Exception:
        body = {}
    code = str(body.get("code") or "").strip()
    status_text = str(body.get("status") or "").strip()
    if response.status_code >= 400 or not code:
        error_class = "credit-or-key" if _credit_or_key_problem(response.status_code, status_text) else "provider"
        log.warning("melipayamak otp rejected: http=%s class=%s", response.status_code, error_class)
        _emit_failure(error_class, response.status_code)
        raise OtpSendError(error_class)
    return code
