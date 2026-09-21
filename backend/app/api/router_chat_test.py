import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router_chat as chat_api
from app.database import get_session
from app.security import get_current_user
from app.state_store import tenant_scope


class RouterChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        app = FastAPI()
        app.include_router(chat_api.router)

        async def fake_user():
            return SimpleNamespace(phone="09129900001", role="admin", is_active=True)

        async def fake_session():
            yield MagicMock()

        app.dependency_overrides[get_current_user] = fake_user
        app.dependency_overrides[get_session] = fake_session
        self.client = TestClient(app)
        self.store: dict = {}

        def reader(name, default=None):
            return dict(self.store)

        def writer(name, payload):
            self.store.clear()
            if isinstance(payload, dict):
                self.store.update(payload)

        self.idem_read = patch("app.services.idempotency_service.read_json", side_effect=reader)
        self.idem_write = patch("app.services.idempotency_service.write_json", side_effect=writer)
        self.idem_read.start()
        self.idem_write.start()

    def tearDown(self) -> None:
        self.idem_read.stop()
        self.idem_write.stop()
        self.dir.cleanup()

    def test_get_snapshot(self) -> None:
        with tenant_scope("09129900001"), patch(
            "app.services.router_service.snapshot",
            return_value={"messages": [], "pendingConfirm": None},
        ):
            res = self.client.get("/chat")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["messages"], [])

    def test_post_idempotent(self) -> None:
        payload = {"messages": [{"role": "assistant", "text": "انجام شد"}], "pendingConfirm": None}
        with tenant_scope("09129900001"), patch(
            "app.services.router_service.turn",
            new=AsyncMock(return_value=payload),
        ) as turn:
            first = self.client.post("/chat", json={"text": "سلام"}, headers={"Idempotency-Key": "r1"})
            second = self.client.post("/chat", json={"text": "سلام دوباره"}, headers={"Idempotency-Key": "r1"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(turn.await_count, 1)

    def test_post_confirm_without_text(self) -> None:
        payload = {"messages": [{"role": "assistant", "text": "به‌روز شد"}], "pendingConfirm": None}
        with tenant_scope("09129900001"), patch(
            "app.services.router_service.turn",
            new=AsyncMock(return_value=payload),
        ) as turn:
            res = self.client.post("/chat", json={"confirmId": "abc"})
        self.assertEqual(res.status_code, 200)
        turn.assert_awaited_once()
        self.assertEqual(turn.await_args.kwargs.get("confirm_id"), "abc")

    def test_post_cancel_without_text(self) -> None:
        payload = {"messages": [{"role": "assistant", "text": "باشه، انجامش نمی‌دهم."}], "pendingConfirm": None, "brand": ""}
        with tenant_scope("09129900001"), patch(
            "app.services.router_service.turn",
            new=AsyncMock(return_value=payload),
        ) as turn:
            res = self.client.post("/chat", json={"cancelId": "abc"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(turn.await_args.kwargs.get("cancel_id"), "abc")

    def test_post_multipart_carries_confirm(self) -> None:
        payload = {"messages": [], "pendingConfirm": None}
        with tenant_scope("09129900001"), patch(
            "app.services.router_service.turn",
            new=AsyncMock(return_value=payload),
        ) as turn, patch(
            "app.services.chat_media_service.save",
            return_value={"kind": "image", "name": "a.png"},
        ):
            res = self.client.post(
                "/chat",
                data={"text": "عکس", "confirmId": "abc"},
                files={"file": ("a.png", b"\x89PNG\r\n", "image/png")},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(turn.await_args.kwargs.get("confirm_id"), "abc")
        self.assertEqual(turn.await_args.kwargs.get("media"), {"kind": "image", "name": "a.png"})


if __name__ == "__main__":
    unittest.main()
