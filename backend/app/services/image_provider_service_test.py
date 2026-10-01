import base64
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from app.services import image_provider_service


def _png(color: tuple[int, int, int] = (1, 2, 3), size: tuple[int, int] = (8, 8)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _payload(blob: bytes, *, cost: float = 0.014, provider: str = "Together") -> dict:
    raw = "data:image/png;base64," + base64.b64encode(blob).decode("ascii")
    return {
        "provider": provider,
        "usage": {"cost": cost, "prompt_tokens": 8, "completion_tokens": 1},
        "choices": [{"message": {"images": [{"image_url": {"url": raw}}]}}],
    }


class ImageCutoverTests(unittest.TestCase):
    def test_parse_data_uri_and_body_is_image_only(self) -> None:
        blob = _png()
        parsed = image_provider_service._image_bytes(_payload(blob))
        self.assertEqual(parsed, blob)
        body = image_provider_service._body("black-forest-labs/flux.2-klein-4b", "mug", (1080, 1080), b"")
        self.assertEqual(body["modalities"], ["image"])
        self.assertNotIn("text", body["modalities"])
        self.assertEqual(body["image_config"]["aspect_ratio"], "1:1")
        story = image_provider_service._body("black-forest-labs/flux.2-klein-4b", "mug", (1080, 1920), b"")
        self.assertEqual(story["image_config"]["aspect_ratio"], "9:16")

    def test_size_snaps_to_post_or_story(self) -> None:
        self.assertEqual(image_provider_service.snap_size(1280, 720), (1080, 1080))
        self.assertEqual(image_provider_service.snap_size(400, 1800), (1080, 1920))

    def test_fresh_scene_label_stays_on_klein(self) -> None:
        calls = []

        def fake_post(url, token, body, timeout=None):
            calls.append(body["model"])
            return _payload(_png())

        env = {"open_router_api_token": "or-test-key", "IMAGE_FALLBACK": "none", "IMAGE_LOCAL": ""}
        with patch.dict("os.environ", env, clear=False), patch(
            "app.services.image_provider_service._post", side_effect=fake_post
        ), patch("app.services.image_provider_service._fit", side_effect=lambda data, size: data + b"0" * 3000), patch(
            "app.services.image_provider_service.emit_later"
        ):
            fresh = image_provider_service.generate_image("a leather bag", edit=True, edit_kind="scene", plan="pro")
        self.assertEqual(calls, [image_provider_service.DEFAULT_MODEL])
        self.assertTrue(fresh.get("png"))
        events = []
        with patch.dict("os.environ", env, clear=False), patch(
            "app.services.image_provider_service._post", side_effect=fake_post
        ) as posted, patch(
            "app.services.image_provider_service.emit_later", side_effect=lambda **kwargs: events.append(kwargs)
        ):
            blocked = image_provider_service.generate_image(
                "put it in a box",
                edit=True,
                edit_kind="scene",
                plan="pro",
                source=b"png",
            )
        posted.assert_not_called()
        self.assertEqual(blocked.get("png"), b"")
        self.assertTrue(blocked.get("failed"))
        self.assertIn("image-failed", [event["title"] for event in events])

    def test_model_follows_plan(self) -> None:
        self.assertEqual(image_provider_service.model_for(edit=False, plan="pro"), image_provider_service.DEFAULT_MODEL)
        self.assertEqual(image_provider_service.model_for(edit=True, plan="pro"), image_provider_service.DEFAULT_MODEL)
        self.assertEqual(image_provider_service.model_for(edit=True, plan="free"), image_provider_service.DEFAULT_MODEL)
        self.assertEqual(
            image_provider_service.model_for(edit=True, plan="promax"),
            image_provider_service.DEFAULT_EDIT_MODEL,
        )
        self.assertEqual(
            image_provider_service.model_for(edit=True, plan="ultra"),
            image_provider_service.DEFAULT_EDIT_MODEL,
        )
        self.assertTrue(image_provider_service.is_hard_edit("همین عکس را ویرایش کن"))
        self.assertFalse(image_provider_service.is_hard_edit("رسمی‌تر کن"))

    def test_cutout_releases_the_session(self) -> None:
        import importlib.util

        if importlib.util.find_spec("rembg") is None:
            self.skipTest("rembg نصب نیست (وابستگی محیط)")
        buf = BytesIO()
        Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buf, "PNG")
        with patch("rembg.new_session", return_value=object()) as made, patch(
            "rembg.remove", return_value=buf.getvalue()
        ):
            foreground, mask = image_provider_service._cutout(_png())
        made.assert_called_once_with("isnet-general-use")
        self.assertIsNone(image_provider_service._CUTOUT)
        self.assertEqual(foreground.size, (8, 8))
        self.assertEqual(mask.getpixel((0, 0)), 255)

    def test_openrouter_uses_named_key_and_no_proxy(self) -> None:
        seen = {}

        def fake_post(url, token, body, timeout=None):
            seen["url"] = url
            seen["token"] = token
            seen["modalities"] = body["modalities"]
            return _payload(_png())

        env = {
            "open_router_api_token": "or-test-key",
            "CLOUD_LLM_TOKEN": "should-not-use",
            "IMAGE_FALLBACK_URL": "",
            "CLOUD_LLM_FALLBACK_URL": "",
            "IMAGE_LOCAL": "",
            "OPENROUTER_PROXY": "",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "app.services.image_provider_service._post", side_effect=fake_post
        ), patch("app.services.image_provider_service._fit", side_effect=lambda data, size: data + b"0" * 3000), patch(
            "app.services.image_provider_service.emit_later"
        ):
            result = image_provider_service.generate_image("mug")
            self.assertIsNone(image_provider_service._proxy_for("https://openrouter.ai/api/v1"))
        self.assertEqual(seen["token"], "or-test-key")
        self.assertIn("openrouter.ai", seen["url"])
        self.assertEqual(seen["modalities"], ["image"])
        with patch.dict("os.environ", {"OPENROUTER_PROXY": "socks5://127.0.0.1:9"}, clear=False):
            self.assertEqual(
                image_provider_service._proxy_for("https://openrouter.ai/api/v1"),
                "socks5://127.0.0.1:9",
            )
        self.assertIsNone(image_provider_service._proxy_for("https://ai.arvancloudai.ir/v1"))
        self.assertEqual(result["cost"], 0.014)
        self.assertEqual(result["provider"], "Together")
        self.assertNotIn("or-test-key", seen["url"])

    def test_timeout_falls_back_to_gemini_and_skips_local(self) -> None:
        calls = []

        def fake_post(url, token, body, timeout=None):
            calls.append((url, body["model"], timeout))
            if "openrouter.ai" in url:
                raise image_provider_service.ImageHttpError(0)
            return _payload(_png((9, 9, 9)), cost=0.068, provider="arvan")

        env = {
            "open_router_api_token": "or-test-key",
            "IMAGE_FALLBACK": "arvan",
            "IMAGE_RETRY_PAUSE": "0",
            "IMAGE_FALLBACK_URL": "https://ai.sozan-core.ir/v1",
            "IMAGE_FALLBACK_MODEL": "Gemini-3.1-Flash-Image-Preview",
            "IMAGE_FALLBACK_TOKEN": "arvan-test",
            "IMAGE_LOCAL": "",
        }
        events = []
        with patch.dict("os.environ", env, clear=False), patch(
            "app.services.image_provider_service._post", side_effect=fake_post
        ), patch("app.services.image_provider_service._fit", side_effect=lambda data, size: data + b"0" * 3000), patch(
            "app.services.image_provider_service._observe_local", return_value=b"\x89PNG" + b"0" * 3000
        ) as local, patch(
            "app.services.image_provider_service.emit_later", side_effect=lambda **kwargs: events.append(kwargs)
        ):
            result = image_provider_service.generate_image("mug")
        local.assert_not_called()
        self.assertEqual(calls[0][1], image_provider_service.DEFAULT_MODEL)
        self.assertEqual(calls[0][2], image_provider_service.KLEIN_TIMEOUT)
        self.assertEqual(calls[1][1], image_provider_service.DEFAULT_MODEL)
        self.assertEqual(calls[2][1], "Gemini-3.1-Flash-Image-Preview")
        self.assertEqual(calls[2][2], image_provider_service.ARVAN_IMAGE_TIMEOUT)
        self.assertTrue(result["fallback"])
        self.assertTrue(result["charged"])
        self.assertEqual(result["png"][:4], b"\x89PNG")
        reasons = [event["payload"]["reason"] for event in events if event["title"] == "image-fallback"]
        self.assertEqual(reasons, ["timeout"])
        self.assertIn("image-retry", [event["title"] for event in events])

    def test_both_clouds_fail_without_local(self) -> None:
        env = {
            "open_router_api_token": "or-test-key",
            "IMAGE_FALLBACK": "none",
            "IMAGE_RETRY_PAUSE": "0",
            "IMAGE_FALLBACK_URL": "https://ai.sozan-core.ir/v1",
            "IMAGE_FALLBACK_TOKEN": "arvan-test",
            "IMAGE_LOCAL": "",
        }
        events = []
        with patch.dict("os.environ", env, clear=False), patch(
            "app.services.image_provider_service._post", side_effect=image_provider_service.ImageHttpError(500)
        ) as posted, patch(
            "app.services.image_provider_service._observe_local", return_value=b"\x89PNG" + b"0" * 3000
        ) as local, patch(
            "app.services.image_provider_service.emit_later", side_effect=lambda **kwargs: events.append(kwargs)
        ):
            result = image_provider_service.generate_image("mug")
        local.assert_not_called()
        self.assertEqual(posted.call_count, 2)
        self.assertEqual(result.get("png"), b"")
        self.assertTrue(result.get("failed"))
        self.assertFalse(result.get("charged"))
        self.assertEqual(result.get("message"), image_provider_service.FAIL_TEXT)
        titles = [event["title"] for event in events]
        self.assertIn("image-retry", titles)
        self.assertIn("image-failed", titles)
        self.assertNotIn("image-usage", titles)
        self.assertNotIn("image-fallback", titles)

    def test_mask_pixels_stay_byte_for_byte(self) -> None:
        fg = Image.new("RGB", (160, 80), (10, 20, 30))
        mask = Image.new("L", (160, 80), 0)
        for y in range(8, 72):
            for x in range(8, 152):
                mask.putpixel((x, y), 255)
                fg.putpixel((x, y), (10, 20, 30))
        bg = Image.new("RGB", (200, 200), (255, 0, 0))
        placed, origin, scaled, cut = image_provider_service._paste(
            fg, mask, bg, (200, 200), subject="leather bag"
        )
        self.assertTrue(image_provider_service.masked_pixels_match(placed, scaled, cut, origin))
        self.assertGreater(scaled.width, int(200 * 0.60) - 2)
        self.assertLess(scaled.width, int(200 * 0.70) + 2)
        center_y = origin[1] + scaled.height / 2
        self.assertGreater(center_y, 200 * 0.55)
        self.assertLess(center_y, 200 * 0.60)
        self.assertTrue(image_provider_service._inside_frame(origin, scaled.size, (200, 200)))
        backdrop = image_provider_service._background_prompt("light oak table and a stool")
        self.assertIn("oak", backdrop)
        self.assertIn("upper left", backdrop)
        self.assertIn("no furniture", backdrop)
        self.assertNotIn("stool", backdrop.split("no objects")[0])
        flat = image_provider_service._background_prompt("pale marble", view="top")
        self.assertIn("flat lay", flat)
        self.assertIn("no perspective", flat)
        self.assertIn("necklace", image_provider_service._guard_question("turquoise necklace").lower())
        self.assertIn("bracelet", image_provider_service._guard_question("turquoise necklace").lower())
        self.assertNotIn("empty", image_provider_service._guard_question("shop window").lower())
        tiny = Image.new("RGB", (40, 20), (4, 5, 6))
        tiny_mask = Image.new("L", (40, 20), 255)
        _small, _origin, small_fg, _small_cut = image_provider_service._paste(
            tiny, tiny_mask, bg, (200, 200), subject="leather bag"
        )
        self.assertLessEqual(small_fg.width, int(40 * image_provider_service.MAX_ENLARGE) + 1)
        padded = Image.new("RGB", (100, 80), (1, 1, 1))
        holes = Image.new("L", (100, 80), 0)
        for y in range(10, 70):
            for x in range(20, 80):
                holes.putpixel((x, y), 255)
                padded.putpixel((x, y), (9, 8, 7))
        low, low_origin, low_fg, low_cut = image_provider_service._paste(
            padded, holes, Image.new("RGB", (200, 300), (220, 220, 220)), (200, 300), subject="leather wallet"
        )
        self.assertTrue(image_provider_service.masked_pixels_match(low, low_fg, low_cut, low_origin))
        self.assertLess(low_fg.width, int(200 * 0.45) + 2)
        foot = low_origin[1] + low_fg.height
        shadow = low.getpixel((low_origin[0] + low_fg.width // 2, min(299, foot + 2)))
        self.assertLess(shadow[0], 200)
        side = low.getpixel((max(0, low_origin[0] - 8), min(299, foot + 2)))
        self.assertGreater(side[0], 200)


if __name__ == "__main__":
    unittest.main()
