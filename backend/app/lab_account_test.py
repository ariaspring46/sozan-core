import unittest

from app.lab_account import LAB_PHONE, require_lab_phone


class LabAccountTests(unittest.TestCase):
    def test_only_the_reserved_phone_is_accepted(self) -> None:
        self.assertEqual(require_lab_phone(LAB_PHONE), LAB_PHONE)
        with self.assertRaises(ValueError):
            require_lab_phone("09135409482")
        with self.assertRaises(ValueError):
            require_lab_phone("09120007777")
