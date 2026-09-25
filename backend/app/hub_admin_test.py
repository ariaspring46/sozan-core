import unittest
from unittest.mock import patch

from app.config import settings
from app.hub_admin import is_hub_admin


class HubAdminTests(unittest.TestCase):
    def test_placeholder_number_is_never_hub_admin(self) -> None:
        with patch.object(settings, "admin_phone", "09120000000"):
            self.assertFalse(is_hub_admin("09120000000"))
            self.assertFalse(is_hub_admin("09135409482"))

    def test_configured_owner_is_hub_admin(self) -> None:
        with patch.object(settings, "admin_phone", "09135409482"):
            self.assertTrue(is_hub_admin("09135409482"))
            self.assertFalse(is_hub_admin("09120000000"))
