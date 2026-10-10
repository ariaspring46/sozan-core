from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import http_ece
import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings
from app.services import seller_alerts, seller_events
from app.state_store import tenant_scope

PHONE = "09135409482"
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class _Browser:
    """What a browser hands the page in PushSubscription.toJSON()."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        point = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.p256dh = _b64(point)
        self.auth_b64 = _b64(self.auth)

    def read(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))


class _Tenant(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.state = patch.object(settings, "state_dir", self.tmp.name)
        self.state.start()
        self.scope = tenant_scope(PHONE)
        self.scope.__enter__()

    def tearDown(self) -> None:
        self.scope.__exit__(None, None, None)
        self.state.stop()
        self.tmp.cleanup()

    def _client(self, handler):
        real = httpx.AsyncClient

        def make(*args, **kwargs):
            kwargs.pop("trust_env", None)
            return real(transport=httpx.MockTransport(handler), **kwargs)

        return patch.object(seller_alerts.httpx, "AsyncClient", side_effect=make)


class SubscribeTests(_Tenant):
    def test_only_known_push_services_and_real_keys(self) -> None:
        browser = _Browser()
        for endpoint in ("http://fcm.googleapis.com/x", "https://127.0.0.1:9292/x", "https://evil.example/fcm.googleapis.com", "https://fcm.googleapis.com.evil.io/x"):
            with self.assertRaises(ValueError, msg=endpoint):
                seller_alerts.subscribe(endpoint, browser.p256dh, browser.auth_b64)
        with self.assertRaises(ValueError):
            seller_alerts.subscribe(FCM, "short", browser.auth_b64)
        self.assertEqual(seller_alerts.subscribe(FCM, browser.p256dh, browser.auth_b64), 1)
        self.assertEqual(seller_alerts.subscribe(FCM, browser.p256dh, browser.auth_b64), 1)  # the same device once
        for n in range(6):
            seller_alerts.subscribe(f"https://updates.push.services.mozilla.com/wpush/v2/{n}", browser.p256dh, browser.auth_b64)
        self.assertEqual(seller_alerts.devices(), seller_alerts.MAX_SUBS)
        self.assertEqual(seller_alerts.unsubscribe("https://updates.push.services.mozilla.com/wpush/v2/5"), seller_alerts.MAX_SUBS - 1)

    def test_the_key_is_made_once(self) -> None:
        first = seller_alerts.public_key()
        self.assertEqual(seller_alerts.public_key(), first)
        self.assertEqual(len(base64.urlsafe_b64decode(first + "==")), 65)


class PushTests(_Tenant):
    def test_the_browser_can_read_it_and_the_push_service_can_check_who_sent_it(self) -> None:
        browser = _Browser()
        seller_alerts.subscribe(FCM, browser.p256dh, browser.auth_b64)
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201)

        with self._client(handler):
            out = asyncio.run(seller_alerts.push("سوزان", "رسید تازه برای «انگشتر فیروزه» آمد.", tag="receipt"))
        self.assertEqual(out["sent"], 1)
        request = seen[0]
        self.assertEqual(str(request.url), FCM)
        self.assertEqual(request.headers["content-encoding"], "aes128gcm")
        self.assertEqual(browser.read(request.content), {"title": "سوزان", "body": "رسید تازه برای «انگشتر فیروزه» آمد.", "url": "/chat", "tag": "receipt"})
        scheme, _, rest = request.headers["authorization"].partition(" ")
        fields = dict(part.strip().split("=", 1) for part in rest.split(","))
        self.assertEqual(scheme, "vapid")
        self.assertEqual(fields["k"], seller_alerts.public_key())
        point = base64.urlsafe_b64decode(fields["k"] + "==")
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
        claims = jwt.decode(fields["t"], public, algorithms=["ES256"], audience="https://fcm.googleapis.com")
        self.assertEqual(claims["sub"], "https://app.sozan-core.ir")

    def test_a_device_that_is_gone_is_forgotten(self) -> None:
        browser = _Browser()
        seller_alerts.subscribe(FCM, browser.p256dh, browser.auth_b64)
        with self._client(lambda request: httpx.Response(410)):
            out = asyncio.run(seller_alerts.push("سوزان", "x"))
        self.assertEqual((out["sent"], out["gone"]), (0, 1))
        self.assertEqual(seller_alerts.devices(), 0)


class AlertTests(_Tenant):
    def test_no_device_urgent_event_goes_by_sms_with_a_daily_cap(self) -> None:
        with patch.object(settings, "melipayamak_seller_body_id", "555"), patch(
            "app.services.melipayamak_otp_service.send_pattern", new=AsyncMock(return_value="1" * 18)
        ) as sms:
            channels = [asyncio.run(seller_alerts.alert("receipt", "رسید آمد.")) for _ in range(seller_alerts.SMS_PER_DAY + 1)]
            later = asyncio.run(seller_alerts.alert("ship48", "یادآوری."))
        self.assertEqual(channels[:-1], ["sms"] * seller_alerts.SMS_PER_DAY)
        self.assertEqual(channels[-1], "sms-cap")
        self.assertEqual(later, "none")  # a reminder is not worth an SMS
        self.assertEqual(sms.await_args.args, (PHONE, "رسید کارت‌به‌کارت تازه"))
        self.assertEqual(sms.await_args.kwargs["body_id"], "555")

    def test_a_device_means_no_sms(self) -> None:
        browser = _Browser()
        seller_alerts.subscribe(FCM, browser.p256dh, browser.auth_b64)
        with self._client(lambda request: httpx.Response(201)), patch.object(settings, "melipayamak_seller_body_id", "555"), patch(
            "app.services.melipayamak_otp_service.send_pattern", new=AsyncMock()
        ) as sms:
            self.assertEqual(asyncio.run(seller_alerts.alert("paid", "سفارش تازه پرداخت شد: «انگشتر». بقیه.")), "push")
        sms.assert_not_awaited()

    def test_without_a_template_nothing_is_sent(self) -> None:
        with patch("app.services.melipayamak_otp_service.send_pattern", new=AsyncMock()) as sms:
            self.assertEqual(asyncio.run(seller_alerts.alert("paid", "x")), "none")
        sms.assert_not_awaited()

    def test_every_event_reaches_the_alerts(self) -> None:
        with patch("app.services.router_service.post_notice"), patch("app.services.router_service.resolve_thread", return_value="t"), patch.object(
            seller_alerts, "alert_soon"
        ) as alerted:
            seller_events.announce("receipt:o1", "رسید آمد.")
            seller_events.announce("receipt:o1", "رسید آمد.")
        alerted.assert_called_once_with("receipt", "رسید آمد.")


if __name__ == "__main__":
    unittest.main()
