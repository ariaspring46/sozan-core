import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.services import public_media_service, studio_publish_service
from app.state_store import tenant_scope


class StudioPublishTests(unittest.TestCase):
    def test_telegram_requires_post_target(self) -> None:
        with patch(
            "app.services.studio_publish_service.channel_service.account_for_platform",
            return_value={"id": "tg", "platform": "telegram", "credentials": {"botToken": "tok"}},
        ), patch(
            "app.services.studio_publish_service.channel_service.token_for",
            return_value="tok",
        ), patch(
            "app.services.studio_publish_service.channel_service.post_target_for",
            return_value="",
        ), patch(
            "app.services.studio_publish_service.chat_media_service.resolve",
            return_value=Path("/tmp/x.png"),
        ):
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(
                    studio_publish_service.publish(
                        platform="telegram",
                        caption="سلام",
                        media_name="x-image.png",
                        media_kind="image",
                    )
                )
        self.assertIn("مقصد پست", str(ctx.exception))

    def test_whatsapp_requires_destination(self) -> None:
        with patch(
            "app.services.studio_publish_service.channel_service.account_for_platform",
            return_value={"id": "wa", "platform": "whatsapp", "credentials": {"accessToken": "tok", "phoneNumberId": "1"}},
        ), patch(
            "app.services.studio_publish_service.channel_service.token_for",
            return_value="tok",
        ), patch(
            "app.services.studio_publish_service.channel_service.credentials_for",
            return_value={"accessToken": "tok", "phoneNumberId": "1"},
        ), patch(
            "app.services.studio_publish_service.channel_service.post_target_for",
            return_value="",
        ), patch(
            "app.services.studio_publish_service.chat_media_service.resolve",
            return_value=Path("/tmp/x.png"),
        ):
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(
                    studio_publish_service.publish(
                        platform="whatsapp",
                        caption="سلام",
                        media_name="x-image.png",
                        media_kind="image",
                    )
                )
        self.assertIn("مقصد", str(ctx.exception))

    def test_telegram_uploads_local_file(self) -> None:
        send_photo = AsyncMock()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value={"id": "tg", "platform": "telegram"},
            ), patch(
                "app.services.studio_publish_service.channel_service.token_for",
                return_value="tok",
            ), patch(
                "app.services.studio_publish_service.channel_service.post_target_for",
                return_value="@myshop",
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ), patch(
                "app.services.studio_publish_service.telegram_service.send_photo",
                new=send_photo,
            ):
                result = asyncio.run(
                    studio_publish_service.publish(
                        platform="telegram",
                        caption="کپشن تلگرام",
                        media_name=path.name,
                        media_kind="image",
                    )
                )
        self.assertTrue(result["ok"])
        send_photo.assert_awaited_once()
        kwargs = send_photo.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], "@myshop")
        self.assertEqual(kwargs["path"], path)
        self.assertEqual(kwargs["caption"], "کپشن تلگرام")

    def test_telegram_publish_marks_message(self) -> None:
        send_photo = AsyncMock()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value={"id": "tg", "platform": "telegram"},
            ), patch(
                "app.services.studio_publish_service.channel_service.token_for",
                return_value="tok",
            ), patch(
                "app.services.studio_publish_service.channel_service.post_target_for",
                return_value="@myshop",
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ), patch(
                "app.services.studio_publish_service.telegram_service.send_photo",
                new=send_photo,
            ), patch(
                "app.services.studio_chat_service.mark_published",
                return_value={"messages": [{"id": "m1", "published": {"telegram": 1}}]},
            ) as marked:
                result = asyncio.run(
                    studio_publish_service.publish(
                        platform="telegram",
                        caption="سلام",
                        media_name="pic-image.png",
                        media_kind="image",
                        message_id="m1",
                    )
                )
        marked.assert_called_once_with("m1", "telegram")
        self.assertEqual(result["messages"][0]["published"]["telegram"], 1)

    def test_skips_duplicate_publish_within_window(self) -> None:
        with patch(
            "app.services.studio_publish_service.studio_chat_service.recently_published",
            return_value=True,
        ), patch(
            "app.services.studio_publish_service.studio_chat_service.snapshot",
            return_value={"messages": [{"id": "m1", "published": {"telegram": 1}}]},
        ):
            result = asyncio.run(
                studio_publish_service.publish(
                    platform="telegram",
                    caption="سلام",
                    media_name="x.png",
                    media_kind="image",
                    message_id="m1",
                )
            )
        self.assertTrue(result.get("skipped"))
        self.assertIn("تأیید", result.get("message") or "")

    def test_instagram_sendbox_waits_for_studio_publish(self) -> None:
        from app.services import channel_service

        row = {"id": "ig", "platform": "instagram", "credentials": {"sendboxAccountId": "acc-1"}}
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value=row,
            ), patch(
                "app.services.studio_publish_service.channel_service.unipile_account_id",
                return_value="",
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ):
                with self.assertRaises(ValueError) as ctx:
                    asyncio.run(
                        studio_publish_service.publish(
                            platform="instagram",
                            caption="کپشن اینستا",
                            media_name=path.name,
                            media_kind="image",
                        )
                    )
        self.assertEqual(str(ctx.exception), channel_service.IG_STUDIO_WAIT)

    def test_public_media_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media = root / "chat-media"
            media.mkdir()
            path = media / "pic-image.png"
            path.write_bytes(b"png")
            with tenant_scope("09120000000"), patch(
                "app.services.chat_media_service.tenant_dir", return_value=root
            ), patch("app.services.public_media_service.current_tenant", return_value="09120000000"):
                url = public_media_service.public_url(name=path.name, ttl=120)
                token = url.rsplit("/", 1)[-1]
                resolved = public_media_service.resolve_token(token)
                self.assertEqual(resolved.name, path.name)

    def test_public_media_rejects_bad_token(self) -> None:
        with self.assertRaises(HTTPException):
            public_media_service.resolve_token("not-a-token")

    def test_clips_caption_to_platform_limit(self) -> None:
        send_photo = AsyncMock()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value={"id": "tg", "platform": "telegram"},
            ), patch(
                "app.services.studio_publish_service.channel_service.token_for",
                return_value="tok",
            ), patch(
                "app.services.studio_publish_service.channel_service.post_target_for",
                return_value="@myshop",
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ), patch(
                "app.services.studio_publish_service.telegram_service.send_photo",
                new=send_photo,
            ):
                asyncio.run(
                    studio_publish_service.publish(
                        platform="telegram",
                        caption="س" * 2000,
                        media_name=path.name,
                        media_kind="image",
                    )
                )
        self.assertEqual(len(send_photo.await_args.kwargs["caption"]), 1024)

    def test_force_bypasses_duplicate_window(self) -> None:
        send_photo = AsyncMock()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.studio_chat_service.recently_published",
                return_value=True,
            ), patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value={"id": "tg", "platform": "telegram"},
            ), patch(
                "app.services.studio_publish_service.channel_service.token_for",
                return_value="tok",
            ), patch(
                "app.services.studio_publish_service.channel_service.post_target_for",
                return_value="@myshop",
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ), patch(
                "app.services.studio_publish_service.telegram_service.send_photo",
                new=send_photo,
            ), patch(
                "app.services.studio_publish_service.studio_chat_service.mark_published",
                return_value={"messages": []},
            ), patch("app.services.studio_publish_service.emit_later"):
                result = asyncio.run(
                    studio_publish_service.publish(
                        platform="telegram",
                        caption="سلام",
                        media_name=path.name,
                        media_kind="image",
                        message_id="m1",
                        force=True,
                    )
                )
        self.assertTrue(result["ok"])
        self.assertFalse(result.get("skipped"))
        send_photo.assert_awaited_once()

    def test_provider_error_emits_publish_failed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value={"id": "tg", "platform": "telegram"},
            ), patch(
                "app.services.studio_publish_service.channel_service.token_for",
                return_value="tok",
            ), patch(
                "app.services.studio_publish_service.channel_service.post_target_for",
                return_value="@myshop",
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ), patch(
                "app.services.studio_publish_service.telegram_service.send_photo",
                new=AsyncMock(side_effect=RuntimeError("httpx")),
            ), patch("app.services.studio_publish_service.emit_later") as emit:
                with self.assertRaises(ValueError):
                    asyncio.run(
                        studio_publish_service.publish(
                            platform="telegram",
                            caption="سلام",
                            media_name=path.name,
                            media_kind="image",
                            campaign_id="c1",
                        )
                    )
        titles = [call.kwargs.get("title") for call in emit.call_args_list]
        self.assertIn("publish-failed", titles)
        self.assertEqual(emit.call_args.kwargs.get("operation_id"), "c1")

    def test_instagram_legacy_token_asks_reconnect(self) -> None:
        from app.services import channel_service

        row = {"id": "ig", "platform": "instagram", "credentials": {"accessToken": "meta"}}
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pic-image.png"
            path.write_bytes(b"png")
            with patch(
                "app.services.studio_publish_service.channel_service.account_for_platform",
                return_value=row,
            ), patch(
                "app.services.studio_publish_service.chat_media_service.resolve",
                return_value=path,
            ):
                with self.assertRaises(ValueError) as ctx:
                    asyncio.run(
                        studio_publish_service.publish(
                            platform="instagram",
                            caption="کپشن اینستا",
                            media_name=path.name,
                            media_kind="image",
                        )
                    )
        self.assertEqual(str(ctx.exception), channel_service.IG_RECONNECT)


if __name__ == "__main__":
    unittest.main()
