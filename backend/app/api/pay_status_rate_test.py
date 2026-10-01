import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import pay
from app.main import app


class StatusRateLimitTests(unittest.TestCase):
    def test_sixty_first_request_from_same_ip_is_rejected(self) -> None:
        pay._status_hits.clear()
        with patch("app.api.pay.client_ip", return_value="198.51.100.7"):
            client = TestClient(app)
            codes = [
                client.get("/p/does-not-exist/status").status_code for _ in range(61)
            ]
        self.assertEqual(codes[:60], [404] * 60)
        self.assertEqual(codes[60], 429)

    def test_unique_ips_do_not_share_the_bucket(self) -> None:
        pay._status_hits.clear()
        client = TestClient(app)
        for i in range(65):
            with patch("app.api.pay.client_ip", return_value=f"203.0.113.{i}"):
                code = client.get("/p/does-not-exist/status").status_code
            self.assertEqual(code, 404)

    def test_bucket_map_is_capped(self) -> None:
        pay._status_hits.clear()
        for i in range(10_050):
            pay._status_rate_allow(f"192.0.2.{i % 251}.{i % 7}")
        self.assertLessEqual(len(pay._status_hits), 10_000)


if __name__ == "__main__":
    unittest.main()
