"""Direct-message sales agent.

Chat goes through llm.py on the inbox surface: cloud first, and the home 9b
only after those clouds fail. Customer text is masked before that call and is
not written to observe. Shipping, returns, and shop policy are copied from the
stored policy, not from the model. Stock, order status, and payment links still
come from the shop's own data. Local bge-m3 only nudges a tool when the model
answered with none.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from app.config import settings
from app.services.llm import (
    ARVAN_HOST_SUFFIX,
    INBOX_TURN_BUDGET,
    LLM_BAD_JSON,
    complete_tools,
    spoken_model_reply,
)
from app.services.observe_client import emit_later
from app.services.persian_text import guard_output
from app.services.pii_mask import mask_pii
from app.services.router_embed import cosine

log = logging.getLogger("sozan.inbox.agent")

AGENT_MODEL = "qwen3.5-9b"
EMBED_MODEL = "bge-m3"
MAX_ROUNDS = 4
DRY_PAY_HOST = "dry-mock.invalid"
_BUY_MARKS = (
    "لینک پرداخت",
    "پرداخت",
    "بخرم",
    "بخرید",
    "بخر",
    "خرید",
    "پول",
    "کارت به کارت",
    "لینک بده",
    "درگاه",
)
_TITLE_NOISE = {"چرم", "نخی", "کوچک", "فلزی", "مردانه", "تابستانی"}
TIMEOUT = 45.0
INTENT_THRESHOLD = 0.75
INTENT_SAMPLES = {
    "stock": ("این کالا موجود است؟", "قیمت این کالا چقدر است؟", "هنوز دارید؟"),
    "order_status": ("سفارشم کجاست؟", "وضعیت سفارش را بگو", "پیگیری شماره سفارش"),
    "payment_link": ("لینک پرداخت بفرست", "می‌خواهم همین را بخرم", "چطور پول را بدهم؟"),
}
_SAMPLE_VECTORS: dict[str, list[list[float]]] | None = None


def local_base() -> str:
    return str(settings.local_llm_url or "http://127.0.0.1:9292/v1").rstrip("/")


def _cloud_base(url: str) -> bool:
    return ARVAN_HOST_SUFFIX in url.lower()


def _explicit_buy(text: str) -> bool:
    folded = _norm(text)
    return any(_norm(mark) in folded for mark in _BUY_MARKS)


def _mentioned_products(text: str) -> list[dict]:
    folded = _norm(text)
    scored: list[tuple[int, dict]] = []
    for item in _products():
        title = _norm(str(item.get("title") or ""))
        words = [word for word in title.split() if len(word) >= 3 and word not in _TITLE_NOISE]
        hits = [word for word in words if word in folded]
        if hits:
            scored.append((len(hits), item))
    if not scored:
        return _color_matches(folded)
    best = max(count for count, _item in scored)
    tier = [item for count, item in scored if count == best]
    if len(tier) == 1:
        return tier
    extra = []
    for item in tier:
        title = _norm(str(item.get("title") or ""))
        noise = [word for word in title.split() if word in _TITLE_NOISE and word in folded]
        extra.append((len(noise), item))
    best_noise = max(count for count, _item in extra)
    if best_noise:
        return [item for count, item in extra if count == best_noise]
    return tier


def _tools(*, allow_payment: bool = True) -> list[dict]:
    rows = [
        {
            "type": "function",
            "function": {
                "name": "stock",
                "description": "موجودی و قیمت واقعی یک کالا از کاتالوگ همین فروشگاه",
                "parameters": {
                    "type": "object",
                    "properties": {"product": {"type": "string", "description": "نام کالا"}},
                    "required": ["product"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "order_status",
                "description": "وضعیت یک سفارش با شمارهٔ خودش",
                "parameters": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string", "description": "شماره سفارش"}},
                    "required": ["order_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "payment_link",
                "description": "ساخت لینک پرداخت برای یک کالای موجود در کاتالوگ",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string", "description": "نام یا شناسهٔ کالا"},
                        "qty": {"type": "integer", "description": "تعداد، از ۱ تا ۵"},
                    },
                    "required": ["product"],
                },
            },
        },
    ]
    if allow_payment:
        return rows
    return [row for row in rows if (row.get("function") or {}).get("name") != "payment_link"]


def _norm(text: str) -> str:
    return (
        str(text or "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .strip()
        .lower()
    )


def _color_matches(folded: str) -> list[dict]:
    found = []
    for item in _products():
        colors = [_norm(str(color)) for color in (item.get("colors") or []) if str(color).strip()]
        if any(len(color) >= 3 and color in folded for color in colors):
            found.append(item)
    return found


def _one_edit(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1 or min(la, lb) < 3:
        return False
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 1


def _products() -> list[dict]:
    from app.services.storefront_service import list_products

    rows = list_products().get("products") or []
    return [row for row in rows if isinstance(row, dict)]


def _match_products(needle: str) -> list[dict]:
    wanted = _norm(needle)
    if len(wanted) < 2:
        return []
    hits = []
    for item in _products():
        title = _norm(str(item.get("title") or ""))
        pid = _norm(str(item.get("id") or ""))
        if wanted in title or wanted == pid or title in wanted:
            hits.append(item)
    if hits:
        return hits[:3]
    fuzzy = []
    for item in _products():
        title = _norm(str(item.get("title") or ""))
        tokens = [tok for tok in title.split() if len(tok) >= 3]
        if any(_one_edit(wanted, tok) for tok in tokens) or _one_edit(wanted, title):
            fuzzy.append(item)
    return fuzzy[:3]


def _public_product(item: dict) -> dict:
    price = int(item.get("finalPrice") or item.get("price") or 0)
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "price": price,
        "stock": int(item.get("stock") or 0),
    }


def tool_stock(product: str) -> dict:
    hits = [_public_product(item) for item in _match_products(product)]
    if not hits:
        return {"ok": False, "error": "کالا در کاتالوگ نیست"}
    return {"ok": True, "products": hits}


def tool_order_status(order_id: str) -> dict:
    from app.services.pay_service import get_order, public_order

    row = get_order(str(order_id or "").strip())
    if not row:
        return {"ok": False, "error": "سفارش پیدا نشد"}
    pub = public_order(row)
    return {
        "ok": True,
        "id": pub.get("id") or "",
        "title": pub.get("title") or "",
        "status": pub.get("status") or "",
        "amount": int(pub.get("amount") or 0),
    }


def _dry_mock_payment() -> bool:
    """Fake link only on the dry edge, and only while the shop gateway is still mock.

    Real shops without a merchant keep the handoff. payment_service stays unchanged.
    """
    from app.services.arvan_dns_service import edge_dry
    from app.services.settings_service import get_settings

    if not edge_dry():
        return False
    gateway = str(get_settings().get("paymentGateway") or "mock").strip().lower()
    return gateway in {"", "mock"}


async def tool_payment_link(product: str, qty: int, *, thread: dict | None) -> dict:
    from app.services.channel_service import PLATFORMS
    from app.services.pay_service import create_order

    hits = _match_products(product)
    if not hits:
        return {"ok": False, "error": "کالا در کاتالوگ نیست"}
    item = hits[0]
    price = int(item.get("finalPrice") or item.get("price") or 0)
    if price <= 0:
        return {"ok": False, "error": "قیمت تومان برای این کالا نیست"}
    count = min(5, max(1, int(qty or 1)))
    if _dry_mock_payment():
        slug = re.sub(r"[^a-z0-9]+", "-", str(item.get("id") or "item").lower()).strip("-") or "item"
        return {
            "ok": True,
            "dry": True,
            "title": str(item.get("title") or ""),
            "amount": price * count,
            "payUrl": f"https://{DRY_PAY_HOST}/p/{slug}-{count}",
        }
    platform = str((thread or {}).get("platform") or "")
    channel = PLATFORMS.get(platform, platform) or "دایرکت"
    order = await create_order(
        title=str(item.get("title") or ""),
        amount=price * count,
        product_id=str(item.get("id") or ""),
        qty=count,
        customer=str((thread or {}).get("sender") or "مشتری"),
        channel=channel,
        thread_id=str((thread or {}).get("id") or ""),
    )
    url = str(order.get("payUrl") or "").strip()
    if not url:
        return {"ok": False, "error": "لینک پرداخت ساخته نشد"}
    return {
        "ok": True,
        "title": str(order.get("title") or item.get("title") or ""),
        "amount": int(order.get("amount") or 0),
        "payUrl": url,
    }


async def run_tool(name: str, args: dict, *, thread: dict | None) -> dict:
    if name == "stock":
        return tool_stock(str(args.get("product") or ""))
    if name == "order_status":
        return tool_order_status(str(args.get("order_id") or ""))
    if name == "payment_link":
        try:
            qty = int(args.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        return await tool_payment_link(str(args.get("product") or ""), qty, thread=thread)
    return {"ok": False, "error": "ابزار ناشناخته"}


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    token = str(settings.local_llm_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _calls_from(payload: dict) -> tuple[str, list[dict]]:
    msg = ((payload.get("choices") or [{}])[0].get("message") or {})
    text = spoken_model_reply(str(msg.get("content") or ""))
    if text == LLM_BAD_JSON["reply"]:
        text = ""
    calls = []
    for raw in msg.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        fn = raw.get("function") or {}
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        args_raw = fn.get("arguments") or "{}"
        if isinstance(args_raw, dict):
            args = args_raw
        else:
            try:
                parsed = json.loads(str(args_raw))
            except json.JSONDecodeError:
                parsed = {}
            args = parsed if isinstance(parsed, dict) else {}
        calls.append({"id": str(raw.get("id") or name), "name": name, "arguments": args})
    return text, calls


async def _post(path: str, body: dict) -> dict:
    base = local_base()
    if _cloud_base(base):
        raise RuntimeError("inbox_cloud_refused")
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, proxy=None) as client:
        res = await client.post(f"{base}{path}", json=body, headers=_headers())
        res.raise_for_status()
        payload = res.json()
    if not isinstance(payload, dict):
        raise RuntimeError("inbox_bad_json")
    return payload


def _mask_for_model(messages: list[dict]) -> list[dict]:
    safe = []
    for msg in messages:
        if str(msg.get("role") or "") == "user":
            safe.append({**msg, "content": mask_pii(str(msg.get("content") or ""))})
        else:
            safe.append(msg)
    return safe


def _digit_fold(text: str) -> str:
    return str(text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _amounts(text: str) -> set[str]:
    folded = _digit_fold(text)
    found = set(re.findall(r"\d{4,}", folded))
    found.update(re.findall(r"\d+(?:\.\d+)?\s*٪", folded))
    found.update(re.findall(r"\d+(?:\.\d+)?\s*%", folded))
    return found


def _tool_blob(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        content = str(msg.get("content") or "")
        if msg.get("role") == "tool" or content.startswith("موجودی این کالاها"):
            parts.append(content)
    return "\n".join(parts)


def _numbers_ok(reply: str, tool_blob: str) -> bool:
    return not (_amounts(reply) - _amounts(tool_blob))


def _number_reminder(tool_blob: str) -> str:
    allowed = sorted(_amounts(tool_blob))
    if not allowed:
        return (
            "پیام قبلی رد شد. در خروجی ابزار این نوبت هیچ قیمت، مبلغ یا درصدی نیست. "
            "جواب را از نو بنویس و هیچ عدد قیمت یا درصدی نیاور."
        )
    shown = "، ".join(allowed)
    return (
        "پیام قبلی رد شد. فقط این عددها در خروجی ابزار این نوبت هستند و باید عیناً بیایند: "
        f"{shown}. جواب را از نو بنویس و عدد دیگری نیاور."
    )


_CLAIM_MARKS = (
    "اصیل",
    "طبیعی",
    "مقاوم",
    "حکاکی",
    "ضمانت",
    "ارسال",
    "قیمت",
    "موجود",
    "چرم",
    "طلا",
    "نقره",
    "جیب",
    "قابل تنظیم",
    "دوام",
    "اصالت",
    "جنس",
)
_URL = re.compile(r"https?://[^\s<>\"']+")
HANDOFF_LINE = "همکارم به‌زودی جواب می‌دهد"
CLAIMS_LINE = "اجازه بدهید دقیق چک کنم و برگردم."


def _looks_like_claim(text: str) -> bool:
    if any(mark in text for mark in _CLAIM_MARKS):
        return True
    return bool(re.search(r"اصل(?!ا)", text))


def _shop_url() -> str:
    from app.services.shop_service import _shop, live_url

    return live_url(_shop()).strip().rstrip("/")


def _public_shop_url() -> str:
    """A real storefront address. Localhost and an empty shop are not one."""
    url = _shop_url()
    if not url.startswith(("http://", "https://")):
        return ""
    host = url.split("://", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return ""
    return url


def _fix_links(reply: str, pay_urls: list[str]) -> str:
    """Keep this shop's address and this turn's payment links. Anything else goes.

    When the shop has no public address yet, a made-up URL is removed.
    """
    shop = _public_shop_url()
    allowed = {shop} if shop else set()
    for url in pay_urls:
        cleaned = url.strip().rstrip("/")
        if cleaned:
            allowed.add(cleaned)

    def repl(match: re.Match) -> str:
        raw = match.group(0).rstrip(".,،);؛")
        bare = raw.rstrip("/")
        if bare in allowed or any(bare == item or bare.startswith(item + "/") for item in allowed):
            return raw
        return shop

    text = _URL.sub(repl, reply)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _hand_off(thread: dict | None, reason: str) -> str:
    thread_id = str((thread or {}).get("id") or "").strip()
    if thread_id:
        from app.services.inbox_service import mark_handoff

        mark_handoff(thread_id, reason)
    return HANDOFF_LINE


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__


_QUALITATIVE = tuple(mark for mark in _CLAIM_MARKS if mark not in {"قیمت", "موجود"})


def _availability_conflict(text: str, facts: str) -> bool:
    stocks = [int(item) for item in re.findall(r'"stock":\s*(-?\d+)', facts)]
    if not stocks:
        return False
    says_out = any(word in text for word in ("ناموجود", "موجود نیست", "تموم", "تمام شده"))
    says_in = "موجود" in text and not says_out
    if says_in and max(stocks) <= 0:
        return True
    if says_out and min(stocks) > 0:
        return True
    return False


def _needs_claims_model(text: str, facts: str) -> bool:
    """A second model call only for a product claim that is not already in the tool text."""
    if any(mark in text and mark not in facts for mark in _QUALITATIVE):
        return True
    if re.search(r"اصل(?!ا)", text) and not re.search(r"اصل(?!ا)", facts):
        return True
    if re.search(r'"stock":\s*-?\d+', facts):
        return False
    return "موجود" in text or "تموم" in text or "تمام" in text


async def _inbox_claims_complete(system: str, user: str, **_kwargs) -> dict:
    from app.services.llm import complete_json

    return await complete_json(system, user, surface="inbox", max_tokens=400)


async def _claims(text: str, facts: str) -> str:
    if _availability_conflict(text, facts):
        return CLAIMS_LINE
    if not _needs_claims_model(text, facts):
        return text
    try:
        from app.services.claims_guard import check
    except ImportError:
        return text
    try:
        hits = await check(mask_pii(text), facts, complete=_inbox_claims_complete)
    except Exception:
        log.warning("claims guard skipped")
        return text
    if hits:
        return CLAIMS_LINE
    return text


async def _complete(messages: list[dict], *, allow_payment: bool, timeout: float) -> tuple[str, list[dict]]:
    result = await complete_tools(
        messages=_mask_for_model(messages),
        tools=_tools(allow_payment=allow_payment),
        temperature=0.3,
        max_tokens=500,
        timeout=timeout,
        surface="inbox",
    )
    calls = []
    for call in result.get("tool_calls") or []:
        if not isinstance(call, dict) or not call.get("name"):
            continue
        args = call.get("arguments")
        calls.append(
            {
                "id": str(call.get("id") or "call"),
                "name": str(call.get("name")),
                "arguments": args if isinstance(args, dict) else {},
            }
        )
    raw = str(result.get("text") or "").strip()
    # A shop address is Latin. Judge the Persian around it, and keep the address for the link guard.
    judged = spoken_model_reply(_URL.sub("نشانی", raw))
    text = "" if judged == LLM_BAD_JSON["reply"] else raw
    return text, calls


def _vectors_of(payload: dict, count: int) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("embed_bad_json")
    ordered: list[list[float] | None] = [None] * count
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index") or 0)
        except (TypeError, ValueError):
            continue
        raw = item.get("embedding")
        if isinstance(raw, list) and 0 <= index < count:
            ordered[index] = [float(value) for value in raw]
    if any(row is None for row in ordered):
        raise RuntimeError("embed_incomplete")
    return [row for row in ordered if row is not None]


async def _embed(texts: list[str]) -> list[list[float]]:
    payload = await _post("/embeddings", {"model": EMBED_MODEL, "input": texts})
    return _vectors_of(payload, len(texts))


async def intent_hint(text: str) -> str:
    """Local bge-m3 only. Failure leaves the model's own prose in place."""
    global _SAMPLE_VECTORS
    sentence = str(text or "").strip()
    if not sentence:
        return ""
    try:
        if _SAMPLE_VECTORS is None:
            flat = [sample for rows in INTENT_SAMPLES.values() for sample in rows]
            vectors = await _embed(flat)
            saved: dict[str, list[list[float]]] = {}
            cursor = 0
            for name, rows in INTENT_SAMPLES.items():
                saved[name] = vectors[cursor : cursor + len(rows)]
                cursor += len(rows)
            _SAMPLE_VECTORS = saved
        query = (await _embed([mask_pii(sentence[:500])]))[0]
    except Exception:
        log.warning("inbox intent embed skipped")
        return ""
    best_name = ""
    best_score = -1.0
    for name, rows in (_SAMPLE_VECTORS or {}).items():
        for row in rows:
            score = cosine(query, row)
            if score > best_score:
                best_score = score
                best_name = name
    if best_score < INTENT_THRESHOLD:
        return ""
    return best_name


def clear_intent_cache() -> None:
    global _SAMPLE_VECTORS
    _SAMPLE_VECTORS = None


def _history(thread: dict | None) -> list[dict]:
    rows = (thread or {}).get("messages") or []
    messages = []
    for msg in rows[-12:]:
        text = str(msg.get("text") or "").strip()
        if not text:
            continue
        role = "user" if msg.get("role") == "inbound" else "assistant"
        messages.append({"role": role, "content": text[:240]})
    return messages


def _media_note(thread: dict | None) -> str:
    for msg in reversed((thread or {}).get("messages") or []):
        if msg.get("role") != "inbound":
            continue
        kind = str(msg.get("mediaKind") or "").strip()
        label = {"image": "تصویر", "video": "ویدیو", "audio": "صدا"}.get(kind, "")
        return f"پیوست مشتری: {label}" if label else ""
    return ""


def _system(thread: dict | None) -> str:
    from app.services.settings_service import get_settings
    from app.services.voice_service import prompt_block

    cfg = get_settings()
    titles = [str(item.get("title") or "").strip() for item in _products()[:12]]
    titles = [title for title in titles if title]
    note = _media_note(thread)
    return (
        "تو فروشندهٔ همین فروشگاه هستی و در دایرکت جواب می‌دهی. فقط فارسی کوتاه بنویس.\n"
        "موجودی، قیمت، وضعیت سفارش و لینک پرداخت را فقط از ابزار بگیر. "
        "اگر چند ابزار لازم است، همه را در همان نوبت صدا بزن. "
        "اگر ابزار چیزی پیدا نکرد، همان را بگو و عدد یا لینک نساز.\n"
        f"{prompt_block()}\n"
        f"فروشگاه: {cfg.get('storeName') or ''} / {cfg.get('storeTagline') or ''}\n"
        f"نام کالاها: {'، '.join(titles) if titles else 'کاتالوگی ثبت نشده'}\n"
        f"{note}"
    ).strip()


def _catalog_line(item: dict) -> str:
    title = str(item.get("title") or "")
    row = tool_stock(title)
    colors = [str(color).strip() for color in (item.get("colors") or []) if str(color).strip()]
    sizes = str(item.get("sizes") or "").strip()
    products = row.get("products") if isinstance(row.get("products"), list) else []
    for product in products:
        if isinstance(product, dict):
            product["colors"] = colors
            product["sizes"] = sizes
    return json.dumps(row, ensure_ascii=False)


def _catalog_facts(reply: str) -> str:
    """Color, material words in the title, and size, so a matching reply skips the claims model."""
    folded = _norm(reply).replace("\u200c", "")
    lines = []
    for item in _products():
        title = str(item.get("title") or "")
        colors = [str(color).strip() for color in (item.get("colors") or []) if str(color).strip()]
        sizes = str(item.get("sizes") or "").strip()
        words = [word for word in _norm(title).replace("\u200c", "").split() if len(word) >= 3]
        keys = words + [_norm(color).replace("\u200c", "") for color in colors]
        if sizes:
            keys.append(_norm(sizes).replace("\u200c", ""))
        if any(key and key in folded for key in keys):
            lines.append(
                json.dumps({"title": title, "colors": colors, "sizes": sizes}, ensure_ascii=False)
            )
    return "\n".join(lines)


def _seed_stock(messages: list[dict], products: list[dict]) -> None:
    lines = [_catalog_line(item) for item in products]
    messages.append(
        {
            "role": "system",
            "content": "موجودی این کالاها از کاتالوگ آمده است.\n"
            + "\n".join(lines)
            + "\nجواب را از همین عددها، رنگ‌ها و اندازه‌ها بنویس و ابزار پرداخت را صدا نزن.",
        }
    )


def _fa_num(value: int) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _finish(reply: str, reason: str) -> str:
    text = str(reply or "").strip()
    emit_later(
        kind="inbox",
        surface="inbox",
        title="inbox-agent",
        status="handoff" if text == HANDOFF_LINE else "ready",
        payload={"tools": [], "reason": reason},
    )
    return text[:1000]


def _finish_handoff(thread: dict | None, reason: str) -> str:
    return _finish(_hand_off(thread, reason), reason)


_HANDOFF_MARKS = (
    "صاحب",
    "واقعی",
    "فروشنده",
    "مدیر",
    "عمده",
    "هوا",
    "شعر",
    "استقلال",
    "دلار",
    "لطیفه",
    "دیر جواب",
    "بد قول",
    "شکایت",
    "طرز حرف",
    "پشت گوش",
    "اعتماد",
    "کلاهبردار",
    "اینستاگرام",
    "رقیب",
    "دیجی",
    "جای دیگر",
    "فروشگاه دیگر",
    "مغازه",
    "آدرس",
    "مترو",
    "تحویل حضوری",
)
_PII_MARKS = ("[تلفن]", "[کارت]", "[شبا]", "[کد]", "[نشانی]")


def _item_price(item: dict) -> int:
    return int(item.get("finalPrice") or item.get("price") or 0)


def _item_stock(item: dict) -> int:
    return int(item.get("stock") or 0)


def _item_colors(item: dict) -> list[str]:
    return [str(color).strip() for color in (item.get("colors") or []) if str(color).strip()]


def _item_sizes(item: dict) -> str:
    return str(item.get("sizes") or "").strip()


def _catalog_sentence(sentence: str, products: list[dict]) -> str:
    folded = _norm(sentence)
    if "چه رنگی" in folded:
        named = {
            _norm(color)
            for item in products
            for color in _item_colors(item)
            if _norm(color) in folded
        }
        others: list[str] = []
        for item in _products():
            if _item_stock(item) <= 0:
                continue
            for color in _item_colors(item):
                if _norm(color) not in named and color not in others:
                    others.append(color)
        if others:
            return "رنگ‌های موجود: " + "، ".join(others) + "."
    if any(mark in folded for mark in ("رنگ دیگر", "غیر از")) and len(products) == 1:
        colors = _item_colors(products[0])
        title = str(products[0].get("title") or "")
        if len(colors) == 1:
            return f"{title} فقط رنگ {colors[0]} را دارد."
        if colors:
            return f"{title} این رنگ‌ها را دارد: " + "، ".join(colors) + "."
    if "ارزانترین" in folded:
        products = [min(products, key=_item_price)]
    qty = 2 if ("دو" in folded and "عدد" in folded) else 1
    want_price = any(mark in folded for mark in ("قیمت", "چند", "چقدر", "جمع", "ارزان"))
    lines = []
    for item in products:
        title = str(item.get("title") or "")
        stock = _item_stock(item)
        price = _item_price(item)
        colors = _item_colors(item)
        sizes = _item_sizes(item)
        if stock <= 0:
            line = f"{title} موجود نیست."
        else:
            line = f"{title} موجود است، {_fa_num(stock)} عدد."
        if want_price and price > 0:
            line += f" قیمت {_fa_num(price * qty)} تومان است."
        if colors and ("رنگ" in folded or any(_norm(color) in folded for color in colors)):
            line += " رنگ " + "، ".join(colors) + "."
        if sizes and ("سایز" in folded or "اندازه" in folded or _norm(sizes) in folded):
            line += f" اندازه {sizes}."
        lines.append(line)
    return " ".join(lines)


async def _known_reply(thread: dict | None, sentence: str) -> str | None:
    """Facts the shop already stores. The model is only for what is not stored."""
    folded = _norm(sentence)
    if "ارسال شد" in folded:
        return _finish_handoff(thread, "وضعیت سفارش نامشخص")
    if any(mark in folded for mark in _HANDOFF_MARKS):
        return _finish_handoff(thread, "نیاز به انسان")
    if "سفارش" in folded:
        order_ids = re.findall(r"\d{3,}", _digit_fold(sentence))
        if order_ids:
            row = tool_order_status(order_ids[0])
            if not row.get("ok"):
                return _finish("سفارش پیدا نشد.", "order")
            return _finish(f"وضعیت سفارش {row.get('id') or order_ids[0]}: {row.get('status') or ''}.", "order")
        if re.search(r"[A-Za-z]{3,}", sentence):
            return None
        return _finish("شماره سفارش را بگویید. اگر در فروشگاه نباشد می‌گویم سفارش پیدا نشد.", "order")
    products = _mentioned_products(sentence)
    if "تخفیف" in folded or "کمتر" in folded or ("ارزان" in folded and "ارزانترین" not in folded):
        if not products:
            return _finish_handoff(thread, "تخفیف ثبت نشده")
        bits = [
            f"قیمت {item.get('title') or ''} {_fa_num(_item_price(item))} تومان است."
            for item in products
            if _item_price(item) > 0
        ]
        bits.append("تخفیف ثبت نشده است.")
        return _finish(" ".join(bits), "price")
    if "لینک سایت" in folded and "پرداخت" not in folded:
        url = _public_shop_url()
        if not url:
            return _finish("نشانی عمومی این فروشگاه ثبت نشده.", "shop")
        return _finish(f"نشانی فروشگاه: {url}", "shop")
    if "عکس" in folded and not products:
        return _finish_handoff(thread, "کالا از عکس مشخص نیست")
    if _explicit_buy(sentence) and len(products) == 1:
        item = products[0]
        title = str(item.get("title") or "")
        if _item_stock(item) <= 0:
            return _finish(f"{title} موجود نیست.", "stock")
        qty = 2 if ("دو" in folded and "عدد" in folded) else 1
        try:
            result = await tool_payment_link(title, qty, thread=thread)
        except Exception:
            return _finish_handoff(thread, "خطای ابزار پرداخت")
        if not result.get("ok") or not str(result.get("payUrl") or "").strip():
            return _finish_handoff(thread, "خطای ابزار پرداخت")
        amount = _fa_num(int(result.get("amount") or 0))
        return _finish(f"لینک پرداخت {title}: {result['payUrl']} مبلغ {amount} تومان.", "pay")
    if products:
        return _finish(_catalog_sentence(sentence, products), "catalog")
    masked = mask_pii(sentence)
    if any(mark in masked for mark in _PII_MARKS):
        return _finish_handoff(thread, "اطلاعات خصوصی")
    if _amounts(sentence):
        return _finish_handoff(thread, "عدد نامجاز")
    return None


def _policy_reply(thread: dict | None, sentence: str) -> str | None:
    from app.services.sales_policy_service import fixed_reply

    fixed = fixed_reply(sentence)
    if fixed is None:
        return None
    reply = guard_output(fixed) if fixed.strip() else ""
    if not reply.strip():
        reply = _hand_off(thread, "سیاست ثبت نشده")
    emit_later(
        kind="inbox",
        surface="inbox",
        title="inbox-agent",
        status="handoff" if reply == HANDOFF_LINE else "ready",
        payload={"tools": [], "reason": "policy"},
    )
    return reply[:1000]


async def answer(customer_text: str, thread: dict | None = None) -> str | None:
    sentence = str(customer_text or "").strip()
    if not sentence:
        return None
    stored = _policy_reply(thread, sentence)
    if stored is not None:
        return stored
    known = await _known_reply(thread, sentence)
    if known is not None:
        return known
    started = time.monotonic()
    messages: list[dict] = [{"role": "system", "content": _system(thread)}, *_history(thread)]
    if not messages[-1:] or messages[-1].get("content") != sentence:
        messages.append({"role": "user", "content": sentence[:800]})
    nudged = ""
    used: list[str] = []
    pay_urls: list[str] = []
    number_retried = False
    force_retry = False
    rounds = 0
    allow_payment = _explicit_buy(sentence)
    mentioned = _mentioned_products(sentence)
    if mentioned and not allow_payment:
        _seed_stock(messages, mentioned[:3])
    try:
        while rounds < MAX_ROUNDS or force_retry:
            force_retry = False
            rounds += 1
            if rounds > MAX_ROUNDS + 1:
                break
            left = INBOX_TURN_BUDGET - (time.monotonic() - started)
            if left < 1:
                reply = _hand_off(thread, "مهلت مدل")
                emit_later(
                    kind="inbox",
                    surface="inbox",
                    title="inbox-agent",
                    status="handoff",
                    payload={"tools": used, "reason": "مهلت مدل"},
                )
                return reply
            text, calls = await _complete(messages, allow_payment=allow_payment, timeout=left)
            if not calls:
                blob_now = _tool_blob(messages)
                grounded = bool(_amounts(text) & _amounts(blob_now)) or (
                    "موجود" in text and '"stock"' in blob_now
                )
                if not nudged and not used and not grounded:
                    hinted = await intent_hint(sentence)
                    if hinted:
                        nudged = hinted
                        messages.append(
                            {
                                "role": "system",
                                "content": f"این پیام به ابزار {hinted} می‌خورد. همان را صدا بزن و جواب را از نتیجه‌اش بنویس.",
                            }
                        )
                        continue
                blob = _tool_blob(messages)
                reply = guard_output(text)
                if not _numbers_ok(mask_pii(reply), blob):
                    if not number_retried:
                        number_retried = True
                        force_retry = True
                        messages.append({"role": "system", "content": _number_reminder(blob)})
                        continue
                    reply = _hand_off(thread, "عدد نامجاز")
                    emit_later(
                        kind="inbox",
                        surface="inbox",
                        title="inbox-agent",
                        status="handoff",
                        payload={"tools": used, "reason": "numbers"},
                    )
                    return reply
                reply = _fix_links(reply, pay_urls)
                facts = "\n".join(part for part in (blob, _catalog_facts(reply)) if part)
                left = INBOX_TURN_BUDGET - (time.monotonic() - started)
                if left < 1:
                    reply = _hand_off(thread, "مهلت مدل")
                    emit_later(
                        kind="inbox",
                        surface="inbox",
                        title="inbox-agent",
                        status="handoff",
                        payload={"tools": used, "reason": "مهلت مدل"},
                    )
                    return reply
                reply = await asyncio.wait_for(_claims(reply, facts), timeout=left)
                for url in pay_urls:
                    if url and url not in reply:
                        reply = f"{reply}\n{url}".strip()
                if not str(reply or "").strip():
                    reply = _hand_off(thread, "جواب خالی")
                emit_later(
                    kind="inbox",
                    surface="inbox",
                    title="inbox-agent",
                    status="handoff" if reply == HANDOFF_LINE else "ready",
                    payload={"tools": used, "nudge": nudged},
                )
                return reply[:1000]
            messages.append(
                {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                used.append(call["name"])
                if call["name"] == "payment_link" and not allow_payment:
                    result = {"ok": False, "error": "مشتری خرید را نخواسته"}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    continue
                try:
                    result = await run_tool(call["name"], call["arguments"], thread=thread)
                except Exception as exc:
                    reason = "خطای ابزار پرداخت" if call["name"] == "payment_link" else "خطای ابزار"
                    log.warning("inbox tool failed: %s %s", call["name"], type(exc).__name__)
                    reply = _hand_off(thread, reason)
                    emit_later(
                        kind="inbox",
                        surface="inbox",
                        title="inbox-agent",
                        status="handoff",
                        payload={"tools": used, "reason": reason, "errorClass": type(exc).__name__},
                    )
                    return reply
                url = str(result.get("payUrl") or "").strip()
                if url:
                    pay_urls.append(url)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
    except Exception as exc:
        reason = "مهلت مدل" if _is_timeout(exc) else "خطای پاسخ"
        log.warning("inbox agent failed: %s", type(exc).__name__)
        reply = _hand_off(thread, reason)
        emit_later(
            kind="inbox",
            surface="inbox",
            title="inbox-agent",
            status="handoff",
            payload={"tools": used, "reason": reason, "errorClass": type(exc).__name__},
        )
        return reply
    reply = _hand_off(thread, "دورها تمام شد")
    emit_later(
        kind="inbox",
        surface="inbox",
        title="inbox-agent",
        status="handoff",
        payload={"tools": used, "nudge": nudged, "reason": "دورها تمام شد"},
    )
    return reply
