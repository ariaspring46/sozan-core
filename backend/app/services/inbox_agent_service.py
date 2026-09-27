"""Local direct-message agent.

Customer text stays on the home llama-swap (qwen3.5-9b). It never uses the
Arvan route. Stock, order status, and payment links come from existing
services. Local bge-m3 only nudges a tool when the model answered with none.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
from app.services.llm import ARVAN_HOST_SUFFIX, LLM_BAD_JSON, _emit_usage, _persian_enough, spoken_model_reply
from app.services.observe_client import emit_later
from app.services.persian_text import guard_output
from app.services.router_embed import cosine

log = logging.getLogger("sozan.inbox.agent")

AGENT_MODEL = "qwen3.5-9b"
EMBED_MODEL = "bge-m3"
MAX_ROUNDS = 3
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


def _tools() -> list[dict]:
    return [
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


def _norm(text: str) -> str:
    return str(text or "").replace("ي", "ی").replace("ك", "ک").strip().lower()


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


def _agent_body(messages: list[dict], model: str) -> dict:
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": 500,
        "messages": messages,
        "tools": _tools(),
        "tool_choice": "auto",
    }
    if model == AGENT_MODEL:
        body["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
        body["reasoning_format"] = "none"
    return body


async def _post_inbox_cloud(messages: list[dict], primary: Exception) -> dict:
    from app.services.llm import inbox_cloud_route

    route = inbox_cloud_route()
    url = str((route or {}).get("url") or "")
    token = str((route or {}).get("token") or "")
    model = str((route or {}).get("model") or "")
    if not url or not token or not model or _cloud_base(url):
        raise primary
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, proxy=None) as client:
        res = await client.post(f"{url}/chat/completions", json=_agent_body(messages, model), headers=headers)
        res.raise_for_status()
        payload = res.json()
    if not isinstance(payload, dict):
        raise RuntimeError("inbox_bad_json")
    return payload


async def _complete(messages: list[dict]) -> tuple[str, list[dict]]:
    model = AGENT_MODEL
    try:
        payload = await _post("/chat/completions", _agent_body(messages, model))
    except Exception as exc:
        payload = await _post_inbox_cloud(messages, exc)
        model = str(inbox_cloud_model() or model)
    _emit_usage(surface="inbox", model=model, payload=payload)
    return _calls_from(payload)


def inbox_cloud_model() -> str:
    from app.services.llm import inbox_cloud_route

    route = inbox_cloud_route()
    return str((route or {}).get("model") or "")


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
        query = (await _embed([sentence[:500]]))[0]
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
    for msg in rows[-8:]:
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
        "اگر ابزار چیزی پیدا نکرد، همان را بگو و عدد یا لینک نساز.\n"
        f"{prompt_block()}\n"
        f"فروشگاه: {cfg.get('storeName') or ''} / {cfg.get('storeTagline') or ''}\n"
        f"نام کالاها: {'، '.join(titles) if titles else 'کاتالوگی ثبت نشده'}\n"
        f"{note}"
    ).strip()


async def answer(customer_text: str, thread: dict | None = None) -> str | None:
    sentence = str(customer_text or "").strip()
    if not sentence:
        return None
    if _cloud_base(local_base()):
        emit_later(kind="inbox", surface="inbox", title="inbox-agent", status="refused", payload={"errorClass": "cloud"})
        return None
    messages: list[dict] = [{"role": "system", "content": _system(thread)}, *_history(thread)]
    if not messages[-1:] or messages[-1].get("content") != sentence:
        messages.append({"role": "user", "content": sentence[:800]})
    nudged = ""
    used: list[str] = []
    pay_urls: list[str] = []
    try:
        for _round in range(MAX_ROUNDS):
            text, calls = await _complete(messages)
            if not calls:
                if not nudged and not used:
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
                reply = guard_output(text)
                for url in pay_urls:
                    if url and url not in reply:
                        reply = f"{reply}\n{url}".strip()
                emit_later(
                    kind="inbox",
                    surface="inbox",
                    title="inbox-agent",
                    status="ready" if reply else "empty",
                    payload={"tools": used, "nudge": nudged},
                )
                return reply[:1000] or None
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
                result = await run_tool(call["name"], call["arguments"], thread=thread)
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
        log.warning("inbox agent failed: %s", type(exc).__name__)
        emit_later(
            kind="inbox",
            surface="inbox",
            title="inbox-agent",
            status="failed",
            payload={"errorClass": type(exc).__name__},
        )
        return None
    emit_later(
        kind="inbox",
        surface="inbox",
        title="inbox-agent",
        status="empty",
        payload={"tools": used, "nudge": nudged},
    )
    return None
