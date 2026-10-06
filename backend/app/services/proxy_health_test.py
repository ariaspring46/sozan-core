import asyncio
import unittest
from unittest.mock import patch

import httpx

from app.services import llm, proxy_health

PROXY = "socks5h://127.0.0.1:10888"
URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER = {
    "kind": "cloud",
    "url": "https://openrouter.ai/api/v1",
    "model": "deepseek/deepseek-v4.1-flash",
    "token": "or-test",
    "proxy": PROXY,
    "auth": "Bearer",
    "source": "settings",
}
ARVAN = {
    "kind": "cloud",
    "url": "https://api.arvancloudai.ir/v1",
    "model": "GPT-OSS-120B",
    "token": "arvan-test",
    "proxy": None,
    "auth": "Bearer",
    "source": "fallback",
}


def _clients(seen: list, *, tunnel: list, direct: list):
    """Fake httpx clients. Each path answers from its own script, one step per call, the last step repeating:
    "ok" (200), "403" (the Iran refusal), "connect" (did not connect), or an exception instance."""

    def step(path: list, url: str) -> httpx.Response:
        what = path.pop(0) if len(path) > 1 else path[0]
        request = httpx.Request("POST", url)
        if what == "connect":
            raise httpx.ConnectTimeout("no answer", request=request)
        if isinstance(what, Exception):
            raise what
        if what == "403":
            return httpx.Response(403, json={"error": "Access denied"}, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "باشه"}}]}, request=request)

    class Base:
        def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
            self.timeout = timeout
            self.proxy = proxy

        def _post(self, url):
            seen.append({"url": url, "proxy": self.proxy, "timeout": self.timeout})
            return step(tunnel if self.proxy else direct, url)

    class AsyncFake(Base):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            return self._post(url)

    class SyncFake(Base):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            return self._post(url)

    return AsyncFake, SyncFake


class ProxyHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        proxy_health._down_until.clear()
        self.addCleanup(proxy_health._down_until.clear)

    def _post(self, seen: list, *, tunnel: list, direct: list, calls: int = 1) -> list[int]:
        fake, _ = _clients(seen, tunnel=tunnel, direct=direct)
        codes = []
        with patch("app.services.proxy_health.httpx.AsyncClient", fake):
            for _ in range(calls):
                codes.append(asyncio.run(proxy_health.post(URL, proxy=PROXY, total=10, json={})).status_code)
        return codes

    def test_direct_answers_and_the_fallback_is_not_used(self) -> None:
        seen: list = []
        codes = self._post(seen, tunnel=["ok"], direct=["ok"], calls=2)
        self.assertEqual(codes, [200, 200])
        self.assertEqual([item["proxy"] for item in seen], [None, None])
        self.assertEqual(seen[0]["timeout"].connect, proxy_health.DIRECT_CONNECT_TIMEOUT)

    def test_refused_direct_uses_the_fallback(self) -> None:
        seen: list = []
        codes = self._post(seen, tunnel=["ok"], direct=["403"])
        self.assertEqual(codes, [200])
        self.assertEqual([item["proxy"] for item in seen], [None, PROXY])
        self.assertEqual(seen[1]["timeout"].connect, proxy_health.CONNECT_TIMEOUT)

    def test_connect_failure_uses_the_fallback(self) -> None:
        seen: list = []
        codes = self._post(seen, tunnel=["ok"], direct=["connect"])
        self.assertEqual(codes, [200])
        self.assertEqual([item["proxy"] for item in seen], [None, PROXY])

    def test_both_paths_down_raises_for_the_arvan_fallback(self) -> None:
        seen: list = []
        with self.assertRaises(httpx.ConnectTimeout):
            self._post(seen, tunnel=["connect"], direct=["connect"])
        self.assertEqual([item["proxy"] for item in seen], [None, PROXY])

    def test_tunnel_is_tried_again_after_the_pause(self) -> None:
        proxy_health.mark_down(PROXY)
        self.assertIsNone(proxy_health.live(PROXY))
        later = proxy_health.time.monotonic() + proxy_health.DOWN_SECONDS + 1
        with patch("app.services.proxy_health.time.monotonic", return_value=later):
            self.assertEqual(proxy_health.live(PROXY), PROXY)

    def test_a_reply_that_started_is_never_sent_twice(self) -> None:
        seen: list = []
        slow = httpx.ReadTimeout("slow model", request=httpx.Request("POST", URL))
        with self.assertRaises(httpx.ReadTimeout):
            self._post(seen, tunnel=["ok"], direct=[slow])
        self.assertEqual(len(seen), 1)
        self.assertIsNone(seen[0]["proxy"])

    def test_no_proxy_keeps_the_callers_timeout(self) -> None:
        seen: list = []
        fake, _ = _clients(seen, tunnel=["ok"], direct=["403"])
        with patch("app.services.proxy_health.httpx.AsyncClient", fake):
            res = asyncio.run(proxy_health.post(URL, proxy=None, total=45, json={}))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(seen[0]["timeout"], 45)
        self.assertEqual(proxy_health.timeout(120, None, connect=8.0).connect, 8.0)
        self.assertEqual(proxy_health.timeout(2, PROXY).connect, 2)

    def test_sync_image_call_tries_direct_then_fallback(self) -> None:
        seen: list = []
        _, sync = _clients(seen, tunnel=["ok"], direct=["connect"])
        with patch("app.services.proxy_health.httpx.Client", sync):
            res = proxy_health.post_sync(URL, proxy=PROXY, total=120, connect=8.0, json={})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([item["proxy"] for item in seen], [None, PROXY])
        self.assertEqual(seen[0]["timeout"].connect, 8.0)

    def test_router_reply_skips_arvan_when_direct_works(self) -> None:
        seen: list = []
        events: list = []
        fake, _ = _clients(seen, tunnel=["connect"], direct=["ok"])
        with patch("app.services.llm.route_for_surface", return_value=dict(OPENROUTER)), patch(
            "app.services.llm._fallback_cloud_route", return_value=dict(ARVAN)
        ), patch("app.services.llm._budget_capped", return_value=None), patch(
            "app.services.proxy_health.httpx.AsyncClient", fake
        ), patch("app.services.llm.emit_later", new=lambda **kw: events.append(kw.get("title"))):
            text = asyncio.run(
                llm._chat_completion(messages=[{"role": "user", "content": "سلام"}], temperature=0, max_tokens=50, surface="router")
            )
        self.assertEqual(text, "باشه")
        self.assertEqual([(item["proxy"], "openrouter.ai" in item["url"]) for item in seen], [(None, True)])
        self.assertNotIn("cloud-fallback", events)


if __name__ == "__main__":
    unittest.main()
