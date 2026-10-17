import asyncio
import unittest
from unittest.mock import patch

from app.services import inbound_media_service, public_fetch


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


class _FakeClient:
    """Records every URL asked for. `answers` maps a URL to its response; any other URL redirects to the metadata address."""

    def __init__(self, calls: list[str], answers: dict | None = None) -> None:
        self.calls = calls
        self.answers = answers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url: str):
        self.calls.append(url)
        if url in self.answers:
            return self.answers[url]
        return _FakeResponse(302, {"location": "http://169.254.169.254/latest/meta-data/"})


class PublicUrlTests(unittest.TestCase):
    def test_private_and_metadata_addresses_are_not_public(self) -> None:
        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1/a.jpg",
            "http://10.0.0.5/a.jpg",
            "http://192.168.1.10/a.jpg",
            "http://localhost/a.jpg",
            "http://[::1]/a.jpg",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url):
                self.assertFalse(asyncio.run(public_fetch.public_url(url)))

    def test_public_address_is_allowed(self) -> None:
        self.assertTrue(asyncio.run(public_fetch.public_url("https://8.8.8.8/a.jpg")))


class FetchPublicTests(unittest.TestCase):
    def test_redirect_into_metadata_address_is_not_followed(self) -> None:
        calls: list[str] = []
        with patch.object(public_fetch, "async_client", lambda **kwargs: _FakeClient(calls)):
            result = asyncio.run(public_fetch.fetch_public("https://8.8.8.8/a.jpg", 5))
        self.assertEqual(result, (0, {}, b""))
        self.assertEqual(calls, ["https://8.8.8.8/a.jpg"])

    def test_public_redirect_is_followed_hop_by_hop(self) -> None:
        calls: list[str] = []
        answers = {
            "https://8.8.8.8/a.jpg": _FakeResponse(302, {"location": "https://1.1.1.1/b.jpg"}),
            "https://1.1.1.1/b.jpg": _FakeResponse(200, {"content-type": "image/jpeg"}, b"img"),
        }
        with patch.object(public_fetch, "async_client", lambda **kwargs: _FakeClient(calls, answers)):
            status, headers, body = asyncio.run(public_fetch.fetch_public("https://8.8.8.8/a.jpg", 5))
        self.assertEqual((status, body), (200, b"img"))
        self.assertEqual(headers.get("content-type"), "image/jpeg")
        self.assertEqual(calls, ["https://8.8.8.8/a.jpg", "https://1.1.1.1/b.jpg"])

    def test_redirect_loop_stops_after_the_hop_limit(self) -> None:
        calls: list[str] = []
        answers = {"https://8.8.8.8/a.jpg": _FakeResponse(302, {"location": "https://8.8.8.8/a.jpg"})}
        with patch.object(public_fetch, "async_client", lambda **kwargs: _FakeClient(calls, answers)):
            result = asyncio.run(public_fetch.fetch_public("https://8.8.8.8/a.jpg", 5))
        self.assertEqual(result, (0, {}, b""))
        self.assertEqual(len(calls), public_fetch.MAX_HOPS)


class InboundMediaTests(unittest.TestCase):
    def test_redirect_into_private_address_stores_nothing(self) -> None:
        calls: list[str] = []
        with patch.object(public_fetch, "async_client", lambda **kwargs: _FakeClient(calls)), patch.object(
            inbound_media_service.chat_media_service, "save"
        ) as save, patch.object(inbound_media_service, "emit_later"):
            stored = asyncio.run(inbound_media_service.fetch_and_store("https://8.8.8.8/a.jpg", kind_hint="image"))
        self.assertIsNone(stored)
        save.assert_not_called()
        self.assertEqual(calls, ["https://8.8.8.8/a.jpg"])

    def test_public_image_is_stored(self) -> None:
        calls: list[str] = []
        answers = {"https://8.8.8.8/a.jpg": _FakeResponse(200, {"content-type": "image/jpeg"}, b"\xff\xd8img")}
        with patch.object(public_fetch, "async_client", lambda **kwargs: _FakeClient(calls, answers)), patch.object(
            inbound_media_service.chat_media_service, "save", return_value={"ok": True}
        ) as save:
            stored = asyncio.run(inbound_media_service.fetch_and_store("https://8.8.8.8/a.jpg", kind_hint="image"))
        self.assertEqual(stored, {"ok": True})
        save.assert_called_once_with("a.jpg", b"\xff\xd8img", "image/jpeg")


if __name__ == "__main__":
    unittest.main()
