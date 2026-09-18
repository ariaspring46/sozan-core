import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from app.config import settings
from app.services import product_image_service, storefront_service
from app.services.channel_scan_service import _scan_dir
from app.state_store import tenant_scope


def _png(width: int, height: int, color: str = "red") -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


class ProductImageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_png_becomes_downscaled_jpg(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name):
            name = product_image_service.store(_png(2000, 800), "image/png", "shot.png")
            path = _scan_dir() / name
            self.assertTrue(name.endswith(".jpg"))
            self.assertTrue(path.is_file())
            with Image.open(path) as img:
                self.assertEqual(img.format, "JPEG")
                self.assertLessEqual(max(img.size), 1600)
                self.assertEqual(img.size[0], 1600)

    def test_exif_rotation(self) -> None:
        buf = BytesIO()
        img = Image.new("RGB", (20, 40), "blue")
        exif = img.getexif()
        exif[0x0112] = 6
        img.save(buf, "JPEG", exif=exif)
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name):
            name = product_image_service.store(buf.getvalue(), "image/jpeg", "rot.jpg")
            with Image.open(_scan_dir() / name) as out:
                self.assertEqual(out.size, (40, 20))

    def test_reject_non_image_and_oversize(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name):
            with self.assertRaises(ValueError):
                product_image_service.store(b"not-an-image", "text/plain", "a.txt")
            with self.assertRaises(ValueError):
                product_image_service.store(b"x" * (8_000_001), "image/jpeg", "big.jpg")

    def test_remove_if_unreferenced_keeps_shared(self) -> None:
        with tenant_scope("09120001111"), patch.object(settings, "state_dir", self.dir.name):
            shared = product_image_service.store(_png(32, 32), "image/png", "a.png")
            orphan = product_image_service.store(_png(32, 32, "green"), "image/png", "b.png")
            storefront_service.add_product(title="یکی", price=1, stock=1, sku="", image=shared)
            storefront_service.add_product(title="دومی", price=1, stock=1, sku="", image=shared)
            self.assertFalse(product_image_service.remove_if_unreferenced(shared))
            self.assertTrue((_scan_dir() / shared).is_file())
            self.assertTrue(product_image_service.remove_if_unreferenced(orphan))
            self.assertFalse((_scan_dir() / orphan).is_file())


if __name__ == "__main__":
    unittest.main()
