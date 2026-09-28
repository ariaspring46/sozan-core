import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import voice_service
from app.state_store import tenant_scope, write_json


class VoiceSampleTests(unittest.TestCase):
    def test_strip_urls_keeps_the_seller_words(self) -> None:
        text = voice_service.strip_urls("سلام بیا https://joahr-froshi.sozan-core.ir/ring و joahr-froshi.sozan-core.ir ببین")
        self.assertEqual(text, "سلام بیا و ببین")
        self.assertNotIn("http", text)
        self.assertNotIn("sozan-core.ir", text)

    def test_learn_does_not_store_a_shop_url(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09120000991"):
                write_json(
                    "voice.json",
                    {
                        "sampleReply": "بیا https://joahr-froshi.sozan-core.ir",
                        "samples": ["https://joahr-froshi.sozan-core.ir فقط همین"],
                    },
                )
                loaded = voice_service.get_voice()
                self.assertNotIn("http", loaded["sampleReply"])
                self.assertEqual(loaded["samples"], ["فقط همین"])
                with patch(
                    "app.services.voice_service.complete_json",
                    new=AsyncMock(
                        return_value={
                            "summary": "گرم",
                            "tone": "کوتاه",
                            "do": [],
                            "dont": [],
                            "sampleReply": "آدرس https://shop.example/x",
                        }
                    ),
                ), patch("app.services.voice_service.emit_later"):
                    saved = asyncio.run(
                        voice_service.learn(
                            platform="instagram",
                            handle="sozan",
                            samples="موجود است https://joahr-froshi.sozan-core.ir",
                        )
                    )
        self.assertNotIn("http", saved["sampleReply"])
        self.assertTrue(all("http" not in item and "sozan-core.ir" not in item for item in saved["samples"]))
        self.assertIn("موجود است", saved["samples"][-1])


if __name__ == "__main__":
    unittest.main()
