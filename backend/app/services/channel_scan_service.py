from __future__ import annotations

import json
import re
import subprocess
import tempfile
import threading
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from app.config import settings
from app.services import storefront_service, voice_service
from app.services.channel_http import async_client, channel_proxy
from app.services.llm import complete_json
from app.services.observe_client import emit_later
from app.services.settings_service import get_settings
from app.state_store import current_tenant, read_json, tenant_dir, write_json

USER_AGENT = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36"
IG_APP_UA = "Instagram 192.168.2.4.75 Android (33/13; 420dpi; 1080x2400; Google; Pixel 7; panther; panther; en_US; 458229237)"
META = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:(title|description|image)["\'][^>]+content=["\']([^"\']+)',
    re.I,
)
META_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:(title|description|image)["\']',
    re.I,
)
IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.I)
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
ITEM_WORD = re.compile(r"(کیف(?!یت)|کفش|صندل|کوله|زعفران|ادویه|عسل|چای)")
FA_DIGIT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DIRECT_PRICE = re.compile(r"قیمت\s*=\s*دایرکت|قیمت\s*دایرکت|دایرکت\s*بد")
GROUPED_PRICE = re.compile(r"\b(\d{1,3}(?:[./،,]\d{3}){1,3})\b")
LEADING_ZERO_PRICE = re.compile(r"\b0+[./](\d{1,3})[./](\d{3})\b")
THOUSAND_PRICE = re.compile(r"\b(\d{1,3})[./](\d{3})\s*(?:هزار|هزلر)")
STYLE_WORDS = ("مجلسی", "دوشی", "دستی", "دانشجویی", "زنانه", "مردانه", "دخترانه", "خرگوش", "لژدار", "پاییزه")
MATERIALS = ("چرم", "ساتن", "جیر", "مروارید")
COLOR_WORDS = ("قهوه‌ای", "قهوه ای", "کرم", "سفید", "مشکی", "طلایی", "عسلی", "نخی", "صورتی")
CAPTION_MAX = 400
# complete_json() error markers that mean "the model failed", not "the page was empty".
LLM_ERRORS = frozenset({"llm_unreachable", "llm_bad_json"})
SCAN_MODEL_ERROR = "llm_unreachable"
SCAN_MODEL_ERROR_FA = "مدل هوش مصنوعی در دسترس نبود؛ چند لحظه بعد دوباره اسکن کن."


def _category_from_text(text: str) -> str:
    match = ITEM_WORD.search(text or "")
    return match.group(0) if match else ""


def parse_caption_price(text: str) -> tuple[int, str]:
    raw = SPACE.sub(" ", (text or "").translate(FA_DIGIT)).strip()
    if not raw:
        return 0, ""
    if DIRECT_PRICE.search(raw):
        return 0, "دایرکت"
    zero = LEADING_ZERO_PRICE.search(raw)
    if zero:
        return int(zero.group(1) + zero.group(2)) * 1000, ""
    grouped = GROUPED_PRICE.search(raw)
    if grouped:
        digits = re.sub(r"\D", "", grouped.group(1))
        if digits:
            value = int(digits)
            tail = raw[grouped.end() : grouped.end() + 16]
            if re.search(r"هزار|هزلر", tail):
                value *= 1000
            return value, ""
    thousand = THOUSAND_PRICE.search(raw)
    if thousand:
        return int(thousand.group(1) + thousand.group(2)) * 1000, ""
    return 0, ""


def parse_caption_colors(text: str) -> list[str]:
    found: list[str] = []
    blob = text or ""
    for name in COLOR_WORDS:
        if name not in blob:
            continue
        label = "قهوه‌ای" if name.startswith("قهوه") else name
        if label not in found:
            found.append(label)
    return found[:6]


def parse_caption_sizes(text: str) -> str:
    blob = text or ""
    if "دو سایز" in blob or "دوسایز" in blob:
        return "دو سایز"
    if "سایز بندی" in blob or "سایزبندی" in blob or "دارای سایز" in blob:
        return "سایزبندی"
    return ""


def site_type_hint() -> str:
    scan = get_scan()
    cats = [str(item).strip() for item in (scan.get("categories") or []) if str(item).strip()]
    if not cats:
        products = storefront_service.list_products().get("products") or []
        cats = list(
            dict.fromkeys(str(row.get("category") or "").strip() for row in products if str(row.get("category") or "").strip())
        )
    blob = " ".join(cats)
    if "کیف" in blob and "کفش" not in blob and "صندل" not in blob:
        return "bags"
    if ("کفش" in blob or "صندل" in blob) and "کیف" not in blob:
        return "shoes"
    if "کیف" in blob and ("کفش" in blob or "صندل" in blob):
        return "bags-and-shoes"
    if any(token in blob for token in ("زعفران", "ادویه", "هل", "زرشک")):
        return "saffron-spice"
    if any(token in blob for token in ("جواهر", "طلا", "الماس", "زیورآلات", "اکسسوری", "بدلیجات")):
        return "jewelry"
    if any(token in blob for token in ("چای", "دمنوش")):
        return "tea"
    if "عسل" in blob:
        return "honey"
    return "general-store" if cats else "store"


def _parse_categories(parsed: dict, products: list[dict]) -> list[str]:
    out: list[str] = []
    for item in parsed.get("categories") or []:
        text = str(item).strip()[:40]
        if text and text not in out:
            out.append(text)
    for row in products:
        text = str(row.get("category") or "").strip()[:40]
        if text and text not in out:
            out.append(text)
    return out[:12]


def _unattributed_dir() -> Path:
    path = settings.state_path / "scan-images" / "_unattributed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quarantine_shared_scan_images() -> None:
    shared = settings.state_path / "scan-images"
    if not shared.is_dir():
        return
    dest = _unattributed_dir()
    for path in shared.iterdir():
        if path.name.startswith("_") or path.is_dir():
            continue
        target = dest / path.name
        if target.exists():
            continue
        try:
            path.replace(target)
        except OSError:
            continue


def _scan_dir() -> Path:
    _quarantine_shared_scan_images()
    path = tenant_dir() / "scan-images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_scan() -> dict:
    data = read_json("channel-scan.json", {})
    return data if isinstance(data, dict) else {}


def scan_status() -> dict:
    data = read_json("scan-status.json", {})
    if not isinstance(data, dict):
        data = {}
    status = str(data.get("status") or "idle")
    if status not in {"idle", "running", "done", "error"}:
        status = "idle"
    return {
        "status": status,
        "productCount": int(data.get("productCount") or 0),
        "error": str(data.get("error") or ""),
        "handles": [str(item) for item in (data.get("handles") or []) if str(item).strip()],
        "needsReview": bool(data.get("needsReview")),
        "errorClass": str(data.get("errorClass") or ""),
        "imported": int(data.get("imported") or data.get("productCount") or 0),
        "kept": int(data.get("kept") or 0),
        "noImage": int(data.get("noImage") or 0),
        "noPrice": int(data.get("noPrice") or 0),
        "rejected": int(data.get("rejected") or 0),
    }


def _set_scan_status(*, status: str, product_count: int = 0, error: str = "", handles: list | None = None, extra: dict | None = None) -> dict:
    payload = {
        "status": status,
        "productCount": int(product_count or 0),
        "error": error,
        "handles": handles or [],
    }
    if extra:
        payload.update(extra)
    write_json("scan-status.json", payload)
    return payload


def start_scan(accounts: list[dict]) -> dict:
    import asyncio

    from app.state_store import current_tenant, tenant_scope

    handles = [str(item.get("handle") or "") for item in accounts if item.get("handle")]
    before = scan_status()
    _set_scan_status(status="running", handles=handles)
    phone = current_tenant()
    copied = [dict(item) for item in accounts]

    async def job() -> None:
        with tenant_scope(phone):
            try:
                out = await scan_accounts(copied)
                if str(out.get("error") or "") == SCAN_MODEL_ERROR:
                    _set_scan_status(
                        status="error",
                        product_count=int(before.get("productCount") or 0),
                        error=SCAN_MODEL_ERROR_FA,
                        handles=handles,
                        extra={
                            "errorClass": SCAN_MODEL_ERROR,
                            "needsReview": False,
                            "imported": int(before.get("imported") or 0),
                            "noImage": int(before.get("noImage") or 0),
                            "noPrice": int(before.get("noPrice") or 0),
                            "rejected": 0,
                        },
                    )
                    emit_later(
                        kind="scan",
                        surface="scan",
                        title="scan-error",
                        status="failed",
                        payload={"handles": handles, "errorClass": SCAN_MODEL_ERROR},
                    )
                    return
                count = int(out.get("productCount") or 0)
                quality = out.get("quality") if isinstance(out.get("quality"), dict) else {}
                imported = int(quality.get("imported") or 0)
                with_image = int(quality.get("withImage") or 0)
                _set_scan_status(
                    status="done",
                    product_count=count,
                    handles=handles,
                    extra={
                        "needsReview": bool(out.get("needsReview")),
                        "imported": imported,
                        "kept": int(quality.get("kept") or 0),
                        "noImage": max(0, imported - with_image),
                        "noPrice": int(quality.get("noPrice") or 0),
                        "rejected": int(quality.get("rejectedAccounts") or 0),
                    },
                )
                emit_later(
                    kind="scan",
                    surface="scan",
                    title="scan-done",
                    payload={"productCount": count, "handles": handles},
                )
                if count:
                    from app.services import shop_service

                    shop_service.rebuild_from_channel_catalog()
            except Exception:
                _set_scan_status(status="error", error="اسکن کانال کامل نشد", handles=handles)
                emit_later(
                    kind="scan",
                    surface="scan",
                    title="scan-error",
                    payload={"handles": handles},
                )

    try:
        asyncio.get_running_loop().create_task(job())
    except RuntimeError:
        threading.Thread(target=lambda: asyncio.run(job()), daemon=True).start()
    return scan_status()


def _save_scan(payload: dict) -> dict:
    write_json("channel-scan.json", payload)
    return payload


def _clean_handle(raw: str) -> str:
    text = (raw or "").strip()
    text = text.replace("https://", "").replace("http://", "")
    text = text.split("?")[0].strip("/")
    for prefix in ("t.me/", "telegram.me/", "instagram.com/", "www.instagram.com/", "@"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
    return text.strip().strip("/")


def _plain(html: str) -> str:
    text = TAG.sub(" ", unescape(html or ""))
    return SPACE.sub(" ", text).strip()[:6000]


def _urls_for(platform: str, handle: str) -> list[str]:
    name = _clean_handle(handle)
    if not name:
        return []
    if platform == "telegram":
        return [f"https://t.me/s/{name}", f"https://t.me/{name}"]
    if platform == "instagram":
        return [f"https://www.instagram.com/{name}/"]
    return []


def _extract(html: str, base: str) -> dict:
    title = ""
    description = ""
    images: list[str] = []
    for key, value in META.findall(html or ""):
        if key == "title" and not title:
            title = unescape(value).strip()
        elif key == "description" and not description:
            description = unescape(value).strip()
        elif key == "image":
            images.append(urljoin(base, unescape(value).strip()))
    for value, key in META_REV.findall(html or ""):
        if key == "title" and not title:
            title = unescape(value).strip()
        elif key == "description" and not description:
            description = unescape(value).strip()
        elif key == "image":
            images.append(urljoin(base, unescape(value).strip()))
    for src in IMG_SRC.findall(html or ""):
        if src.startswith("data:"):
            continue
        images.append(urljoin(base, unescape(src).strip()))
    seen: list[str] = []
    for item in images:
        if item and item not in seen:
            seen.append(item)
    return {"title": title, "description": description, "images": seen[:12], "text": _plain(html)}


def _curl_get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes, str]:
    dest = Path(tempfile.mkstemp(prefix="sozan-scan-")[1])
    cmd = ["curl", "-sS", "-L", "--max-time", str(max(5, int(timeout))), "-o", str(dest), "-w", "%{http_code} %{url_effective}"]
    proxy = channel_proxy()
    if proxy:
        cmd.extend(["--proxy", proxy, "--noproxy", "*"])
    ua = headers.get("User-Agent") or USER_AGENT
    cmd.extend(["-A", ua])
    for key, value in headers.items():
        if key.lower() == "user-agent":
            continue
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 8)
        meta = (proc.stdout or "").strip().split(" ", 1)
        status = int(meta[0]) if meta and meta[0].isdigit() else 0
        final = meta[1] if len(meta) > 1 else url
        body = dest.read_bytes() if dest.is_file() else b""
        return status, body, final
    except Exception:
        return 0, b"", url
    finally:
        dest.unlink(missing_ok=True)


async def _http_get(url: str, *, headers: dict[str, str], timeout: float) -> tuple[int, bytes, str]:
    try:
        async with async_client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            res = await client.get(url)
            return res.status_code, res.content or b"", str(res.url)
    except ImportError:
        pass
    except Exception:
        pass
    return _curl_get(url, headers, timeout)


async def _fetch(url: str, *, headers: dict[str, str] | None = None) -> tuple[str, str]:
    status, body, final = await _http_get(url, headers=headers or {"User-Agent": USER_AGENT}, timeout=18)
    if status >= 400 or not body:
        return "", final
    return body.decode("utf-8", errors="ignore"), final


async def _download(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    suffix = Path(parsed.path).suffix.lower().split("?")[0]
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    name = f"{uuid4().hex}{suffix}"
    dest = _scan_dir() / name
    try:
        status, body, _final = await _http_get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if status >= 400 or not body or len(body) > 8_000_000:
            return ""
        dest.write_bytes(body)
    except Exception:
        return ""
    return name


def _media_url(node: dict) -> str:
    cands = ((node.get("image_versions2") or {}).get("candidates")) or []
    if cands and isinstance(cands[0], dict):
        return str(cands[0].get("url") or "").strip()
    return ""


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _instagram_from_feed(payload: dict, handle: str) -> dict:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    if not user:
        for row in items:
            if isinstance(row, dict) and isinstance(row.get("user"), dict):
                user = row["user"]
                break
    posts: list[dict] = []
    cities: list[str] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        cap = row.get("caption") if isinstance(row.get("caption"), dict) else {}
        text = str(cap.get("text") or "").strip()[:CAPTION_MAX]
        url = _media_url(row)
        if not url:
            for slide in row.get("carousel_media") or []:
                if isinstance(slide, dict):
                    url = _media_url(slide)
                    if url:
                        break
        if text or url:
            posts.append({"caption": text, "image": url, "id": str(row.get("pk") or row.get("id") or "")})
        loc = row.get("location") if isinstance(row.get("location"), dict) else {}
        city = str(loc.get("name") or "").strip()
        if city and city not in cities:
            cities.append(city)
    name = str(user.get("full_name") or handle).strip()
    bio = str(user.get("biography") or "").strip()
    bits = [name]
    if bio:
        bits.append(bio)
    if cities:
        bits.append("شهر: " + "، ".join(cities[:4]))
    captions = [str(item.get("caption") or "") for item in posts if item.get("caption")]
    images = [str(item.get("image") or "") for item in posts if item.get("image")]
    return {
        "title": name,
        "description": " — ".join(bits)[:400],
        "images": _unique(images)[:16],
        "captions": captions,
        "posts": posts[:24],
        "text": "\n\n".join(captions)[:5000],
    }


async def _sendbox_page(handle: str, sendbox_id: str) -> dict | None:
    import asyncio

    from app.services import sendbox_service

    ident = str(sendbox_id or "").strip()
    if not ident or not sendbox_service.configured():
        return None
    try:
        await sendbox_service.request_list_posts(account_id=ident, limit=24)
    except Exception:
        return None
    posts: list[dict] = []
    for _ in range(8):
        await asyncio.sleep(1.2)
        posts = sendbox_service.take_list_posts(ident)
        if posts:
            break
    if not posts:
        return None
    paired = []
    for row in posts:
        caption = str(row.get("caption") or "").strip()
        image = str(row.get("media_url") or "").strip()
        if caption or image:
            paired.append({"caption": caption[:CAPTION_MAX], "image": image})
    captions = [str(item.get("caption") or "") for item in paired if item.get("caption")]
    images = [str(item.get("image") or "") for item in paired if item.get("image")]
    return {
        "title": handle,
        "description": (captions[0] if captions else "")[:400],
        "images": _unique(images)[:24],
        "captions": captions[:24],
        "posts": paired[:24],
        "text": "\n\n".join(captions)[:5000],
    }


def _boxapi_pick(payload: dict) -> dict | None:
    captions: list[str] = []
    images: list[str] = []
    title = ""
    bio = ""

    def walk(node: object, depth: int = 0) -> None:
        nonlocal title, bio
        if depth > 7:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                low = str(key).lower()
                if low in {"full_name", "name"} and isinstance(value, str) and value.strip() and not title:
                    title = value.strip()
                if low in {"biography", "bio"} and isinstance(value, str) and value.strip() and not bio:
                    bio = value.strip()
                if low in {"caption", "text"} and isinstance(value, str) and len(value.strip()) > 8:
                    captions.append(value.strip()[:400])
                if isinstance(value, dict) and low == "caption":
                    text = str(value.get("text") or value.get("caption") or "").strip()
                    if len(text) > 8:
                        captions.append(text[:400])
                if low in {"media_url", "display_url", "profile_pic_url_hd", "profile_pic_url", "thumbnail_url"}:
                    url = str(value or "").strip()
                    if url.startswith("http"):
                        images.append(url)
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:48]:
                walk(item, depth + 1)

    walk(payload)
    if not captions and not images:
        return None
    unique_caps = _unique(captions)[:24]
    unique_imgs = _unique(images)[:24]
    paired = []
    for index, caption in enumerate(unique_caps):
        paired.append({"caption": caption[:CAPTION_MAX], "image": unique_imgs[index] if index < len(unique_imgs) else ""})
    return {
        "title": title,
        "description": bio[:400],
        "images": unique_imgs,
        "captions": unique_caps,
        "posts": paired,
        "text": "\n\n".join(unique_caps)[:5000],
    }


async def _boxapi_page(handle: str) -> dict | None:
    from app.services import sendbox_service

    name = _clean_handle(handle)
    key = sendbox_service.api_key()
    if not name or not key:
        return None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    info = None
    media = None
    try:
        async with async_client(timeout=22) as client:
            info_res = await client.post(
                "https://boxapi.ir/api/instagram/user/get_info_by_username",
                headers=headers,
                json={"username": name},
            )
            if info_res.status_code < 400:
                parsed_info = info_res.json()
                info = parsed_info if isinstance(parsed_info, dict) else None
            items: list[dict] = []
            max_id = ""
            for _ in range(3):
                body: dict = {"username": name, "count": 12}
                if max_id:
                    body["max_id"] = max_id
                media_res = await client.post(
                    "https://boxapi.ir/api/instagram/user/get_media_by_username",
                    headers=headers,
                    json=body,
                )
                if media_res.status_code >= 400:
                    break
                parsed_media = media_res.json()
                payload = parsed_media if isinstance(parsed_media, dict) else {}
                items.append(payload)
                nxt = str(payload.get("next_max_id") or "")
                if not nxt:
                    data = payload.get("response") if isinstance(payload.get("response"), dict) else payload
                    body_data = data.get("body") if isinstance(data, dict) and isinstance(data.get("body"), dict) else data
                    nxt = str((body_data or {}).get("next_max_id") or "") if isinstance(body_data, dict) else ""
                if not nxt or nxt == max_id:
                    break
                max_id = nxt
            media = {"pages": items} if items else None
    except Exception:
        return None
    picked = _boxapi_pick({"info": info or {}, "media": media or {}})
    if picked and not picked.get("title"):
        picked["title"] = name
    return picked


TG_TEXT = re.compile(r'class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.I | re.S)
TG_PHOTO = re.compile(r"background-image:\s*url\('([^']+)'\)", re.I)
TG_BEFORE = re.compile(r"t\.me/s/[^\"'?]+\?before=(\d+)", re.I)


def _telegram_from_html(html: str, handle: str) -> dict | None:
    texts = [_plain(block) for block in TG_TEXT.findall(html or "") if _plain(block)]
    photos = [unescape(src).strip() for src in TG_PHOTO.findall(html or "") if src.strip()]
    if not texts and not photos:
        return None
    return {
        "title": handle,
        "description": (texts[0] if texts else "")[:400],
        "images": _unique(photos)[:24],
        "captions": texts[:24],
        "text": "\n\n".join(texts)[:5000],
    }


async def _telegram_channel(handle: str) -> dict | None:
    name = _clean_handle(handle)
    if not name:
        return None
    html, _final = await _fetch(f"https://t.me/s/{name}")
    page = _telegram_from_html(html, handle)
    if not page:
        return None
    match = TG_BEFORE.search(html or "")
    if not match:
        return page
    more, _ = await _fetch(f"https://t.me/s/{name}?before={match.group(1)}")
    extra = _telegram_from_html(more, handle)
    if not extra:
        return page
    captions = _unique((page.get("captions") or []) + (extra.get("captions") or []))[:24]
    images = _unique((page.get("images") or []) + (extra.get("images") or []))[:24]
    page["captions"] = captions
    page["images"] = images
    page["text"] = "\n\n".join(captions)[:5000]
    return page


async def _instagram_page(handle: str) -> dict | None:
    name = _clean_handle(handle)
    if not name:
        return None
    url = f"https://i.instagram.com/api/v1/feed/user/{name}/username/?count=12"
    status, body, _final = await _http_get(
        url,
        headers={"User-Agent": IG_APP_UA, "Accept": "*/*"},
        timeout=20,
    )
    if status >= 400 or not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("items"):
        return None
    return _instagram_from_feed(payload, name)


HASHTAG = re.compile(r"#([^\s#]+)")
BRAND_ITEM = re.compile(r"(صندل|کفش|کیف|کوله)\s+از\s+برند\s+#?([\w\u0600-\u06FF]+)")
MODEL = re.compile(r"مدل(?:‌های| های)?\s+((?:پروانه\s*ای|پروانه‌ای)|[\w\u0600-\u06FF]{2,16})")
SKIP_MODELS = frozenset({"ساده", "لوکس", "جذاب", "جدید", "خاص", "زیبا", "شیک", "مون", "کار"})
SLOGAN_BITS = ("جایی که", "جاودانه", "نظرتون", "هر خانمی", "داشته باشید", "میکنه", "می‌کنه", "خبرای خوبی", "همراه ما باشید")


def _looks_like_product_title(title: str) -> bool:
    text = SPACE.sub(" ", title or "").strip(" .،,")
    if len(text) < 3 or len(text) > 36:
        return False
    if any(mark in text for mark in ("🤗", "😍", "😉", "😊", "🤷")):
        return False
    if text.startswith(("هر ", "به صورت", "وقتی ", "و هیچ", "نظرتون", "یکی از", "ببینید")):
        return False
    if any(bit in text for bit in SLOGAN_BITS):
        return False
    if any(bit in text for bit in ("کامنت", "دایرکت", "دیرکت", "برات بیاد", "قیمت و سایز", "پیام بده", "لایک")):
        return False
    if len(text.split()) > 6:
        return False
    return bool(ITEM_WORD.search(text))


def product_title_from_caption(caption: str, brand: str = "") -> str | None:
    raw = SPACE.sub(" ", caption or "").strip()
    if not raw:
        return None
    match = BRAND_ITEM.search(raw)
    if match:
        name = match.group(2).replace("_", " ").strip("#")
        if name and name not in {"برند"}:
            title = f"{match.group(1)} {name}"
            if _looks_like_product_title(title):
                return title[:36]
    match = MODEL.search(raw)
    if match:
        style = SPACE.sub(" ", match.group(1)).replace("پروانه ای", "پروانه‌ای").strip(" .")
        if style and style not in SKIP_MODELS:
            item = "کفش" if "کفش" in raw or "پروانه" in style else (ITEM_WORD.search(raw).group(0) if ITEM_WORD.search(raw) else "مدل")
            title = f"{item} {style}"
            if ITEM_WORD.search(title) and style not in SLOGAN_BITS:
                return title[:36]
    if "پارچه" in raw and ("نامزد" in raw or "مراسم" in raw):
        if "کیف" in raw and "کفش" in raw:
            return "کیف و کفش از پارچه مراسم"
        if "کیف" in raw:
            return "کیف از پارچه مراسم"
        return "کفش از پارچه مراسم"
    item_match = ITEM_WORD.search(raw)
    if item_match:
        bits = [item_match.group(0)]
        if "مراسم" in raw or "نامزد" in raw:
            bits.append("مجلسی")
        for style in STYLE_WORDS:
            if style in raw and style not in bits:
                bits.append(style)
                break
        for material in MATERIALS:
            if material in raw and material not in bits:
                bits.append(material)
                break
        title = " ".join(bits)
        if len(bits) > 1 and _looks_like_product_title(title):
            return title[:36]
    for tag in HASHTAG.findall(raw):
        clean = tag.replace("_", " ").strip()
        if "پروانه" in clean:
            return "کفش پروانه‌ای"
        if ITEM_WORD.search(clean) and len(clean) > 3 and clean not in {"کفش", "صندل", "کیف"}:
            return clean[:36]
    if item_match:
        title = item_match.group(0)
        if _looks_like_product_title(title):
            return title[:36]
    _ = brand
    return None


def _page_posts(page: dict) -> list[dict]:
    posts = page.get("posts") if isinstance(page.get("posts"), list) else []
    if posts:
        return [item for item in posts if isinstance(item, dict)]
    captions = page.get("captions") if isinstance(page.get("captions"), list) else None
    blocks = captions if captions else [block for block in str(page.get("text") or "").split("\n\n") if block.strip()]
    images = [str(item) for item in (page.get("images") or []) if str(item).strip()]
    rows: list[dict] = []
    for index, caption in enumerate(blocks):
        rows.append(
            {
                "caption": str(caption or ""),
                "image": images[index] if index < len(images) else "",
                "id": f"idx-{index}",
            }
        )
    return rows


def _product_from_caption(caption: str, brand: str = "", image_url: str = "", fallback_no: int = 0) -> dict | None:
    title = product_title_from_caption(caption, brand=brand)
    if not title:
        # نامی پیدا نشد؛ جملهٔ فراخوان هرگز نام کالا نمی‌شود.
        title = f"کالای {max(1, fallback_no)}"
    if len(title) < 3:
        return None
    price, price_note = parse_caption_price(caption)
    if price_note == "دایرکت":
        price_status = "direct"
    elif price > 0:
        price_status = "parsed"
    elif any(ch.isdigit() for ch in caption):
        price_status = "parse-failed"
    else:
        price_status = "missing"
    return {
        "title": title,
        "price": price,
        "priceNote": price_note,
        "priceStatus": price_status,
        "priceUnit": "toman",
        "description": SPACE.sub(" ", str(caption)).strip()[:CAPTION_MAX],
        "category": _category_from_text(caption) or _category_from_text(title),
        "colors": parse_caption_colors(caption),
        "sizes": parse_caption_sizes(caption),
        "imageUrl": image_url,
        "sourceCaption": SPACE.sub(" ", str(caption)).strip()[:CAPTION_MAX],
        "extractor": "caption",
        "confidence": 0.7,
    }


def _caption_products(page: dict, brand: str = "") -> list[dict]:
    seen: list[str] = []
    rows: list[dict] = []
    for post in _page_posts(page):
        caption = str(post.get("caption") or "")
        row = _product_from_caption(
            caption, brand=brand, image_url=str(post.get("image") or ""), fallback_no=len(seen) + 1
        )
        if not row:
            continue
        title = str(row.get("title") or "")
        if title in seen:
            continue
        seen.append(title)
        row["sourcePostId"] = str(post.get("id") or post.get("pk") or title)
        rows.append(row)
        if len(rows) >= 24:
            break
    return rows


def _llm_price(row: dict) -> int:
    raw = row.get("price")
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return raw if raw > 0 else 0
    text = str(raw or "").strip()
    if text.isdigit():
        return int(text)
    value, _note = parse_caption_price(text)
    return value


def _titles_overlap(left: str, right: str) -> bool:
    a = SPACE.sub(" ", left or "").strip()
    b = SPACE.sub(" ", right or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def enrich_scan_products(caption_rows: list[dict], llm_rows: list[dict]) -> list[dict]:
    used: set[int] = set()
    products: list[dict] = []
    for cap in caption_rows:
        match_at = None
        cap_title = str(cap.get("title") or "")
        for index, llm in enumerate(llm_rows):
            if index in used or not isinstance(llm, dict):
                continue
            if _titles_overlap(cap_title, str(llm.get("title") or "")):
                match_at = index
                break
        row = dict(cap)
        if match_at is not None:
            used.add(match_at)
            llm = llm_rows[match_at]
            llm_title = str(llm.get("title") or "").strip()
            if llm_title and len(llm_title) > len(str(row.get("title") or "")) and _looks_like_product_title(llm_title):
                row["title"] = llm_title[:36]
            llm_price = _llm_price(llm)
            if not int(row.get("price") or 0) and llm_price > 0:
                row["price"] = llm_price
            category = str(llm.get("category") or "").strip()[:40]
            if category and not row.get("category"):
                row["category"] = category
        products.append(row)
    seen = {str(item.get("title") or "") for item in products}
    for index, llm in enumerate(llm_rows):
        if index in used or not isinstance(llm, dict):
            continue
        title = str(llm.get("title") or "").strip()
        if not title or title in seen:
            continue
        products.append(
            {
                "title": title[:80],
                "price": _llm_price(llm),
                "priceNote": "",
                "description": str(llm.get("description") or "").strip()[:CAPTION_MAX],
                "category": str(llm.get("category") or "").strip()[:40] or _category_from_text(title),
                "colors": parse_caption_colors(str(llm.get("description") or "")),
                "sizes": parse_caption_sizes(str(llm.get("description") or "")),
                "imageUrl": "",
            }
        )
        seen.add(title)
    return products


def _parse_colors(parsed: dict) -> list[str]:
    out: list[str] = []
    for item in parsed.get("colors") or []:
        text = str(item).strip()
        if not text or text.isdigit() or text.lower() == "#112233":
            continue
        if text not in out:
            out.append(text[:40])
    return out[:8]


async def scan_account(*, platform: str, handle: str, brand: str, work: str, sendbox_id: str = "") -> dict:
    pages: list[dict] = []
    notes: list[str] = []
    ident = str(sendbox_id or "").strip()
    if platform == "instagram":
        page = await _sendbox_page(handle, ident)
        if not page:
            page = await _boxapi_page(handle)
        if not page:
            page = await _instagram_page(handle)
        if page and (page.get("text") or page.get("images") or page.get("captions")):
            pages.append(page)
        else:
            notes.append("فید اینستاگرام خوانده نشد")
    elif platform == "telegram":
        page = await _telegram_channel(handle)
        if page and (page.get("text") or page.get("images") or page.get("captions")):
            pages.append(page)
        else:
            notes.append("کانال تلگرام خوانده نشد")
    for url in _urls_for(platform, handle):
        if pages:
            break
        try:
            html, final = await _fetch(url)
        except Exception:
            notes.append(f"خواندن {url} نشد")
            continue
        if not html:
            notes.append(f"{url} خالی بود")
            continue
        extracted = _telegram_from_html(html, handle) if platform == "telegram" else _extract(html, final)
        if not extracted:
            extracted = _extract(html, final)
        if extracted.get("title") in {"Instagram", "Telegram"} and not extracted.get("description") and not extracted.get("captions"):
            notes.append(f"{url} صفحهٔ ورود داد")
            continue
        pages.append(extracted)
        break
    if not pages:
        return {
            "platform": platform,
            "handle": handle,
            "about": "",
            "colors": [],
            "notes": notes or ["صفحهٔ عمومی خوانده نشد"],
            "images": [],
            "categories": [],
            "products": [],
            "fetched": False,
        }
    blob = "\n\n".join(
        f"عنوان: {page.get('title')}\nتوضیح: {page.get('description')}\nمتن:\n{page.get('text')}" for page in pages
    )
    page_brand = str(pages[0].get("title") or brand).strip()
    page_about = str(pages[0].get("description") or work).strip()
    parsed = await complete_json(
        """از نوشته‌های همین صفحه فقط JSON برگردان.
{"about":"خلاصه فارسی برند و شهر و کار","colors":["سفید","قهوه‌ای"],"categories":["کیف","کفش"],"products":[{"title":"نام کالا","price":0,"description":"یک خط","category":"کیف"}]}
title نام کوتاه کالاست مثل «صندل لوکا» یا «کفش مجلسی ساتن»، نه شعار، نه جمله، نه ایموجی.
دسته‌بندی را از هایلایت، منوی صفحه، یا نوع کالا در کپشن بگیر؛ همان برچسب کانال را بگذار.
برند را از عنوان و کپشن همین صفحه بگیر، نه از فروشگاه دیگر. قیمت فقط اگر در متن آمده عدد بگذار؛ وگرنه 0. حداکثر ۲۴ محصول واقعی از همین کپشن‌ها. چیز ساختگی نگذار.""",
        (
            f"عنوان صفحه: {page_brand}\nمعرفی صفحه: {page_about}\nپلتفرم: {platform}\nحساب: {handle}\n"
            f"کپشن‌ها:\n{blob}"
        ),
        surface="scan",
    )
    llm_error = str(parsed.get("error") or "") if str(parsed.get("error") or "") in LLM_ERRORS else ""
    if llm_error:
        notes.append("مدل هوش مصنوعی به این اسکن نرسید")
    llm_rows = parsed.get("products") if isinstance(parsed.get("products"), list) else []
    products = enrich_scan_products(_caption_products(pages[0], brand=page_brand), llm_rows)
    colors = _parse_colors(parsed)
    for row in products:
        for name in row.get("colors") or []:
            if name not in colors:
                colors.append(name)
    colors = colors[:8]
    categories = _parse_categories(parsed, products)
    about = str(parsed.get("about") or pages[0].get("description") if pages else "").strip()[:400]
    imported = []
    winner = "html"
    if ident and platform == "instagram":
        winner = "sendbox"
    elif platform == "instagram":
        winner = "instagram-api"
    for row in products[:24]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        price = int(row.get("price") or 0)
        if price < 0:
            price = 0
        image = ""
        image_url = str(row.get("imageUrl") or "").strip()
        if image_url.startswith("http"):
            image = await _download(image_url)
        handle_key = _clean_handle(handle)
        post_id = str(row.get("sourcePostId") or title)
        imported.append(
            {
                "title": title,
                "price": price,
                "description": str(row.get("description") or "").strip()[:CAPTION_MAX],
                "sku": f"{platform}-{handle_key}-{post_id}"[:80],
                "image": image,
                "source": platform,
                "sourceHandle": handle,
                "sourcePostId": post_id,
                "sourceCaption": str(row.get("sourceCaption") or row.get("description") or "")[:CAPTION_MAX],
                "extractor": str(row.get("extractor") or winner),
                "confidence": float(row.get("confidence") or 0.6),
                "category": str(row.get("category") or "").strip()[:40],
                "colors": list(row.get("colors") or []),
                "sizes": str(row.get("sizes") or ""),
                "priceNote": str(row.get("priceNote") or ""),
                "priceStatus": str(row.get("priceStatus") or ("direct" if row.get("priceNote") == "دایرکت" else "missing" if price <= 0 else "parsed")),
                "priceUnit": "toman",
                "stableKey": f"{platform}:{handle_key}:{post_id}",
            }
        )
    if blob.strip():
        try:
            await voice_service.learn(platform=platform, handle=handle, samples=blob[:1200])
            from app.services import channel_service

            channel_service.mark_voice_handle(platform=platform, handle=handle)
        except Exception:
            notes.append("لحن از این صفحه کامل یاد گرفته نشد")
    return {
        "platform": platform,
        "handle": handle,
        "about": about,
        "colors": colors,
        "categories": categories,
        "notes": notes,
        "images": [row.get("image") for row in imported if row.get("image")],
        "products": imported,
        "fetched": bool(pages),
        "winner": winner,
        "llmError": llm_error,
    }


def _model_unavailable(results: list[dict], candidates: list[dict]) -> bool:
    """True when the scan produced nothing because the model failed, not because the page was empty."""
    if candidates:
        return False
    fetched = [item for item in results if item.get("fetched")]
    return bool(fetched) and all(item.get("llmError") for item in fetched)


async def scan_accounts(accounts: list[dict]) -> dict:
    cfg = get_settings()
    brand = str(cfg.get("storeName") or "")
    work = str(cfg.get("storeTagline") or "")
    results = []
    for account in accounts:
        platform = str(account.get("platform") or "")
        handle = str(account.get("handle") or "")
        if not platform or not handle:
            continue
        sendbox_id = str(account.get("sendboxAccountId") or "")
        if not sendbox_id and platform == "instagram":
            from app.services import channel_service

            row = channel_service.account_for_platform("instagram")
            if row:
                sendbox_id = channel_service.sendbox_account_id(row)
        results.append(
            await scan_account(
                platform=platform,
                handle=handle,
                brand=brand,
                work=work,
                sendbox_id=sendbox_id,
            )
        )
    previous = get_scan()
    by_key = {}
    for item in previous.get("accounts") or []:
        if isinstance(item, dict) and item.get("handle"):
            by_key[(str(item.get("platform")), str(item.get("handle")))] = item
    for item in results:
        by_key[(str(item.get("platform")), str(item.get("handle")))] = item
    merged = list(by_key.values())
    colors = []
    categories: list[str] = []
    abouts = []
    for item in merged:
        for color in item.get("colors") or []:
            if not color or str(color).startswith("#") or color in colors:
                continue
            colors.append(color)
        for cat in item.get("categories") or []:
            text = str(cat).strip()[:40]
            if text and text not in categories:
                categories.append(text)
        if item.get("about"):
            abouts.append(str(item["about"]))
    payload = {
        "accounts": merged,
        "colors": colors,
        "categories": categories[:12],
        "about": " ".join(abouts)[:800],
        "productCount": sum(len(item.get("products") or []) for item in merged),
        "scanId": str(uuid4()),
        "quality": {},
    }
    candidates: list[dict] = []
    for item in results:
        for row in item.get("products") or []:
            if isinstance(row, dict):
                candidates.append(row)
    run_dir = tenant_dir() / "scan-run" / str(payload["scanId"])
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "candidate-catalog.json").write_text(
        json.dumps({"candidates": candidates, "accounts": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fetched = sum(1 for item in results if item.get("fetched"))
    with_image = sum(1 for row in candidates if row.get("image"))
    with_cat = sum(1 for row in candidates if row.get("category"))
    no_price = 0
    for row in candidates:
        try:
            price = int(row.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        if price <= 0:
            no_price += 1
    rejected = sum(1 for item in results if not item.get("fetched"))
    if _model_unavailable(results, candidates):
        # Model outage (e.g. GPU1 evicted mid-request): keep the previous scan and
        # products untouched and let start_scan report a retryable error.
        emit_later(
            kind="scan",
            surface="scan",
            title="scan-candidates",
            scan_id=str(payload["scanId"]),
            status="failed",
            payload={"fetchedAccounts": fetched, "candidates": 0, "errorClass": SCAN_MODEL_ERROR},
        )
        return {**previous, "error": SCAN_MODEL_ERROR, "scanId": payload["scanId"], "quality": {**(previous.get("quality") or {}), "error": SCAN_MODEL_ERROR}}
    thin_or_empty = len(candidates) == 0
    poor_coverage = len(candidates) >= 5 and with_image / max(len(candidates), 1) < 0.2
    needs_review = thin_or_empty or poor_coverage
    quality = {
        "fetchedAccounts": fetched,
        "candidates": len(candidates),
        "withImage": with_image,
        "withCategory": with_cat,
        "noPrice": no_price,
        "rejectedAccounts": rejected,
        "needsReview": needs_review,
        "imported": 0,
    }
    payload["quality"] = quality
    emit_later(
        kind="scan",
        surface="scan",
        title="scan-candidates",
        scan_id=str(payload["scanId"]),
        status="review" if needs_review else "ready",
        payload=quality,
    )
    if thin_or_empty:
        # Nothing new from the page: keep what earlier scans imported and say so.
        payload["needsReview"] = True
        quality["kept"] = storefront_service.count_scanned_handle(
            [str(item.get("handle") or "") for item in results]
        )
        if payload["about"]:
            voice_service.merge_summary(str(payload["about"]))
        return _save_scan(payload)
    if poor_coverage:
        payload["needsReview"] = True
    seen_keys: set[str] = set()
    for item in results:
        handle = str(item.get("handle") or "")
        if handle:
            storefront_service.remove_scanned_handle(handle)
    imported = 0
    for row in candidates:
        key = str(row.get("stableKey") or "")
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        storefront_service.upsert_scanned_product(
            title=title,
            price=int(row.get("price") or 0),
            description=str(row.get("description") or ""),
            sku=str(row.get("sku") or ""),
            image=str(row.get("image") or ""),
            source=str(row.get("source") or ""),
            sourceHandle=str(row.get("sourceHandle") or ""),
            category=str(row.get("category") or ""),
            colors=list(row.get("colors") or []),
            sizes=str(row.get("sizes") or ""),
            priceNote=str(row.get("priceNote") or ""),
            sourcePostId=str(row.get("sourcePostId") or ""),
            sourceCaption=str(row.get("sourceCaption") or ""),
            extractor=str(row.get("extractor") or ""),
            confidence=float(row.get("confidence") or 0),
            priceStatus=str(row.get("priceStatus") or ""),
            priceUnit=str(row.get("priceUnit") or "toman"),
            stableKey=key,
            stock=int(row["stock"]) if str(row.get("stock") or "").isdigit() else 24,
        )
        imported += 1
    quality["imported"] = imported
    payload["productCount"] = imported
    if payload["about"]:
        voice_service.merge_summary(str(payload["about"]))
    return _save_scan(payload)


def brief_for_shop() -> str:
    scan = get_scan()
    products = storefront_service.list_products().get("products") or []
    scanned = [row for row in products if row.get("source")]
    handles = []
    for row in scanned:
        handle = str(row.get("sourceHandle") or "").strip()
        if handle and handle not in handles:
            handles.append(handle)
    if not handles:
        for item in scan.get("accounts") or []:
            handle = str(item.get("handle") or "").strip()
            if handle and handle not in handles:
                handles.append(handle)
    lines: list[str] = []
    for row in scanned[:12]:
        bit = str(row.get("title") or "")
        price = int(row.get("price") or 0)
        note = str(row.get("priceNote") or "")
        if price > 0:
            bit += f" / {price} تومان"
        elif note:
            bit += f" / {note}"
        colors = [str(item) for item in (row.get("colors") or []) if str(item).strip()]
        if colors:
            bit += " / رنگ " + "، ".join(colors)
        if row.get("sizes"):
            bit += f" / {row.get('sizes')}"
        lines.append(bit)
    colors = "، ".join(scan.get("colors") or []) or "هنوز پالت اسکن نشده"
    cats = [str(item) for item in (scan.get("categories") or []) if str(item).strip()]
    if not cats:
        cats = [str(row.get("category") or "").strip() for row in scanned if str(row.get("category") or "").strip()]
        cats = list(dict.fromkeys(cats))
    categories = "، ".join(cats) or "هنوز دسته اسکن نشده"
    catalog = "\n".join(f"- {line}" for line in lines) or "هنوز کالایی از کانال نیامده"
    page = "، ".join(handles) or "هنوز پیج اسکن نشده"
    return (
        f"پیج اسکن‌شده: {page}\n"
        f"اسکن شبکه‌ها: {scan.get('about') or '—'}\n"
        f"رنگ‌های دیده‌شده: {colors}\n"
        f"دسته‌بندی کانال: {categories}\n"
        f"کالاهای پیدا شده:\n{catalog}\n"
        f"همین کاتالوگ را استفاده کن. نگو به پیج یا اینستاگرام دسترسی نداری. از همین عکس‌های کانال برای کارت کالا استفاده کن. تصویر ساختگی نساز."
    )

# ---- Public API for other roles (docs/agents). Wrappers call the private names at call time, so tests that patch those still work.

def scan_dir() -> Path:
    return _scan_dir()


def unattributed_dir() -> Path:
    return _unattributed_dir()


def category_from_text(text: str) -> str:
    return _category_from_text(text)


def looks_like_product_title(title: str) -> bool:
    return _looks_like_product_title(title)
