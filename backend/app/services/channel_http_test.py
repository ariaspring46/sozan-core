import asyncio
import unittest
from unittest.mock import patch

import httpx

from app.config import settings
from app.services import channel_http


class _Scripted(httpx.AsyncBaseTransport):
    def __init__(self, proxy=None, script=None):
        self.proxy = proxy
        self.script = script if script is not None else []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        step = self.script.pop(0) if self.script else "ok"
        channel_http_seen.append({"proxy": self.proxy, "connect": (request.extensions.get("timeout") or {}).get("connect")})
        if step == "connect":
            raise httpx.ConnectTimeout("no route")
        if step == "read":
            raise httpx.ReadTimeout("started")
        if isinstance(step, Exception):
            raise step
        return httpx.Response(200, request=request)

    async def aclose(self) -> None:
        return None


channel_http_seen: list[dict] = []


class ChannelHttpTests(unittest.TestCase):
    def test_socks_scheme_and_foreign_hosts(self) -> None:
        with patch.object(settings, "channel_proxy", "socks5://127.0.0.1:10891"):
            self.assertEqual(channel_http.channel_proxy(), "socks5h://127.0.0.1:10891")
        for host in (
            "instagram.com",
            "www.instagram.com",
            "scontent.cdninstagram.com",
            "video.fbcdn.net",
            "graph.facebook.com",
            "api.telegram.org",
            "t.me",
            "telegram.me",
        ):
            self.assertTrue(channel_http.foreign_host(host), host)
        for host in ("api.sendbox.chat", "boxapi.ir", "tapi.bale.ai", "botapi.rubika.ir", "openrouter.ai"):
            self.assertFalse(channel_http.foreign_host(host), host)

    def test_mounts_proxy_foreign_and_leave_iran_direct(self) -> None:
        with (
            patch.object(settings, "channel_proxy", "socks5h://127.0.0.1:10891"),
            patch.object(settings, "channel_proxy_fallback", "socks5h://127.0.0.1:10890"),
        ):
            client = channel_http.async_client()
            self.assertEqual(channel_http.proxies_for("https://t.me/s/telegram"), [
                "socks5h://127.0.0.1:10891",
                "socks5h://127.0.0.1:10890",
            ])
            self.assertEqual(channel_http.proxies_for("https://boxapi.ir/api"), [])
        try:
            foreign = client._transport_for_url(httpx.URL("https://www.instagram.com/sozan_core/"))
            direct = client._transport_for_url(httpx.URL("https://api.sendbox.chat/api/v1/service/info"))
            self.assertIsInstance(foreign, channel_http.FailoverProxyTransport)
            self.assertNotIsInstance(direct, channel_http.FailoverProxyTransport)
        finally:
            asyncio.run(client.aclose())

    def test_connect_failure_uses_fallback_and_a_read_does_not(self) -> None:
        channel_http_seen.clear()
        request = httpx.Request("GET", "https://api.telegram.org/")
        request.extensions["timeout"] = {"connect": 20.0, "read": 20.0, "write": 20.0, "pool": 20.0}

        def build(proxy=None):
            kind = "connect" if str(proxy).endswith("10891") else "ok"
            return _Scripted(proxy=proxy, script=[kind])

        with patch("app.services.channel_http.httpx.AsyncHTTPTransport", build):
            transport = channel_http.FailoverProxyTransport(
                ["socks5h://127.0.0.1:10891", "socks5h://127.0.0.1:10890"]
            )
            response = asyncio.run(transport.handle_async_request(request))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["proxy"] for row in channel_http_seen], [
            "socks5h://127.0.0.1:10891",
            "socks5h://127.0.0.1:10890",
        ])
        self.assertEqual(channel_http_seen[0]["connect"], channel_http.CONNECT_LIMIT)
        self.assertEqual(request.extensions["timeout"]["connect"], 20.0)

        channel_http_seen.clear()
        read_request = httpx.Request("GET", "https://api.telegram.org/")

        def read_build(proxy=None):
            return _Scripted(proxy=proxy, script=["read"])

        with patch("app.services.channel_http.httpx.AsyncHTTPTransport", read_build):
            transport = channel_http.FailoverProxyTransport(
                ["socks5h://127.0.0.1:10891", "socks5h://127.0.0.1:10890"]
            )
            with self.assertRaises(httpx.ReadTimeout):
                asyncio.run(transport.handle_async_request(read_request))
        self.assertEqual(len(channel_http_seen), 1)

    def test_without_proxies_the_body_is_still_readable(self) -> None:
        # review 2026-10-09: the direct transport was closed right after the headers, before the body was read
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"x" * 70000
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                return None

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/"

        async def fetch() -> int:
            async with httpx.AsyncClient(transport=channel_http.FailoverProxyTransport([])) as client:
                res = await client.get(url)
                return len(res.content)

        self.assertEqual(asyncio.run(fetch()), 70000)


if __name__ == "__main__":
    unittest.main()
