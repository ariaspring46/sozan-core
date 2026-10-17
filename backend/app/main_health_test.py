import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main


class HealthTests(unittest.TestCase):
    """/health answers 503 when the database or Redis is down, so deploys and the health tool turn red."""

    def _get(self, db: bool, cache: bool):
        with patch.object(main, "_db_up", new=AsyncMock(return_value=db)), patch.object(
            main, "_redis_up", new=AsyncMock(return_value=cache)
        ):
            return TestClient(main.app).get("/health")

    def test_all_up_is_200(self) -> None:
        res = self._get(True, True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])

    def test_database_down_is_503(self) -> None:
        res = self._get(False, True)
        self.assertEqual(res.status_code, 503)
        self.assertFalse(res.json()["ok"])
        self.assertFalse(res.json()["db"])

    def test_redis_down_is_503(self) -> None:
        res = self._get(True, False)
        self.assertEqual(res.status_code, 503)
        self.assertFalse(res.json()["redis"])


if __name__ == "__main__":
    unittest.main()
