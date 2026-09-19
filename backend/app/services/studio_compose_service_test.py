import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services import studio_chat_service, studio_compose_service


class FakeCampaigns:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.raw: list[str] = []
        self.bytes = b""

    async def save_raw(self, campaign_id, filename, data):
        self.raw.append(filename)
        self.bytes = data
        return SimpleNamespace(id=uuid4())

    async def compose(self, campaign_id):
        if self.fail:
            raise RuntimeError("ffmpeg")
        return SimpleNamespace(id=campaign_id)

    async def preview_outputs(self, campaign_id):
        if self.fail:
            return []
        return [
            {"kind": "image", "path": "/tmp/ig-feed.png", "name": "ig-feed.png"},
            {"kind": "video", "path": "/tmp/ig-reel.mp4", "name": "ig-reel.mp4"},
        ]


class StudioComposeTests(unittest.TestCase):
    def _session(self, fake: FakeCampaigns):
        session_cm = patch("app.services.studio_compose_service.SessionLocal")
        svc = patch("app.services.studio_compose_service._svc", return_value=fake)
        cm = session_cm.start()
        svc.start()
        cm.return_value.__aenter__ = AsyncMock(return_value=object())
        cm.return_value.__aexit__ = AsyncMock(return_value=False)
        self.addCleanup(session_cm.stop)
        self.addCleanup(svc.stop)
        return fake

    def test_no_still_saves_feed_png(self) -> None:
        png = b"\x89PNG" + b"0" * 3000
        fake = self._session(FakeCampaigns())
        with patch("app.services.studio_compose_service.generate_still", return_value=png), patch(
            "app.services.studio_chat_service.set_compose"
        ), patch("app.services.studio_chat_service.finish_compose") as finish, patch(
            "app.services.studio_chat_service.attach_still", new=AsyncMock(return_value=False)
        ), patch("app.services.studio_chat_service.fallback_attachment", return_value=[]), patch(
            "app.services.studio_chat_service.copy_outputs",
            return_value=[{"kind": "image", "name": "ig-feed.png"}, {"kind": "video", "name": "ig-reel.mp4"}],
        ), patch("app.services.studio_compose_service.emit_later"):
            asyncio.run(
                studio_compose_service._run(
                    tenant="09120001111",
                    message_id="m1",
                    campaign_id=str(uuid4()),
                    media=None,
                    title="ویترین",
                    image_prompt="mug, no text",
                    job_id="j1",
                    started=0,
                )
            )
        self.assertEqual(fake.raw, ["feed.png"])
        self.assertEqual(fake.bytes, png)
        self.assertEqual(finish.call_args.kwargs["status"], "ready")
        attachments = finish.call_args.args[1]
        kinds = {item["kind"] for item in attachments}
        self.assertEqual(kinds, {"image", "video"})

    def test_ffmpeg_failure_marks_failed(self) -> None:
        png = b"\x89PNG" + b"0" * 3000
        self._session(FakeCampaigns(fail=True))
        with patch("app.services.studio_compose_service.generate_still", return_value=png), patch(
            "app.services.studio_chat_service.set_compose"
        ), patch("app.services.studio_chat_service.finish_compose") as finish, patch(
            "app.services.studio_chat_service.attach_still", new=AsyncMock(return_value=False)
        ), patch(
            "app.services.studio_chat_service.fallback_attachment", return_value=[{"kind": "image", "name": "x.png"}]
        ), patch("app.services.studio_compose_service.emit_later") as emit:
            asyncio.run(
                studio_compose_service._run(
                    tenant="09120001111",
                    message_id="m2",
                    campaign_id=str(uuid4()),
                    media=None,
                    title="ویترین",
                    image_prompt="",
                    job_id="j2",
                    started=0,
                )
            )
        self.assertEqual(finish.call_args.kwargs["status"], "failed")
        titles = [call.kwargs.get("title") for call in emit.call_args_list]
        self.assertIn("compose-failed", titles)

    def test_watchdog_flips_stale_running(self) -> None:
        rows = [{"id": "m3", "compose": {"status": "running", "startedAt": 1}}]
        with patch("app.services.studio_chat_service._messages", return_value=rows), patch(
            "app.services.studio_chat_service._save"
        ) as save, patch("app.services.studio_chat_service.tenant_file_lock"), patch(
            "app.services.studio_chat_service.emit_later"
        ):
            studio_chat_service.expire_stale_compose(10)
        self.assertEqual(rows[0]["compose"]["status"], "failed")
        self.assertIn("طول کشید", rows[0]["compose"]["error"])
        save.assert_called()

    def test_finish_compose_ignores_stale_job(self) -> None:
        rows = [{"id": "m1", "compose": {"status": "running", "jobId": "new", "startedAt": 1}}]
        with patch("app.services.studio_chat_service._messages", return_value=rows), patch(
            "app.services.studio_chat_service._save"
        ), patch("app.services.studio_chat_service.tenant_file_lock"):
            skipped = studio_chat_service.finish_compose(
                "m1", [{"kind": "image", "name": "x.png"}], status="ready", job_id="old"
            )
        self.assertFalse(skipped)
        self.assertEqual(rows[0]["compose"]["status"], "running")
        self.assertEqual(rows[0]["compose"]["jobId"], "new")


if __name__ == "__main__":
    unittest.main()
