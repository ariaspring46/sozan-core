import unittest
from unittest.mock import patch

import httpx

from app import egress


class EgressTests(unittest.TestCase):
    def setUp(self) -> None:
        egress._is_local.cache_clear()

    def _with(self, egress_ip: str = "", origin_ip: str = ""):
        return patch.multiple(egress.settings, egress_source_ip=egress_ip, arvan_origin_ip=origin_ip)

    def test_hub_ip_binds_the_transport(self) -> None:
        with self._with(origin_ip="127.0.0.1"):
            kwargs = egress.client_kwargs()
            sync = egress.client_kwargs(sync=True)
        self.assertIsInstance(kwargs["transport"], httpx.AsyncHTTPTransport)
        self.assertIsInstance(sync["transport"], httpx.HTTPTransport)

    def test_explicit_setting_wins(self) -> None:
        with self._with(egress_ip="127.0.0.1", origin_ip="203.0.113.9"):
            self.assertEqual(egress.source_ip(), "127.0.0.1")

    def test_address_of_another_machine_is_ignored(self) -> None:
        # a dev box or CI with the prod origin IP in its env must not fail every SMS with "cannot assign address"
        with self._with(origin_ip="203.0.113.9"):
            self.assertEqual(egress.client_kwargs(), {})

    def test_nothing_configured(self) -> None:
        with self._with():
            self.assertEqual(egress.client_kwargs(sync=True), {})


if __name__ == "__main__":
    unittest.main()
