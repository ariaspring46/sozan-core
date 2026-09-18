import unittest

from app.services import channel_poll_service


class ChannelPollBackoffTests(unittest.TestCase):
    def tearDown(self) -> None:
        channel_poll_service._fail_counts.clear()
        channel_poll_service._backoff_until.clear()

    def test_three_failures_enter_backoff(self) -> None:
        key = "p:telegram:bot"
        channel_poll_service._note_poll_result(key, False)
        channel_poll_service._note_poll_result(key, False)
        self.assertFalse(channel_poll_service._in_backoff(key))
        channel_poll_service._note_poll_result(key, False)
        self.assertTrue(channel_poll_service._in_backoff(key))
        channel_poll_service._note_poll_result(key, True)
        self.assertFalse(channel_poll_service._in_backoff(key))


if __name__ == "__main__":
    unittest.main()
