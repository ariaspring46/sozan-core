from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services import channel_poll_service
from app.state_store import tenant_scope


class ChannelPollBackoffTests(unittest.TestCase):
    def tearDown(self) -> None:
        channel_poll_service._fail_counts.clear()
        channel_poll_service._backoff_until.clear()
        channel_poll_service._last_ig.clear()
        channel_poll_service._gap_skips.clear()
        channel_poll_service._poll_skip_emitted.clear()

    def test_three_failures_enter_backoff(self) -> None:
        key = "p:telegram:bot"
        channel_poll_service._note_poll_result(key, False)
        channel_poll_service._note_poll_result(key, False)
        self.assertFalse(channel_poll_service._in_backoff(key))
        channel_poll_service._note_poll_result(key, False)
        self.assertTrue(channel_poll_service._in_backoff(key))
        channel_poll_service._note_poll_result(key, True)
        self.assertFalse(channel_poll_service._in_backoff(key))

    def test_two_instagram_accounts_are_not_polled(self) -> None:
        accounts = [
            {"platform": "instagram", "handle": "one", "credentials": {"unipileAccountId": "u1"}},
            {"platform": "instagram", "handle": "two", "credentials": {"sendboxAccountId": "s1"}},
            {"platform": "telegram", "handle": "bot", "credentials": {"botToken": "t"}},
        ]
        pull = AsyncMock(return_value={"ok": True})
        with (
            tenant_scope("09123456789"),
            patch("app.services.channel_poll_service.channel_service.iter_accounts", return_value=accounts),
            patch("app.services.channel_poll_service.channel_service.token_for", side_effect=lambda row: "t" if row["platform"] == "telegram" else ""),
            patch("app.services.channel_poll_service.plan_service.current", return_value={"dmSync": True}),
            patch("app.services.channel_poll_service.telegram_service.pull_updates", pull),
        ):
            asyncio.run(channel_poll_service.poll_tenant())
        self.assertEqual(pull.call_count, 1)
        pull.assert_awaited_once_with(token="t", handle="bot")

    def test_poll_skip_emits_once_after_two_gap_cycles(self) -> None:
        emit = []

        def fake_emit(**kwargs):
            emit.append(kwargs)

        key = "09123456789:instagram:one"
        now = 1000.0
        channel_poll_service._last_ig[key] = now
        with patch("app.services.channel_poll_service.emit_later", fake_emit):
            self.assertFalse(channel_poll_service._ig_due(key, now + 1))
            self.assertEqual(emit, [])
            self.assertFalse(channel_poll_service._ig_due(key, now + 2))
            self.assertEqual(len(emit), 1)
            self.assertEqual(emit[0]["title"], "poll-skip")
            self.assertFalse(channel_poll_service._ig_due(key, now + 3))
            self.assertEqual(len(emit), 1)
