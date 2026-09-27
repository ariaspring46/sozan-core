import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.services.overlay_service import OverlayService, _overlap, place_caption


class OverlayLayoutTests(unittest.TestCase):
    def test_caption_misses_the_subject(self) -> None:
        width, height = 400, 400
        subject = (40, 140, 360, 340)
        placed = place_caption(width, height, subject, block_h=48, margin=24)
        self.assertFalse(_overlap(placed.box, subject))

    def test_full_frame_subject_uses_a_separate_bar(self) -> None:
        placed = place_caption(400, 400, (10, 10, 390, 390), block_h=60, margin=16)
        self.assertGreater(placed.bar, 0)
        self.assertGreaterEqual(placed.box[1], 400 - placed.bar)

    def test_render_keeps_text_off_the_product_and_skips_a_wide_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            src = root / "src.png"
            image = Image.new("RGB", (400, 400), (244, 240, 232))
            draw = ImageDraw.Draw(image)
            draw.rectangle((80, 150, 320, 340), fill=(24, 64, 140))
            image.save(src)
            fonts = root / "fonts"
            fonts.mkdir()
            # The layout test above does not need a face; render needs one.
            face = _font_file()
            if face is None:
                self.skipTest("font missing")
            (fonts / "Vazirmatn-Regular.ttf").write_bytes(face.read_bytes())
            (fonts / "Vazirmatn-Bold.ttf").write_bytes(face.read_bytes())
            dest = root / "out.png"
            OverlayService(fonts).render(
                src,
                dest,
                title="گردنبند",
                subtitle="",
                cta="",
                format_name="feed",
                logo_path=None,
            )
            out = Image.open(dest).convert("RGB")
            corner = out.getpixel((24, out.height - 24))
            self.assertGreater(corner[0], 180, corner)


class SellerLogoTests(unittest.TestCase):
    def test_packaged_mark_is_not_pasted(self) -> None:
        from app.services.compose_pipeline import _seller_logo

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            packaged = root / "packaged"
            packaged.mkdir()
            (packaged / "logo.png").write_bytes(b"sozan-mark")
            (packaged / "logo-mark.png").write_bytes(b"sozan-mark")
            brand = root / "brand"
            brand.mkdir()
            (brand / "logo.png").write_bytes(b"sozan-mark")
            with patch("app.config.settings") as fake:
                fake.brand_path = packaged
                self.assertIsNone(_seller_logo(brand))
                (brand / "logo.png").write_bytes(b"seller-own-logo")
                found = _seller_logo(brand)
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "logo.png")


def _font_file() -> Path | None:
    candidates = [
        Path("/home/demon/work-f/Sozan-Core/brand/fonts/Vazirmatn-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


if __name__ == "__main__":
    unittest.main()
