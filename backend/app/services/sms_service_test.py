from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import sms_service


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, captured: dict, response: _FakeResponse) -> None:
        self.captured = captured
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, json=None, data=None):
        self.captured["url"] = url
        self.captured["headers"] = headers
        self.captured["json"] = json
        self.captured["data"] = data
        return self.response


class SmsIrTests(unittest.TestCase):
    def test_mobile_drops_leading_zero(self) -> None:
        self.assertEqual(sms_service.smsir_mobile("09135409482"), "9135409482")

    def test_verify_payload_matches_sms_ir_docs(self) -> None:
        captured: dict = {}
        response = _FakeResponse({"status": 1, "message": "موفق", "data": {"messageId": 1, "cost": 1}})

        def factory(*_args, **_kwargs):
            return _FakeClient(captured, response)

        with patch("app.services.sms_service.httpx.AsyncClient", factory):
            asyncio.run(
                sms_service.send_otp(
                    provider="smsir",
                    api_key="test-key",
                    template_id="499682",
                    token_name="Code",
                    phone="09135409482",
                    code="123456",
                )
            )
        self.assertEqual(captured["url"], "https://api.sms.ir/v1/send/verify")
        self.assertEqual(captured["headers"]["x-api-key"], "test-key")
        self.assertEqual(captured["json"]["mobile"], "9135409482")
        self.assertEqual(captured["json"]["templateId"], 499682)
        self.assertEqual(captured["json"]["parameters"], [{"name": "Code", "value": "123456"}])

    def test_resolve_sms_falls_back_to_hub_env(self) -> None:
        with (
            patch.object(settings, "sms_provider", "smsir"),
            patch.object(settings, "sms_ir_api_key", "hub-key"),
            patch.object(settings, "sms_ir_template_id", "499682"),
            patch.object(settings, "sms_ir_token_name", "Code"),
        ):
            sms = sms_service.resolve_sms({"smsApiKey": "", "smsTemplateId": ""})
        self.assertEqual(sms["provider"], "smsir")
        self.assertEqual(sms["api_key"], "hub-key")
        self.assertEqual(sms["template_id"], "499682")
        self.assertEqual(sms["token_name"], "Code")
