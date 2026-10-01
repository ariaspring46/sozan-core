import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import llm_routing_service
from app.state_store import tenant_scope


class RoutingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        llm_routing_service._cache.update({"at": 0.0, "routes": {}, "providers": []})
        llm_routing_service._stale_emitted = False

    def tearDown(self) -> None:
        llm_routing_service._cache.update({"at": 0.0, "routes": {}, "providers": []})
        self.dir.cleanup()

    def test_apply_payload_keeps_surface_and_provider_model(self) -> None:
        llm_routing_service.apply_payload(
            {
                "routes": {"studio": {"kind": "local", "model": "qwen3.8-27b"}},
                "providers": [
                    {
                        "id": "ollama-cloud",
                        "kind": "openai-chat",
                        "base_url": "https://ollama.com/v1",
                        "key_env": "CLOUD_LLM_TOKEN",
                        "label": "Ollama",
                        "model": "deepseek-v4.1-flash:cloud",
                    }
                ],
            }
        )
        row = llm_routing_service.get("studio")
        self.assertEqual(row["model"], "qwen3.8-27b")
        self.assertEqual(llm_routing_service.provider("ollama-cloud")["model"], "deepseek-v4.1-flash:cloud")

    def test_refresh_failure_keeps_disk_and_emits_once(self) -> None:
        captured = []

        def fake_emit(**kwargs):
            captured.append(kwargs)

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, *args, **kwargs):
                raise RuntimeError("down")

        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name), patch(
            "app.services.observe_client.emit_later", new=fake_emit
        ), patch("app.services.llm_routing_service.httpx.AsyncClient", FakeClient):
            llm_routing_service.apply_payload({"routes": {"inbox": {"kind": "local", "model": "qwen3.8-27b"}}})
            llm_routing_service._cache["at"] = 0.0
            llm_routing_service._cache["routes"] = {}
            ok = asyncio.run(llm_routing_service.refresh())
            self.assertFalse(ok)
            self.assertEqual(llm_routing_service.get("inbox")["model"], "qwen3.8-27b")
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["title"], "routing-stale")
            asyncio.run(llm_routing_service.refresh())
            self.assertEqual(len(captured), 1)


class ImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        # Routing/provider behaviour only; the budget gate has its own test (agentic_regressions_test).
        cap = patch("app.services.image_provider_service._image_budget_capped", return_value=None)
        cap.start()
        self.addCleanup(cap.stop)

    def test_local_path_posts_observe(self) -> None:
        from app.services import image_provider_service

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, json=None, headers=None):
                self.url = url
                class Res:
                    status_code = 200
                    content = b"\x89PNG" + b"0" * 3000
                    headers = {"content-type": "image/png"}
                    text = ""
                return Res()

        with patch("app.services.llm_routing_service.get", return_value={}), patch(
            "app.services.image_provider_service.httpx.Client", FakeClient
        ), patch("app.services.image_provider_service.observe_base", return_value="http://127.0.0.1:9292"), patch.dict(
            os.environ, {"IMAGE_LOCAL": "1"}
        ):
            png = image_provider_service.generate_still("mug")
        self.assertGreaterEqual(len(png), 2048)

    def test_cloud_fail_does_not_use_local(self) -> None:
        from app.services import image_provider_service

        # env هاب fallback تصویر (seedream) دارد؛ این تست نبودِ محلیِ موازی را می‌سنجد.
        with patch.dict(os.environ, {"IMAGE_FALLBACK": "none", "open_router_api_token": ""}, clear=False), patch(
            "app.services.llm_routing_service.get",
            return_value={"kind": "cloud", "model": "x", "provider": "p"},
        ), patch("app.services.llm_routing_service.provider", return_value={}), patch(
            "app.services.image_provider_service._observe_local", return_value=b"\x89PNG" + b"0" * 3000
        ) as local:
            png = image_provider_service.generate_still("mug")
        local.assert_not_called()
        self.assertEqual(png, b"")

    def test_empty_prompt_does_not_generate(self) -> None:
        from app.services import image_provider_service

        with patch("app.services.image_provider_service._observe_local") as local:
            png = image_provider_service.generate_still("")
        local.assert_not_called()
        self.assertEqual(png, b"")


if __name__ == "__main__":
    unittest.main()
