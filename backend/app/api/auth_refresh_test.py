import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.config import settings
from app.database import get_session
from app.security import decode_token, encode_token, get_current_user


def _client(user=None) -> TestClient:
    app = FastAPI()
    app.include_router(auth_api.router)

    async def fake_session():
        yield MagicMock()

    app.dependency_overrides[get_session] = fake_session
    if user is not None:

        async def fake_user():
            return user

        app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app)


class AuthRefreshTests(unittest.TestCase):
    def test_refresh_returns_full_session_lifetime(self) -> None:
        user = SimpleNamespace(id=uuid4(), role="admin", phone="09111234567", is_active=True)
        res = _client(user).post("/auth/refresh")
        self.assertEqual(res.status_code, 200)
        payload = decode_token(res.json()["access_token"])
        self.assertEqual(payload["sub"], str(user.id))
        self.assertEqual(payload["exp"] - payload["iat"], settings.session_days * 24 * 3600)

    def test_refresh_needs_a_token(self) -> None:
        self.assertEqual(_client().post("/auth/refresh").status_code, 401)

    def test_refresh_rejects_expired_token(self) -> None:
        old = encode_token(uuid4(), "admin", ttl_minutes=-1)
        res = _client().post("/auth/refresh", headers={"Authorization": f"Bearer {old}"})
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
