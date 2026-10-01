from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import cloud_cutout_service


class _Resp:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class CloudCutoutTests(unittest.TestCase):
    def setUp(self) -> None:
        emit_patcher = patch.object(cloud_cutout_service, "emit_later")
        self.emit = emit_patcher.start()
        self.addCleanup(emit_patcher.stop)
        for key, value in (
            ("cutout_provider", "clipdrop"),
            ("cutout_api_key", "CUTOUT-KEY-123"),
            ("cloud_llm_url", "https://openrouter.ai/api/v1"),
        ):
            patcher = patch.object(settings, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _client(self, status_code: int = 200, content: bytes = b"\x89PNG"):
        class Client:
            seen_url = ""
            seen_headers = {}

            def __init__(self, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, files=None, params=None):
                Client.seen_url = url
                Client.seen_headers = headers or {}
                return _Resp(status_code, content)

        return Client

    def test_clipdrop_posts_key_and_returns_png(self) -> None:
        client = self._client(200, b"\x89PNG-alpha")
        with patch.object(cloud_cutout_service.httpx, "AsyncClient", client):
            out, cost = asyncio.run(cloud_cutout_service.remove_background(b"input"))
        self.assertTrue(out.startswith(b"\x89PNG"))
        self.assertGreater(cost, 0)
        self.assertEqual(client.seen_headers.get("x-api-key"), "CUTOUT-KEY-123")
        self.assertTrue(client.seen_url.startswith("https://clipdrop-api.co/remove-background"))

    def test_http_error_raises_and_emits_without_image(self) -> None:
        client = self._client(402)
        with patch.object(cloud_cutout_service.httpx, "AsyncClient", client):
            with self.assertRaises(RuntimeError):
                asyncio.run(cloud_cutout_service.remove_background(b"input"))
        self.emit.assert_called_once()
        payload = self.emit.call_args.kwargs.get("payload") or {}
        self.assertEqual(payload.get("returnCode"), "http-402")

    def test_disabled_without_key(self) -> None:
        with patch.object(settings, "cutout_api_key", ""):
            self.assertFalse(cloud_cutout_service.cloud_enabled())


class CutoutFallbackTests(unittest.TestCase):
    def test_fallback_raises_without_key_and_dev_flag(self) -> None:
        from app.services import image_provider_service as img

        with patch.dict("os.environ", {"IMAGE_LOCAL": ""}, clear=False), patch.object(
            img, "cloud_cutout_enabled", return_value=False
        ):
            with self.assertRaises(RuntimeError) as ctx:
                img._cutout_with_fallback(b"input")
        self.assertIn("cutout-unavailable", str(ctx.exception))

    def test_fallback_uses_local_only_behind_dev_flag(self) -> None:
        from app.services import image_provider_service as img

        with patch.dict("os.environ", {"IMAGE_LOCAL": "1"}, clear=False), patch.object(
            img, "cloud_cutout_enabled", return_value=False
        ), patch.object(img, "_cutout", return_value=("fg", "mask")) as local:
            fg, mask = img._cutout_with_fallback(b"input")
        self.assertEqual((fg, mask), ("fg", "mask"))
        local.assert_called_once()

    def test_queue_guard_blocks_over_limit(self) -> None:
        from app.services import image_provider_service as img

        with patch.dict("os.environ", {"CUTOUT_QUEUE_LIMIT": "1"}, clear=False):
            img._CUTOUT_ACTIVE = 1
            with self.assertRaises(RuntimeError) as ctx:
                img._cutout_slot()
            self.assertIn("cutout-busy", str(ctx.exception))
            img._CUTOUT_ACTIVE = 0

    def test_alpha_matches_local_shape(self) -> None:
        # قرارداد آلفا: خروجی ابری L-mask هم‌اندازهٔ عکس اصلی می‌شود (همان شکل isnet)
        import contextlib
        import io

        from PIL import Image

        from app.services import cloud_cutout_service as cc
        from app.services import image_provider_service as img

        src = Image.new("RGB", (64, 64), (200, 30, 30))
        buf = io.BytesIO()
        src.save(buf, "PNG")

        async def fake_remove(png, *, proxy=None):
            rgba2 = Image.new("RGBA", (64, 64), (200, 30, 30, 128))
            out = io.BytesIO()
            rgba2.save(out, "PNG")
            return out.getvalue(), 0.005

        patches = [
            patch.object(settings, "cutout_provider", "openrouter"),
            patch.object(settings, "cloud_llm_url", "https://openrouter.ai/api/v1"),
            patch.dict(
                "os.environ",
                {"open_router_api_token": "OR-T", "CLOUD_LLM_URL": "https://openrouter.ai/api/v1"},
                clear=False,
            ),
            patch.object(cc, "remove_background", new=fake_remove),
        ]
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            original, mask = img._cutout_with_fallback(buf.getvalue())
        self.assertEqual(mask.size, original.size)
        self.assertEqual(mask.mode, "L")


if __name__ == "__main__":
    unittest.main()
