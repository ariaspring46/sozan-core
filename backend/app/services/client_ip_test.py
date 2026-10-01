import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.client_ip import client_ip
from app.config import settings


def _req(headers: dict, host: str = "10.0.0.1"):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))


class ClientIpTests(unittest.TestCase):
    def test_default_is_socket_address(self) -> None:
        with patch.object(settings, "trusted_ip_header", ""):
            self.assertEqual(client_ip(_req({"x-forwarded-for": "1.2.3.4"})), "10.0.0.1")

    def test_trusted_header_first_value(self) -> None:
        with patch.object(settings, "trusted_ip_header", "x-real-visitor"):
            self.assertEqual(client_ip(_req({"x-real-visitor": "5.6.7.8, 9.9.9.9"})), "5.6.7.8")

    def test_missing_header_falls_back(self) -> None:
        with patch.object(settings, "trusted_ip_header", "x-real-visitor"):
            self.assertEqual(client_ip(_req({})), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
