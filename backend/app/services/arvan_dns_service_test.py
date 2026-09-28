from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import arvan_dns_service


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")
        self.content = self.text.encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeClient:
    def __init__(self, post_status: int = 201):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.post_status = post_status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        if url.endswith("/domains/dns-service"):
            return FakeResponse(self.post_status, {"message": "The provided data is invalid." if self.post_status >= 400 else "ok", "data": {"name": (json or {}).get("domain")}})
        if url.endswith("/dns-records"):
            return FakeResponse(201, {"data": {"id": "rec1"}})
        return FakeResponse(200, {"message": "ok"})

    def put(self, url, json=None):
        self.calls.append(("PUT", url, json))
        return FakeResponse(200, {"data": {"id": "rec1"}})

    def get(self, url):
        self.calls.append(("GET", url, None))
        if url.endswith("/dns-records"):
            return FakeResponse(200, {"data": []})
        if url.endswith("/cname-setup/check"):
            return FakeResponse(200, {"data": {"status": "pending"}})
        if "/domains/" in url:
            return FakeResponse(200 if self.post_status >= 400 else 404, {"data": {"name": "shop.example.com", "type": "partial"}})
        return FakeResponse(200, {})


class ArvanCnameTests(unittest.TestCase):
    def test_hostname_rejects_reserved(self) -> None:
        self.assertEqual(arvan_dns_service.hostname("not-a-real-cname.invalid"), "")
        self.assertEqual(arvan_dns_service.hostname("https://shop.example.com/path"), "shop.example.com")
        self.assertEqual(arvan_dns_service.hostname("evil.com;x"), "")
        self.assertEqual(arvan_dns_service.hostname("evil.com`x"), "")
        self.assertEqual(arvan_dns_service.hostname("evil.com$x"), "")
        self.assertEqual(arvan_dns_service.hostname('evil.com"x'), "")
        self.assertTrue(arvan_dns_service.is_zone_host("sozan.sozan-core.ir"))
        self.assertFalse(arvan_dns_service.is_zone_host("shop.example.com"))

    def test_start_cname_setup_posts_partial(self) -> None:
        fake = FakeClient(201)
        with (
            patch.object(settings, "arvan_api_key", "k"),
            patch.object(settings, "arvan_origin_ip", "1.2.3.4"),
            patch.object(arvan_dns_service, "_client", return_value=fake),
        ):
            out = arvan_dns_service.start_cname_setup("shop.example.com", "sozan")
        create = next(call for call in fake.calls if call[0] == "POST" and str(call[1]).endswith("/domains/dns-service"))
        self.assertEqual(create[2]["domain_type"], "partial")
        self.assertEqual(create[2]["plan_level"], 2)
        self.assertFalse(create[2]["import_dns_records"])
        custom = next(call for call in fake.calls if call[0] == "PUT" and "cname-setup/custom" in str(call[1]))
        self.assertEqual(custom[2]["address"], "sozan.sozan-core.ir")
        self.assertTrue(out["ok"])
        self.assertTrue(out["created"])
        self.assertTrue(out["origin"]["ok"])

    def test_start_cname_setup_reuses_existing_domain(self) -> None:
        fake = FakeClient(422)
        with (
            patch.object(settings, "arvan_api_key", "k"),
            patch.object(settings, "arvan_origin_ip", "1.2.3.4"),
            patch.object(arvan_dns_service, "_client", return_value=fake),
        ):
            out = arvan_dns_service.start_cname_setup("shop.example.com", "sozan")
        self.assertTrue(out["ok"])
        self.assertFalse(out["created"])
        self.assertTrue(any(call[0] == "PUT" and "cname-setup/custom" in str(call[1]) for call in fake.calls))
        self.assertTrue(any(call[0] == "POST" and str(call[1]).endswith("/dns-records") for call in fake.calls))

    def test_check_cname_matches_shop_host(self) -> None:
        with patch.object(arvan_dns_service, "_cname_answers", return_value=["sozan.sozan-core.ir"]):
            out = arvan_dns_service.check_cname("shop.example.com", "sozan")
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "ok")

    def test_check_cname_accepts_arvan_default(self) -> None:
        with patch.object(arvan_dns_service, "_cname_answers", return_value=["shop.example.com.cdn.arvancloud.ir"]):
            out = arvan_dns_service.check_cname("shop.example.com", "sozan")
        self.assertTrue(out["ok"])

    def test_check_cname_waiting(self) -> None:
        with patch.object(arvan_dns_service, "_cname_answers", return_value=[]):
            out = arvan_dns_service.check_cname("shop.example.com", "sozan")
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "waiting")

    def test_dry_edge_does_not_call_arvan(self) -> None:
        with patch.dict(os.environ, {"SOZAN_EDGE_DRY": "1"}), patch.object(arvan_dns_service, "_client") as client:
            record = arvan_dns_service.ensure_shop_record("tast-didari")
            setup = arvan_dns_service.start_cname_setup("shop.example.com", "tast-didari")
        client.assert_not_called()
        self.assertTrue(record["dry"])
        self.assertTrue(setup["dry"])
        self.assertEqual(record["host"], "tast-didari.sozan-core.ir")


if __name__ == "__main__":
    unittest.main()
