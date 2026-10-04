from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFilter

from app.services import proxy_health
from app.services.observe_client import emit_later, observe_base

log = logging.getLogger("sozan.image")

FAIL_TEXT = "ساخت تصویر الان ممکن نیست، چند دقیقهٔ دیگر دوباره بگو"
SUBJECT_FAIL = "تصویر با کالای درخواستی جور نشد، دوباره بگو"
BUDGET_FAIL = "سقف هزینهٔ هوش مصنوعی امروز پر شده؛ ساخت تصویر فردا دوباره باز می‌شود"
DEFAULT_STILL = (
    "cinematic product still life on a clean studio surface, soft directional light, "
    "empty shop, no people, no text, no logos"
)
DATA_URI = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
_BLOCKED = {"http-401", "http-402", "http-403"}
_FURNITURE = re.compile(r"\b(table|stool|chair|furniture|desk|bench)\b", re.I)
DEFAULT_MODEL = "black-forest-labs/flux.2-klein-4b"
DEFAULT_EDIT_MODEL = "bytedance-seed/seedream-4.5"
DEFAULT_FALLBACK_MODEL = "Gemini-3.1-Flash-Image-Preview"
POST_SIZE = (1080, 1080)
PORTRAIT_POST_SIZE = (1080, 1350)
STORY_SIZE = (1080, 1920)
HARD_EDIT_MARKS = ("ویرایش عکس", "عکس را ویرایش", "همین عکس را")
DEFAULT_CUTOUT = "isnet-general-use"
MAX_CUTOUT_SIDE = 1024
GUARD_MODEL = "deepseek/deepseek-v4.1-flash"
MAX_ENLARGE = 1.25
KLEIN_TIMEOUT = 60.0
ARVAN_IMAGE_TIMEOUT = 95.0
_CUTOUT = None
last_error = ""
last_closeup = False


class ImageHttpError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"http-{code}")


def snap_size(width: int, height: int) -> tuple[int, int]:
    if int(height) > int(width):
        # 4:5 پست اینستاگرام است؛ فقط نسبت‌های باریک‌تر از 7:5 استوری می‌شوند.
        return STORY_SIZE if int(height) * 5 >= int(width) * 7 else PORTRAIT_POST_SIZE
    return POST_SIZE


def is_hard_edit(text: str) -> bool:
    spoken = text or ""
    return any(mark in spoken for mark in HARD_EDIT_MARKS)


def model_for(*, edit: bool, plan: str) -> str:
    if edit and (plan or "").strip().lower() in {"promax", "ultra"}:
        return (os.environ.get("IMAGE_OR_EDIT_MODEL") or DEFAULT_EDIT_MODEL).strip()
    return (os.environ.get("IMAGE_OR_MODEL") or DEFAULT_MODEL).strip()


def generate_still(
    prompt: str,
    *,
    width: int = 1080,
    height: int = 1080,
    edit: bool = False,
    plan: str = "",
    source: bytes | None = None,
    force_primary_error: bool = False,
    force_both_errors: bool = False,
    subject: str = "",
    edit_kind: str = "",
) -> bytes:
    return generate_image(
        prompt,
        width=width,
        height=height,
        edit=edit,
        plan=plan,
        source=source,
        force_primary_error=force_primary_error,
        force_both_errors=force_both_errors,
        subject=subject,
        edit_kind=edit_kind,
    ).get("png") or b""


def generate_image(
    prompt: str,
    *,
    width: int = 1080,
    height: int = 1080,
    edit: bool = False,
    plan: str = "",
    source: bytes | None = None,
    force_primary_error: bool = False,
    force_both_errors: bool = False,
    subject: str = "",
    edit_kind: str = "",
) -> dict:
    global last_error, last_closeup
    last_error = ""
    last_closeup = False
    size = snap_size(width, height)
    text = (prompt or "").strip()
    raw = source or b""
    if not text and not raw:
        return _empty()
    plan_id = _plan(plan)
    kind = (edit_kind or "").strip().lower()
    scene = bool(raw) and (kind == "scene" or (bool(edit) and kind != "background"))
    if kind == "background":
        scene = False
    if scene and plan_id not in {"promax", "ultra"}:
        _emit_failed("plan", DEFAULT_EDIT_MODEL)
        return _finish(_failed())
    chosen = model_for(edit=scene, plan=plan_id)
    capped = _image_budget_capped()
    if capped:
        # Images are the most expensive cloud call; the same tenant/company cap as text applies.
        _emit_failed(f"budget-{capped}", chosen)
        out = _failed()
        out["message"] = BUDGET_FAIL
        last_error = "budget"
        return _finish(out)

    def once(prompt_text: str) -> dict:
        if raw and not scene:
            return _product_still(
                raw,
                prompt_text or "soft studio surface",
                size,
                chosen,
                subject=subject,
                force_primary_error=force_primary_error,
                force_both_errors=force_both_errors,
            )
        result = _cloud_chain(
            prompt_text or DEFAULT_STILL,
            size,
            chosen,
            raw if scene else b"",
            force_primary_error=force_primary_error,
            force_both_errors=force_both_errors,
        )
        if not result.get("png") and _local_allowed() and not force_both_errors:
            local = _observe_local(prompt_text or DEFAULT_STILL, width=size[0], height=size[1])
            if len(local) >= 2048:
                result = {
                    "png": local,
                    "model": "local",
                    "provider": "local",
                    "cost": None,
                    "fallback": False,
                    "preserved": False,
                    "charged": False,
                    "failed": False,
                }
        return result

    result = once(text)
    if scene and raw and result.get("png"):
        result = _same_product_guard(raw, result, lambda: once(text))
    result = _apply_guard(result, subject, lambda: once(f"{text}. one clear product only, no unrelated object"))
    return _finish(result)


def composite_product(foreground: Image.Image, background: Image.Image, mask: Image.Image) -> Image.Image:
    placed, _origin, _fg, _mask = _paste(foreground, mask, background, foreground.size)
    return placed


def masked_pixels_match(image: Image.Image, foreground: Image.Image, mask: Image.Image, origin: tuple[int, int]) -> bool:
    fg = foreground.convert("RGB")
    cut = mask.convert("L")
    if cut.size != fg.size:
        return False
    out = image.convert("RGB")
    x0, y0 = origin
    seen = 0
    for y in range(fg.height):
        for x in range(fg.width):
            if cut.getpixel((x, y)) != 255:
                continue
            seen += 1
            if out.getpixel((x0 + x, y0 + y)) != fg.getpixel((x, y)):
                return False
    return seen > 0


def _product_still(
    source: bytes,
    prompt: str,
    size: tuple[int, int],
    model: str,
    subject: str = "",
    force_primary_error: bool = False,
    force_both_errors: bool = False,
) -> dict:
    try:
        foreground, mask = _cutout_with_fallback(source)
    except Exception as exc:
        log.warning("image cutout failed: %s: %s", type(exc).__name__, str(exc)[:120])
        emit_later(
            kind="routing",
            title="cutout-unavailable",
            surface="image",
            status="error",
            payload={"reason": str(exc)[:80]},
        )
        return _failed()
    product_width = _opaque_width(mask)
    view = _ask_view(source)
    background = _cloud_chain(
        _background_prompt(prompt, view),
        size,
        model,
        b"",
        force_primary_error=force_primary_error,
        force_both_errors=force_both_errors,
    )
    if not background.get("png"):
        return background
    try:
        scene = Image.open(BytesIO(background["png"])).convert("RGB")
        placed, origin, fg, cut = _paste(
            foreground, mask, scene, size, subject=subject, prompt=prompt, view=view
        )
    except Exception as exc:
        log.warning("image composite failed: %s", type(exc).__name__)
        return _failed()
    if not masked_pixels_match(placed, fg, cut, origin):
        log.warning("image composite changed product pixels")
        return _failed()
    buf = BytesIO()
    placed.save(buf, "PNG")
    png = buf.getvalue()
    return {
        "png": png,
        "model": background.get("model") or model,
        "provider": background.get("provider") or "",
        "cost": background.get("cost"),
        "fallback": bool(background.get("fallback")),
        "preserved": True,
        "retried": bool(background.get("retried")),
        "view": view,
        "closeup": product_width < 300,
        "failed": False,
        "charged": False,
    }


def _opaque_width(mask: Image.Image) -> int:
    box = mask.point(lambda value: 255 if value > 127 else 0).getbbox()
    if not box:
        return 0
    return int(box[2] - box[0])


async def _cloud_cutout(data: bytes) -> tuple[Image.Image, Image.Image] | None:
    """برش ابری اگر کلید باشد؛ خروجی PNG با آلفا → ماسک L. خطا None."""
    from app.services import cloud_cutout_service

    if not cloud_cutout_service.cloud_enabled():
        return None
    proxy = (os.environ.get("CHANNEL_PROXY") or "").strip() or None
    cut, cost = await cloud_cutout_service.remove_background(data, proxy=proxy)
    try:
        record = Image.open(BytesIO(cut)).convert("RGBA")
        alpha = record.split()[-1]
        original = Image.open(BytesIO(data)).convert("RGB")
        if alpha.size != original.size:
            alpha = alpha.resize(original.size, Image.Resampling.LANCZOS)
        mask = alpha
        # هزینه در دفتر ابر
        from app.services import ai_budget_service

        ai_budget_service.record_cost(surface="image", usd=cost)
        return original, mask
    except Exception as exc:
        log.warning("cloud cutout parse failed: %s", type(exc).__name__)
        return None


def _cutout_with_fallback(data: bytes) -> tuple[Image.Image, Image.Image]:
    """ابر اول؛ محلی فقط پشت فلگ dev (IMAGE_LOCAL=1) — همان الگوی ساخت عکس.

    sync است چون generate_image از to_thread صدا زده می‌شود.
    """
    if cloud_cutout_enabled():
        _cutout_slot()
        _cutout_slot_enter()
        try:
            cloud = asyncio.run(_cloud_cutout(data))
        except Exception as exc:
            log.warning("cloud cutout failed: %s: %s", type(exc).__name__, str(exc)[:120])
            cloud = None
        finally:
            _cutout_slot_exit()
        if cloud is not None:
            return cloud
    if os.environ.get("IMAGE_LOCAL") == "1":
        return _cutout(data)
    raise RuntimeError("cutout-unavailable: cloud key missing or failed and local engine is dev-only")


def cloud_cutout_enabled() -> bool:
    from app.services import cloud_cutout_service

    return cloud_cutout_service.cloud_enabled()


_CUTOUT_ACTIVE = 0


def _cutout_slot() -> None:
    """بیش از N برش همزمان ← پیام صادقانه؛ هاب زیر بار واقعی نفس می‌کشد."""
    global _CUTOUT_ACTIVE
    limit = int(os.environ.get("CUTOUT_QUEUE_LIMIT") or 3)
    if _CUTOUT_ACTIVE >= limit:
        from app.services.observe_client import emit_later

        emit_later(
            kind="routing",
            title="cutout-queue-full",
            surface="image",
            status="error",
            payload={"active": _CUTOUT_ACTIVE, "limit": limit},
        )
        raise RuntimeError("cutout-busy")


def _cutout_slot_enter() -> None:
    global _CUTOUT_ACTIVE
    _CUTOUT_ACTIVE += 1


def _cutout_slot_exit() -> None:
    global _CUTOUT_ACTIVE
    _CUTOUT_ACTIVE = max(0, _CUTOUT_ACTIVE - 1)


def _cutout(data: bytes) -> tuple[Image.Image, Image.Image]:
    original = Image.open(BytesIO(data)).convert("RGB")
    mask = _cutout_pass(original)
    box = mask.point(lambda value: 255 if value > 127 else 0).getbbox()
    if box:
        width = box[2] - box[0]
        height = box[3] - box[1]
        small = width < original.width * 0.45 or height < original.height * 0.45
        if small and width >= 8 and height >= 8:
            pad_x = max(1, int(width * 0.10))
            pad_y = max(1, int(height * 0.10))
            left = max(0, box[0] - pad_x)
            top = max(0, box[1] - pad_y)
            right = min(original.width, box[2] + pad_x)
            bottom = min(original.height, box[3] + pad_y)
            crop = original.crop((left, top, right, bottom))
            crop_mask = _cutout_pass(crop)
            mask = Image.new("L", original.size, 0)
            mask.paste(crop_mask, (left, top))
    return original, mask


def _cutout_pass(image: Image.Image) -> Image.Image:
    work = image
    long_side = max(work.size)
    if long_side > MAX_CUTOUT_SIDE:
        scale = MAX_CUTOUT_SIDE / long_side
        work = work.resize(
            (max(1, int(work.width * scale)), max(1, int(work.height * scale))),
            Image.Resampling.LANCZOS,
        )
    payload = BytesIO()
    work.save(payload, "PNG")
    from rembg import new_session, remove

    os.environ.setdefault("OMP_NUM_THREADS", "2")
    model = (os.environ.get("IMAGE_CUTOUT_MODEL") or DEFAULT_CUTOUT).strip()
    session = new_session(model)
    try:
        cut = remove(payload.getvalue(), session=session, alpha_matting=False)
    finally:
        _release_cutout(session)
    rgba = Image.open(BytesIO(cut)).convert("RGBA")
    alpha = rgba.split()[-1]
    if alpha.size != image.size:
        alpha = alpha.resize(image.size, Image.Resampling.LANCZOS)
    return _soften_alpha(alpha)


def _soften_alpha(mask: Image.Image) -> Image.Image:
    eroded = mask.filter(ImageFilter.MinFilter(3))
    blurred = eroded.filter(ImageFilter.GaussianBlur(radius=1))
    # The core stays fully opaque so product pixels remain the original bytes.
    # The 1px blur is only the edge that erosion opened.
    solid = eroded.point(lambda value: 255 if value >= 200 else 0)
    core = eroded.point(lambda value: 255 if value >= 200 else 0)
    return Image.composite(core, blurred, solid)


def _release_cutout(session: object) -> None:
    global _CUTOUT
    _CUTOUT = None
    try:
        from rembg.session_factory import sessions

        if isinstance(sessions, dict):
            sessions.clear()
    except Exception:
        pass
    del session
    import gc

    gc.collect()


def _width_fraction(subject: str, prompt: str = "") -> float:
    blob = f"{subject or ''} {prompt or ''}".lower()
    if "wallet" in blob or "کیف پول" in blob:
        return 0.40
    large = ("bag", "handbag", "shoe", "boot", "dress", "shirt", "jacket", "clothing", "coat", "کیف", "کفش", "لباس", "پیراهن", "مانتو")
    if any(mark in blob for mark in large):
        return 0.65
    return 0.40


def _paste(
    foreground: Image.Image,
    mask: Image.Image,
    background: Image.Image,
    size: tuple[int, int],
    subject: str = "",
    prompt: str = "",
    view: str = "angle",
) -> tuple[Image.Image, tuple[int, int], Image.Image, Image.Image]:
    fg = foreground.convert("RGB")
    cut = mask.convert("L")
    if cut.size != fg.size:
        cut = cut.resize(fg.size, Image.Resampling.LANCZOS)
    fg, cut = _trim_mask(fg, cut)
    scene = background.convert("RGB")
    if scene.size != size:
        scene = scene.resize(size, Image.Resampling.LANCZOS)
    fraction = _width_fraction(subject, prompt)
    fg, cut = _scale_product(fg, cut, size, fraction)
    origin = _origin_for(fg.size, size)
    for _ in range(4):
        if _inside_frame(origin, fg.size, size):
            break
        fg, cut = _scale_product(fg, cut, size, fraction * 0.85)
        fraction *= 0.85
        origin = _origin_for(fg.size, size)
    scene = _contact_shadow(scene, origin, cut, view=view)
    scene.paste(fg, origin, cut)
    return scene, origin, fg, cut


def _scale_product(
    foreground: Image.Image,
    mask: Image.Image,
    size: tuple[int, int],
    fraction: float,
) -> tuple[Image.Image, Image.Image]:
    canvas_w, canvas_h = size
    target_w = max(1, int(canvas_w * fraction))
    target_w = min(target_w, int(canvas_w * 0.92))
    max_h = max(1, int(canvas_h * 0.60))
    scale = target_w / max(foreground.width, 1)
    if int(foreground.height * scale) > max_h:
        scale = max_h / max(foreground.height, 1)
    if scale > MAX_ENLARGE:
        scale = MAX_ENLARGE
    resized = (max(1, int(foreground.width * scale)), max(1, int(foreground.height * scale)))
    if resized == foreground.size:
        return foreground, mask
    fg = foreground.resize(resized, Image.Resampling.LANCZOS)
    cut = mask.resize(resized, Image.Resampling.LANCZOS)
    return fg, cut


def _origin_for(fg_size: tuple[int, int], canvas: tuple[int, int]) -> tuple[int, int]:
    width, height = fg_size
    canvas_w, canvas_h = canvas
    center_y = int(canvas_h * 0.575)
    origin_y = center_y - height // 2
    min_y = int(canvas_h * 0.08)
    max_y = int(canvas_h * 0.88) - height
    if max_y < min_y:
        origin_y = max(0, max_y)
    else:
        origin_y = min(max(origin_y, min_y), max_y)
    origin_x = (canvas_w - width) // 2
    min_x = int(canvas_w * 0.04)
    max_x = canvas_w - width - min_x
    if max_x < min_x:
        origin_x = max(0, (canvas_w - width) // 2)
    else:
        origin_x = min(max(origin_x, min_x), max_x)
    return origin_x, origin_y


def _inside_frame(origin: tuple[int, int], fg_size: tuple[int, int], canvas: tuple[int, int]) -> bool:
    x, y = origin
    width, height = fg_size
    canvas_w, canvas_h = canvas
    if x < int(canvas_w * 0.04) or y < int(canvas_h * 0.08):
        return False
    if x + width > canvas_w - int(canvas_w * 0.04):
        return False
    if y + height > int(canvas_h * 0.88):
        return False
    return width > 0 and height > 0


def _trim_mask(foreground: Image.Image, mask: Image.Image) -> tuple[Image.Image, Image.Image]:
    box = mask.point(lambda value: 255 if value > 16 else 0).getbbox()
    if not box:
        return foreground, mask
    pad = 2
    left = max(0, box[0] - pad)
    top = max(0, box[1] - pad)
    right = min(foreground.width, box[2] + pad)
    bottom = min(foreground.height, box[3] + pad)
    return foreground.crop((left, top, right, bottom)), mask.crop((left, top, right, bottom))


def _contact_shadow(
    scene: Image.Image,
    origin: tuple[int, int],
    mask: Image.Image,
    view: str = "angle",
) -> Image.Image:
    if view == "top":
        return _silhouette_shadow(scene, origin, mask)
    return _contour_shadow(scene, origin, mask)


def _contour_shadow(scene: Image.Image, origin: tuple[int, int], mask: Image.Image) -> Image.Image:
    alpha = mask.convert("L")
    source = alpha.load()
    contact: list[tuple[int, int]] = []
    for x in range(alpha.width):
        for y in range(alpha.height - 1, -1, -1):
            if source[x, y] > 127:
                contact.append((x, y))
                break
    if not contact:
        return scene
    x0, y0 = origin
    layer = Image.new("L", scene.size, 0)
    paint = layer.load()
    for x, y in contact:
        sx = x0 + x
        sy = y0 + y
        for dy in range(0, 7):
            yy = sy + dy
            if 0 <= sx < scene.size[0] and 0 <= yy < scene.size[1]:
                paint[sx, yy] = max(paint[sx, yy], int(180 * (1 - dy / 7)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.5))
    dark = Image.new("RGB", scene.size, (28, 26, 24))
    return Image.composite(dark, scene, layer)


def _silhouette_shadow(scene: Image.Image, origin: tuple[int, int], mask: Image.Image) -> Image.Image:
    canvas_w, canvas_h = scene.size
    shift_x = max(2, int(canvas_w * 0.015))
    shift_y = max(2, int(canvas_h * 0.015))
    layer = Image.new("L", scene.size, 0)
    shifted = mask.point(lambda value: int(value * 0.25))
    layer.paste(shifted, (origin[0] + shift_x, origin[1] + shift_y))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=max(4, int(canvas_w * 0.012))))
    dark = Image.new("RGB", scene.size, (28, 26, 24))
    return Image.composite(dark, scene, layer)


def _ellipse_shadow(
    scene: Image.Image,
    dark: Image.Image,
    spec: tuple[int, int, int, int],
    *,
    peak: int,
    blur: int,
) -> Image.Image:
    cx, cy, width, height = spec
    shade = Image.new("L", scene.size, 0)
    box = (cx - width // 2, cy - height // 2, cx + width // 2, cy + height // 2)
    ImageDraw.Draw(shade).ellipse(box, fill=255)
    shade = shade.filter(ImageFilter.GaussianBlur(radius=blur))
    hi = shade.getextrema()[1] or 1
    if hi != peak:
        shade = shade.point(lambda value, hi=hi, peak=peak: min(255, int(value * peak / hi)))
    return Image.composite(dark, scene, shade)


def _background_prompt(prompt: str, view: str = "angle") -> str:
    hint = _FURNITURE.sub(" ", prompt or "")
    hint = re.sub(r"\s+", " ", hint).strip(" ,.")
    material = hint or "pale linen with a soft weave"
    if view == "top":
        camera = "seen from directly above, flat lay, no perspective"
    elif view == "front":
        camera = "straight-on front view, soft light from the upper left"
    else:
        camera = "mild overhead angle, gentle perspective only, soft light from the upper left"
    return (
        f"{material}. {camera}. one continuous textured surface filling the whole frame, "
        "visible gentle grain, "
        "no objects, no product, no furniture, no table, no stool, no hands, no text, no logos, no people"
    )


def _is_klein(model: str) -> bool:
    return "klein" in (model or "").lower()


def _fallback_mode() -> str:
    mode = (os.environ.get("IMAGE_FALLBACK") or "none").strip().lower()
    if mode in {"seedream", "arvan", "none"}:
        return mode
    return "none"


def _retry_pause() -> float:
    raw = os.environ.get("IMAGE_RETRY_PAUSE")
    if raw is None or not str(raw).strip():
        return 4.0
    try:
        value = float(raw)
    except ValueError:
        return 4.0
    if value <= 0:
        return 0.0
    return min(5.0, max(3.0, value))


def _cloud_chain(
    prompt: str,
    size: tuple[int, int],
    model: str,
    source: bytes,
    *,
    force_primary_error: bool = False,
    force_both_errors: bool = False,
) -> dict:
    primary_url = (os.environ.get("IMAGE_OR_URL") or "https://openrouter.ai/api/v1").strip()
    primary_token = _token_for(primary_url)
    if not primary_token:
        if _local_allowed() and not force_both_errors:
            local = _observe_local(prompt, width=size[0], height=size[1])
            if len(local) >= 2048:
                return {
                    "png": local,
                    "model": "local",
                    "provider": "local",
                    "cost": None,
                    "fallback": False,
                    "preserved": False,
                    "charged": False,
                    "failed": False,
                }
        _emit_failed("empty", model)
        return _failed()
    timeout = KLEIN_TIMEOUT if _is_klein(model) else 120.0
    if force_both_errors:
        _emit_retry("simulated", model)
        _pause()
        _emit_failed("simulated", model)
        return _failed()
    reason = "simulated" if force_primary_error else ""
    result: dict | None = None
    if not force_primary_error:
        result, reason = _attempt(primary_url, primary_token, model, prompt, size, source, timeout)
        if result:
            return result
    mode = _fallback_mode()
    # مسیر OpenRouter بسته است (403/401/402): تلاش دوباره روی همان مسیر بی‌فایده است، مستقیم به آروان.
    skip_retry = mode == "arvan" and reason in _BLOCKED
    if not skip_retry:
        _emit_retry(reason or "error", model)
        _pause()
        result, reason = _attempt(primary_url, primary_token, model, prompt, size, source, timeout)
        if result:
            result["retried"] = True
            return result
    if mode == "seedream" and "seedream" not in model.lower():
        seed_model = (os.environ.get("IMAGE_OR_EDIT_MODEL") or DEFAULT_EDIT_MODEL).strip()
        _emit_fallback(reason, model, seed_model)
        result, reason = _attempt(primary_url, primary_token, seed_model, prompt, size, source, 120.0)
        if result:
            result["fallback"] = True
            return result
    elif mode == "arvan":
        fallback_url = (os.environ.get("IMAGE_FALLBACK_URL") or os.environ.get("CLOUD_LLM_FALLBACK_URL") or "").strip()
        fallback_model = (os.environ.get("IMAGE_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODEL).strip()
        fallback_token = (
            os.environ.get("IMAGE_FALLBACK_TOKEN")
            or os.environ.get("CLOUD_LLM_FALLBACK_TOKEN")
            or os.environ.get("CLOUD_LLM_TOKEN")
            or ""
        ).strip()
        if fallback_url and fallback_token and fallback_url.rstrip("/") != primary_url.rstrip("/"):
            _emit_fallback(reason, model, fallback_model)
            result, reason = _attempt(
                fallback_url, fallback_token, fallback_model, prompt, size, source, ARVAN_IMAGE_TIMEOUT
            )
            if result:
                result["fallback"] = True
                return result
    _emit_failed(reason or "empty", model)
    return _failed()


def _pause() -> None:
    delay = _retry_pause()
    if delay > 0:
        time.sleep(delay)


def _attempt(
    url: str,
    token: str,
    model: str,
    prompt: str,
    size: tuple[int, int],
    source: bytes,
    timeout: float,
) -> tuple[dict | None, str]:
    try:
        payload = _complete(url, token, model, prompt, size, source, timeout)
    except ImageHttpError as exc:
        reason = "timeout" if exc.code == 0 else f"http-{exc.code}"
        log.warning("image cloud %s %s", model, reason)
        return None, reason
    except Exception as exc:
        reason = type(exc).__name__
        log.warning("image cloud failed: %s", reason)
        return None, reason
    png = _fit(_image_bytes(payload), size)
    if len(png) < 2048:
        return None, "empty"
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "png": png,
        "model": model,
        "provider": str(payload.get("provider") or ""),
        "cost": _cost(usage),
        "fallback": False,
        "preserved": False,
        "retried": False,
        "failed": False,
        "charged": False,
    }, ""


def _complete(
    url: str,
    token: str,
    model: str,
    prompt: str,
    size: tuple[int, int],
    source: bytes,
    timeout: float = 120.0,
) -> dict:
    body = _body(model, prompt, size, source)
    try:
        return _post(url, token, body, timeout=timeout)
    except ImageHttpError as exc:
        if exc.code == 400 and "image_config" in body:
            body.pop("image_config", None)
            return _post(url, token, body, timeout=timeout)
        raise


def _aspect_of(size: tuple[int, int]) -> str:
    width, height = int(size[0]), int(size[1])
    if height > width:
        return "9:16" if height * 5 >= width * 7 else "4:5"
    return "1:1"


def _body(model: str, prompt: str, size: tuple[int, int], source: bytes) -> dict:
    text = (prompt or DEFAULT_STILL)[:800]
    if source:
        encoded = base64.b64encode(source).decode("ascii")
        content: object = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            {"type": "text", "text": text},
        ]
    else:
        content = text
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image"],
        "image_config": {"aspect_ratio": _aspect_of(size)},
    }


def _post(url: str, token: str, body: dict, timeout: float = 120.0) -> dict:
    try:
        res = proxy_health.post_sync(
            f"{url.rstrip('/')}/chat/completions",
            proxy=_proxy_for(url),
            total=timeout,
            connect=8.0,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
    except httpx.TimeoutException as exc:
        raise ImageHttpError(0) from exc
    if res.status_code >= 400:
        raise ImageHttpError(res.status_code)
    data = res.json()
    if not isinstance(data, dict):
        raise ImageHttpError(0)
    return data


def _image_bytes(payload: dict) -> bytes:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    message = (choices[0] or {}).get("message") if choices and isinstance(choices[0], dict) else {}
    if not isinstance(message, dict):
        message = {}
    raw = ""
    images = message.get("images") if isinstance(message.get("images"), list) else []
    if images and isinstance(images[0], dict):
        image_url = images[0].get("image_url")
        raw = str(image_url.get("url") if isinstance(image_url, dict) else image_url or "")
    if not raw:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                image_url = part.get("image_url")
                raw = str(image_url.get("url") if isinstance(image_url, dict) else image_url or "")
                if raw:
                    break
        elif isinstance(content, str):
            # آروان تصویر را به‌صورت مارک‌داون برمی‌گرداند: ![image](data:image/jpeg;base64,...)
            found = DATA_URI.search(content)
            raw = found.group(0) if found else ""
    if not raw.startswith("data:") or "," not in raw:
        return b""
    try:
        blob = base64.b64decode(raw.split(",", 1)[1])
    except Exception:
        return b""
    return blob


def _fit(data: bytes, size: tuple[int, int]) -> bytes:
    if len(data) < 32:
        return b""
    try:
        img = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return data if len(data) >= 2048 else b""
    if img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _cost(usage: dict) -> float | None:
    try:
        return float(usage.get("cost"))
    except (TypeError, ValueError):
        return None


def _empty() -> dict:
    return {
        "png": b"",
        "model": "",
        "provider": "",
        "cost": None,
        "fallback": False,
        "preserved": False,
        "guard": None,
        "guard_cost": None,
        "charged": False,
        "failed": False,
        "message": "",
        "retried": False,
        "closeup": False,
        "view": "",
    }


def _failed() -> dict:
    global last_error
    last_error = "failed"
    out = _empty()
    out["failed"] = True
    out["message"] = FAIL_TEXT
    return out


def _finish(result: dict) -> dict:
    global last_closeup
    done = dict(result)
    last_closeup = bool(done.get("closeup"))
    if done.get("png"):
        done["failed"] = False
        done["message"] = ""
        if done.get("model") == "local":
            done["charged"] = False
            return done
        done["charged"] = True
        _emit_usage(
            model=str(done.get("model") or ""),
            provider=str(done.get("provider") or ""),
            cost=done.get("cost") if isinstance(done.get("cost"), float) else None,
            nbytes=len(done["png"]),
        )
        return done
    done["charged"] = False
    if done.get("failed") or last_error == "failed":
        done["failed"] = True
        done["message"] = done.get("message") or FAIL_TEXT
    elif last_error == "subject":
        done["message"] = SUBJECT_FAIL
        done["failed"] = True
    return done


def _add_cost(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


def _apply_guard(result: dict, subject: str, remake) -> dict:
    global last_error
    name = (subject or "").strip()
    if not name or not result.get("png"):
        return result
    ok, cost = _ask_subject(result["png"], name)
    if ok is not False:
        result = dict(result)
        result["guard"] = ok
        result["guard_cost"] = cost
        return result
    second = remake()
    second_ok, second_cost = (False, None)
    if second.get("png"):
        second_ok, second_cost = _ask_subject(second["png"], name)
    total = _add_cost(cost, second_cost)
    # Same rule as the first pass: only an explicit "no" rejects; an unreachable guard does not.
    if second.get("png") and second_ok is not False:
        second = dict(second)
        second["guard"] = second_ok
        second["guard_cost"] = total
        second["cost"] = _add_cost(result.get("cost"), second.get("cost"))
        return second
    _keep_rejected(result.get("png") or b"", name)
    _keep_rejected(second.get("png") or b"", name)
    last_error = "subject"
    rejected = _empty()
    rejected["guard"] = False
    rejected["guard_cost"] = total
    rejected["cost"] = _add_cost(result.get("cost"), second.get("cost"))
    return rejected


def _keep_rejected(png: bytes, subject: str) -> None:
    from pathlib import Path

    raw = (os.environ.get("IMAGE_BENCH_DIR") or "").strip()
    if not raw or len(png) < 2048:
        return
    dest = Path(raw)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    (dest / f"rejected-{stamp}.png").write_bytes(png)


def _guard_question(subject: str) -> str:
    name = (subject or "").strip()
    low = name.lower()
    if "necklace" in low or "گردنبند" in name:
        return "Is this a necklace (not a bracelet or ring)? فقط JSON با کلید yes که true یا false است."
    if "bracelet" in low or "دستبند" in name:
        return "Is this a bracelet (not a necklace or ring)? فقط JSON با کلید yes که true یا false است."
    if "ring" in low or "انگشتر" in name:
        return "Is this a ring (not a necklace or bracelet)? فقط JSON با کلید yes که true یا false است."
    if "pendant" in low or "آویز" in name:
        return "Is this a pendant (not a necklace, bracelet, or ring)? فقط JSON با کلید yes که true یا false است."
    return f"آیا این تصویر {name} را نشان می‌دهد؟ فقط JSON با کلید yes که true یا false است."


def _ask_subject(png: bytes, subject: str) -> tuple[bool | None, float | None]:
    payload, cost = _vision(png, _guard_question(subject))
    if not payload:
        return None, cost
    answer = _yes_answer(payload)
    if os.environ.get("IMAGE_BENCH_DIR"):
        print(json.dumps({"subject": subject, "yes": answer, "cost": cost}, ensure_ascii=False), flush=True)
    return answer, cost


def _ask_view(png: bytes) -> str:
    payload, _cost = _vision(
        png,
        (
            'Reply JSON only: {"ok": true, "view": "top" or "angle" or "front"}. '
            "view is the camera angle. top means the camera is above the product and the top face dominates, "
            "even if a thin edge is visible; do not call that angle. "
            "angle means a side wall of the product is clearly visible. "
            "front means the camera looks straight at the front."
        ),
    )
    data = _json_object(payload or {})
    view = str((data or {}).get("view") or "").strip().lower()
    if view in {"top", "angle", "front"}:
        return view
    return "angle"


def _ask_same(before: bytes, after: bytes) -> tuple[bool | None, float | None]:
    payload, cost = _vision(
        before,
        "آیا هر دو تصویر همان کالا را نشان می‌دهند؟ فرم، رنگ و جزئیات. فقط JSON با کلید yes که true یا false است.",
        after,
    )
    if not payload:
        return None, cost
    return _yes_answer(payload), cost


def _same_product_guard(source: bytes, result: dict, remake) -> dict:
    global last_error
    ok, cost = _ask_same(source, result.get("png") or b"")
    if ok is not False:
        kept = dict(result)
        kept["guard_cost"] = _add_cost(kept.get("guard_cost"), cost)
        return kept
    second = remake()
    second_ok, second_cost = (False, None)
    if second.get("png"):
        second_ok, second_cost = _ask_same(source, second["png"])
    total = _add_cost(cost, second_cost)
    # Same rule as the first pass: only an explicit "no" rejects; an unreachable guard does not.
    if second.get("png") and second_ok is not False:
        kept = dict(second)
        kept["guard_cost"] = _add_cost(kept.get("guard_cost"), total)
        kept["cost"] = _add_cost(result.get("cost"), second.get("cost"))
        return kept
    _keep_rejected(result.get("png") or b"", "same")
    _keep_rejected(second.get("png") or b"", "same")
    last_error = "subject"
    rejected = _empty()
    rejected["guard"] = False
    rejected["guard_cost"] = total
    rejected["cost"] = _add_cost(result.get("cost"), second.get("cost"))
    rejected["failed"] = True
    rejected["message"] = SUBJECT_FAIL
    return rejected


def _vision(png: bytes, question: str, extra: bytes = b"") -> tuple[dict | None, float | None]:
    url = (os.environ.get("IMAGE_OR_URL") or "https://openrouter.ai/api/v1").strip()
    token = _token_for(url)
    blobs = [blob for blob in (png, extra) if len(blob) >= 32]
    if not token or not blobs:
        return None, None
    model = (os.environ.get("STUDIO_CLOUD_MODEL") or GUARD_MODEL).strip()
    try:
        content: list[dict] = []
        for blob in blobs:
            preview = Image.open(BytesIO(blob)).convert("RGB")
            preview.thumbnail((768, 768))
            buf = BytesIO()
            preview.save(buf, "JPEG", quality=80)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
        content.append({"type": "text", "text": question})
        payload = _post(url, token, {"model": model, "messages": [{"role": "user", "content": content}]})
    except ImageHttpError as exc:
        log.warning("image vision failed: http-%s", exc.code)
        return None, None
    except Exception as exc:
        log.warning("image vision failed: %s", type(exc).__name__)
        return None, None
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return payload, _cost(usage)


def _json_object(payload: dict) -> dict | None:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    message = (choices[0] or {}).get("message") if choices and isinstance(choices[0], dict) else {}
    text = str(message.get("content") or "") if isinstance(message, dict) else ""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _yes_answer(payload: dict) -> bool | None:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    message = (choices[0] or {}).get("message") if choices and isinstance(choices[0], dict) else {}
    text = str(message.get("content") or "") if isinstance(message, dict) else ""
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "yes" in data:
            return bool(data["yes"])
    folded = text.strip().lower()
    if folded in {"true", "yes", "بله"}:
        return True
    if folded in {"false", "no", "خیر", "نه"}:
        return False
    return None


def _plan(explicit: str) -> str:
    cleaned = (explicit or "").strip().lower()
    if cleaned:
        return cleaned
    try:
        from app.services.plan_service import current_plan_id

        return current_plan_id()
    except Exception:
        return "free"


def _local_allowed() -> bool:
    return os.environ.get("IMAGE_LOCAL") == "1"


def _token_for(url: str) -> str:
    if "openrouter.ai" in (_host(url)):
        return os.environ.get("open_router_api_token", "").strip()
    return (os.environ.get("IMAGE_OR_TOKEN") or os.environ.get("CLOUD_LLM_TOKEN") or "").strip()


def _proxy_for(url: str) -> str | None:
    host = _host(url)
    if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return (os.environ.get("OPENROUTER_PROXY") or "").strip() or None
    if host.endswith("arvancloudai.ir"):
        return None
    fallback_host = _host(os.environ.get("CLOUD_LLM_FALLBACK_URL") or os.environ.get("IMAGE_FALLBACK_URL") or "")
    if host and host == fallback_host:
        # آروان از ایران مستقیم در دسترس است؛ پراکسی خارجی فقط کندش می‌کند.
        return None
    raw = (os.environ.get("CLOUD_LLM_PROXY") or os.environ.get("CHANNEL_PROXY") or "").strip()
    return raw or None


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _image_budget_capped() -> str | None:
    from app.services.llm import budget_capped

    return budget_capped("image")


def _emit_usage(*, model: str, provider: str, cost: float | None, nbytes: int) -> None:
    payload: dict = {"model": model, "provider": provider, "bytes": nbytes}
    if cost is not None:
        payload["cost"] = cost
    try:
        emit_later(kind="routing", surface="image", title="image-usage", status="ready", payload=payload)
    except Exception:
        log.warning("image usage emit failed")
    if cost is not None:
        try:
            from app.services import ai_budget_service

            ai_budget_service.record_cost(surface="image", usd=cost)
        except Exception:
            log.warning("ai-budget record failed", exc_info=True)


def _emit_retry(reason: str, model: str) -> None:
    try:
        emit_later(
            kind="routing",
            surface="image",
            title="image-retry",
            status="retry",
            payload={"reason": reason, "model": model},
        )
    except Exception:
        log.warning("image retry emit failed")


def _emit_failed(reason: str, model: str) -> None:
    try:
        emit_later(
            kind="routing",
            surface="image",
            title="image-failed",
            status="failed",
            payload={"reason": reason, "model": model},
        )
    except Exception:
        log.warning("image failed emit failed")


def _emit_fallback(reason: str, requested: str, used: str) -> None:
    try:
        emit_later(
            kind="routing",
            surface="image",
            title="image-fallback",
            status="fallback",
            payload={"reason": reason, "requested": requested, "used": used},
        )
    except Exception:
        log.warning("image fallback emit failed")


def _observe_local(prompt: str, *, width: int, height: int) -> bytes:
    url = f"{observe_base()}/observe/api/image"
    try:
        with httpx.Client(timeout=httpx.Timeout(420.0, connect=5.0), trust_env=False) as client:
            res = client.post(url, json={"prompt": prompt, "width": width, "height": height})
    except Exception as exc:
        log.warning("observe image failed: %s", type(exc).__name__)
        return b""
    if res.status_code != 200 or len(res.content) < 2048:
        return b""
    if "json" in (res.headers.get("content-type") or ""):
        return b""
    return res.content


async def probe_ollama_cloud_once() -> dict:
    from app.state_store import read_json, shared_lock, write_json

    try:
        with shared_lock():
            stored = read_json("image-probe.json", {}, shared=True)
            if isinstance(stored, dict) and stored.get("at"):
                return stored
        result = await asyncio.to_thread(probe_ollama_cloud)
        payload = {**result, "at": time.time()}
        with shared_lock():
            stored = read_json("image-probe.json", {}, shared=True)
            if isinstance(stored, dict) and stored.get("at"):
                return stored
            write_json("image-probe.json", payload, shared=True)
        emit_later(
            kind="routing",
            surface="image",
            title="image-probe",
            status="ready" if result.get("ok") else "failed",
            payload={"ok": bool(result.get("ok")), "status": result.get("status"), "error": result.get("error") or ""},
        )
        return payload
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("image probe failed: %s", type(exc).__name__)
        return {"ok": False, "error": type(exc).__name__}


def probe_ollama_cloud() -> dict:
    from app.config import settings

    token = (settings.cloud_llm_token or os.environ.get("OLLAMA_API_KEY") or "").strip()
    if not token:
        return {"ok": False, "error": "no-token"}
    proxy = (settings.cloud_llm_proxy or settings.channel_proxy or "").strip() or None
    url = "https://ollama.com/v1/images/generations"
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), trust_env=False, proxy=proxy) as client:
            res = client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "model": "x/z-image-turbo",
                    "prompt": "a white ceramic mug on a wooden table, no text",
                    "size": "512x512",
                    "response_format": "b64_json",
                },
            )
        return {
            "ok": res.status_code < 400 and "b64_json" in (res.text or ""),
            "status": res.status_code,
            "detail": (res.text or "")[:240],
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
