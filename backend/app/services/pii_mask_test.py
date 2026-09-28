import unittest

from app.services.pii_mask import mask_pii


class PiiMaskTest(unittest.TestCase):
    def test_mobile_shapes(self) -> None:
        for raw in ("09121234567", "۰۹۱۲۱۲۳۴۵۶۷", "+989121234567", "00989121234567", "0912-123-4567"):
            out = mask_pii(f"شماره‌ام {raw} است")
            self.assertNotIn("9121234567", out.replace("[تلفن]", ""))
            self.assertIn("[تلفن]", out)

    def test_landline(self) -> None:
        out = mask_pii("تلفن ثابت 02188776655")
        self.assertIn("[تلفن]", out)
        self.assertNotIn("2188776655", out)

    def test_card_sheba_and_codes(self) -> None:
        out = mask_pii("کارت 6037-9977-1234-5678 و IR820540102680020817909002 و کد 0491234567")
        self.assertIn("[کارت]", out)
        self.assertIn("[شبا]", out)
        self.assertIn("[کد]", out)
        self.assertNotIn("6037", out)
        self.assertNotIn("820540", out)
        self.assertNotIn("0491234567", out)

    def test_address_and_price_kept(self) -> None:
        out = mask_pii("خیابان ولیعصر پلاک ۱۲. قیمت ۴۰۰۰۰۰۰ تومان است")
        self.assertIn("[نشانی]", out)
        self.assertNotIn("ولیعصر", out)
        self.assertIn("4000000", out)


if __name__ == "__main__":
    unittest.main()
