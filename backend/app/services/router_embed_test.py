from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import httpx

from app.services import router_embed


class RouterEmbedMathTests(unittest.TestCase):
    def test_sample_can_beat_the_mean(self) -> None:
        score = router_embed.intent_score(
            [1.0, 0.0],
            {"mean": [0.0, 1.0], "samples": [[1.0, 0.0]]},
        )
        self.assertAlmostEqual(score, 1.0)

    def test_threshold_keeps_a_tie_with_the_cutoff(self) -> None:
        bank = {"status": {"mean": [1.0, 0.0], "samples": []}}
        tool, score = router_embed.pick_tool([0.6, 0.8], bank, 0.6)
        self.assertEqual(tool, "status")
        self.assertAlmostEqual(score, 0.6)

    def test_below_threshold_runs_nothing(self) -> None:
        bank = {"status": {"mean": [1.0, 0.0], "samples": []}}
        tool, score = router_embed.pick_tool([0.59, 0.8074], bank, 0.6)
        self.assertEqual(tool, "")
        self.assertLess(score, 0.6)

    def test_calibrated_cutoff_is_above_small_talk(self) -> None:
        bank = {"inbox": {"mean": [1.0, 0.0], "samples": []}}
        low, _score = router_embed.pick_tool([0.70, (1 - 0.70**2) ** 0.5], bank)
        high, _score = router_embed.pick_tool([0.75, (1 - 0.75**2) ** 0.5], bank)
        self.assertEqual(low, "")
        self.assertEqual(high, "inbox_status")
        self.assertEqual(router_embed.INTENT_THRESHOLD, 0.75)

    def test_best_intent_wins(self) -> None:
        bank = {
            "status": {"mean": [1.0, 0.0], "samples": []},
            "content": {"mean": [0.0, 1.0], "samples": []},
        }
        tool, _score = router_embed.pick_tool([0.0, 1.0], bank, 0.6)
        self.assertEqual(tool, "studio_chat")

    def test_samples_file_has_four_intents(self) -> None:
        samples = router_embed.load_samples()
        self.assertEqual(set(samples), {"status", "content", "shop", "inbox"})
        for rows in samples.values():
            self.assertGreaterEqual(len(rows), 10)
            self.assertLessEqual(len(rows), 20)

    def test_committed_vectors_match_the_bank(self) -> None:
        samples = router_embed.load_samples()
        bank = router_embed._read_vectors()
        self.assertEqual(set(bank), set(samples))
        for name, rows in samples.items():
            self.assertEqual(len(bank[name]["samples"]), len(rows))
            self.assertEqual(len(bank[name]["mean"]), 1024)
            self.assertEqual(len(bank[name]["samples"][0]), 1024)


class RouterEmbedClientTests(unittest.TestCase):
    def test_client_is_direct_and_uses_bge(self) -> None:
        seen = {}

        class FakeClient:
            def __init__(self, timeout=None, trust_env=False, proxy=None, **kwargs):
                seen["timeout"] = timeout
                seen["trust_env"] = trust_env
                seen["proxy"] = proxy

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                seen["url"] = url
                seen["body"] = json
                seen["auth"] = headers.get("Authorization")
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    json={
                        "usage": {"prompt_tokens": 4},
                        "data": [
                            {"index": 1, "embedding": [0.0, 1.0]},
                            {"index": 0, "embedding": [1.0, 0.0]},
                        ],
                    },
                    request=request,
                )

        route = {
            "kind": "cloud",
            "url": "https://api.arvancloudai.ir/v1",
            "token": "shop-secret",
            "auth": "apikey",
            "proxy": None,
        }
        with patch("app.services.router_embed.route_for_surface", return_value=route), patch(
            "app.services.proxy_health.httpx.AsyncClient", FakeClient
        ), patch("app.services.router_embed._emit_usage", return_value={}):
            rows = asyncio.run(router_embed.embed_texts(["اول", "دوم"]))
        self.assertFalse(seen["trust_env"])
        self.assertIsNone(seen["proxy"])
        self.assertEqual(seen["timeout"], router_embed.EMBED_TIMEOUT)
        self.assertEqual(seen["url"], "https://api.arvancloudai.ir/v1/embeddings")
        self.assertEqual(seen["body"]["model"], "Bge-m3")
        self.assertEqual(seen["auth"], "apikey shop-secret")
        self.assertEqual(rows, [[1.0, 0.0], [0.0, 1.0]])

    def test_embed_failure_keeps_the_turn_on_prose(self) -> None:
        async def boom(_text):
            raise RuntimeError("down")

        bank = {"status": {"mean": [1.0, 0.0], "samples": [[1.0, 0.0]]}}
        with patch("app.services.router_embed.emit_later"):
            tool = asyncio.run(router_embed.rescue_tool("وضعیت", embed=boom, bank=bank))
        self.assertEqual(tool, "")


if __name__ == "__main__":
    unittest.main()
