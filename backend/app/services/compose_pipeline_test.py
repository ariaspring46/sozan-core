import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.services.compose_pipeline import compose_campaign_dir, save_brief


class ComposePipelineTests(unittest.TestCase):
    def test_produces_feed_and_captions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            still = root / "raw"
            still.mkdir()
            Image.new("RGB", (64, 64), (30, 20, 10)).save(still / "feed.png")
            save_brief(
                root,
                {
                    "title": "ویترین",
                    "subtitle": "شب",
                    "cta": "ببین",
                    "instagram_caption": "کپشن اینستا",
                    "telegram_caption": "کپشن تلگرام",
                    "whatsapp_caption": "واتساپ",
                },
            )

            def fake_render(self, src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
                return dest

            def fake_compose(self, frames, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"mp4")
                return dest

            with patch("app.services.compose_pipeline.OverlayService.render", fake_render), patch(
                "app.services.compose_pipeline.VideoComposeService.compose", fake_compose
            ), patch("app.services.compose_pipeline.settings") as cfg:
                cfg.brand_path = root
                cfg.fonts_path = root
                produced = compose_campaign_dir(root, fonts_dir=root, audio_bed=None)
            self.assertIn("ig-feed", produced)
            self.assertIn("tg-post", produced)
            self.assertIn("ig-reel", produced)
            self.assertTrue((root / "out" / "captions.md").is_file())
            self.assertIn("کپشن اینستا", (root / "out" / "captions.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
