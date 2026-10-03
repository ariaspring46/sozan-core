from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.api.chat_payload import parse_chat_json


class ChatPayloadTests(unittest.TestCase):
    def test_valid_text(self) -> None:
        body = parse_chat_json({"text": " سلام ", "viewPath": "/", "viewTarget": ""})
        self.assertEqual(body.text.strip(), "سلام")

    def test_empty_and_long_text_are_400_with_a_reason(self) -> None:
        with self.assertRaises(HTTPException) as empty:
            parse_chat_json({"text": ""})
        self.assertEqual(empty.exception.status_code, 400)
        self.assertIn("لازم", empty.exception.detail)
        with self.assertRaises(HTTPException) as long:
            parse_chat_json({"text": "ا" * 4001})
        self.assertEqual(long.exception.status_code, 400)
        self.assertIn("بلند", long.exception.detail)
        with self.assertRaises(HTTPException) as bad:
            parse_chat_json(["not", "an", "object"])
        self.assertEqual(bad.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
