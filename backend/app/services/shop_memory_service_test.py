import time
import unittest
from unittest.mock import patch

import httpx

from app.services import shop_memory_service as mem
from app.state_store import tenant_scope


class ShopMemoryTest(unittest.TestCase):
    def test_key_hides_the_phone(self) -> None:
        with tenant_scope("09121110099"):
            key = mem.memory_key()
        self.assertNotIn("09121110099", key)
        self.assertEqual(len(key), 32)
        self.assertEqual(key, mem.memory_key("09121110099"))

    def test_two_shops_do_not_share_rows(self) -> None:
        store = mem.MemoryBackend()
        with patch.object(mem, "backend", return_value=store):
            mem.upsert("catalog", [{"id": "a", "document": "کفش چرم ۴۰۰۰۰۰۰"}], phone="09121110099")
            mem.upsert("catalog", [{"id": "b", "document": "انگشتر نقره"}], phone="09121110098")
            own = mem.search("catalog", "کفش", phone="09121110099")
            other = mem.search("catalog", "کفش", phone="09121110098")
        self.assertEqual([row["id"] for row in own], ["a"])
        self.assertEqual(other, [])

    def test_delete_removes_only_that_shop(self) -> None:
        store = mem.MemoryBackend()
        with patch.object(mem, "backend", return_value=store):
            mem.upsert("policies", [{"id": "p", "document": "ارسال ۳۰ هزار"}], phone="09121110099")
            mem.upsert("policies", [{"id": "q", "document": "ارسال ۴۰ هزار"}], phone="09121110098")
            mem.delete_shop(phone="09121110099")
            self.assertEqual(mem.export_shop(phone="09121110099"), {})
            kept = mem.export_shop(phone="09121110098")
        self.assertIn("policies", kept)

    def test_chroma_database_name_is_the_hash(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path.endswith("/databases"):
                return httpx.Response(200, json={"name": "ok"})
            if request.url.path.endswith("/collections"):
                return httpx.Response(200, json={"id": "col-1"})
            return httpx.Response(200, json={"ok": True})

        key = mem.memory_key("09121110099")
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            mem.ChromaHttp("http://127.0.0.1:8008", client=http).upsert(
                key, "catalog", [{"id": "a", "document": "کفش", "metadata": {}}]
            )
        self.assertTrue(any(key in url for url in seen))
        self.assertFalse(any("09121110099" in url for url in seen))

    def test_one_row_can_be_deleted(self) -> None:
        store = mem.MemoryBackend()
        with patch.object(mem, "backend", return_value=store):
            mem.upsert(
                "catalog",
                [{"id": "a", "document": "انگشتر"}, {"id": "b", "document": "گردنبند"}],
                phone="09121110099",
            )
            mem.delete("catalog", "a", phone="09121110099")
            left = mem.search("catalog", "", phone="09121110099")
        self.assertEqual([row["id"] for row in left], ["b"])

    def test_chroma_delete_posts_one_id(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.method == "GET":
                return httpx.Response(200, json={"id": "col-1"})
            return httpx.Response(200, json={"ok": True})

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            mem.ChromaHttp("http://127.0.0.1:8008", client=http).delete("shopkey", "catalog", "a")
        self.assertTrue(any(path.endswith("/delete") for path in seen))

    def test_backfill_does_not_block_the_caller(self) -> None:
        def slow(*_args, **_kwargs) -> int:
            time.sleep(1.2)
            return 0

        with patch.object(mem, "backfill_catalog", slow):
            started = time.monotonic()
            mem.schedule_backfill([{"id": "1", "title": "انگشتر"}], phone="09120000000")
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.5)
        self.assertFalse(mem.studio_hints_enabled())


if __name__ == "__main__":
    unittest.main()
