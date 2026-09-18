from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.services.observe_client import emit_later, llm_headers

log = logging.getLogger("sozan.llm")

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE = re.compile(r"^\s*```(?:json)?|```\s*$", re.MULTILINE)
FA_CHAR = re.compile(r"[\u0600-\u06FF]")
LATIN_CHAR = re.compile(r"[A-Za-z]")
STALE_ASSISTANT = ("ویرایش فروشگاه نیست", "المان را در پیش‌نمایش لمس", "The user is")
CLOUD_UA = "curl/8.5.0"
VOICE_SURFACES = frozenset({"voice", "inbox"})
PINNED_SURFACES = frozenset({"studio"})
CLOUD_SURFACES = frozenset({"factory"})
GPU1_LOCAL = frozenset(
    {"qwen3.8-27b", "ornith-1.5-35b", "muse-glimmer-30b", "gpt-oss-20b", "qwen3-coder-next"}
)

LLM_UNREACHABLE = {
    "reply": "مدل پاسخ نداد. پیام را دوباره بفرست.",
    "error": "llm_unreachable",
}
LLM_BAD_JSON = {
    "reply": "مدل پاسخ خوانا نداد. پیام را کوتاه‌تر دوباره بفرست.",
    "error": "llm_bad_json",
}


def parse_json_object(text: str) -> dict:
    cleaned = THINK_BLOCK.sub("", text or "").strip()
    cleaned = FENCE.sub("", cleaned).strip()
    for start, ch in enumerate(cleaned):
        if ch != "{":
            continue
        end = cleaned.rfind("}")
        if end <= start:
            continue
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data:
            return data
    return {}


def _persian_enough(text: str) -> bool:
    blob = (text or "").strip()
    if len(blob) < 8:
        return False
    fa = len(FA_CHAR.findall(blob))
    if fa < 4:
        return False
    return fa >= len(LATIN_CHAR.findall(blob))


def spoken_model_reply(text: str) -> str:
    parsed = parse_json_object(text)
    reply = str(parsed.get("reply") or "").strip()
    if _persian_enough(reply):
        return reply[:2000]
    cleaned = FENCE.sub("", THINK_BLOCK.sub("", text or "")).strip()
    if _persian_enough(cleaned):
        return cleaned[:2000]
    return LLM_BAD_JSON["reply"]


def _swap_base() -> str:
    url = settings.local_llm_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url


def _cloud_token() -> str:
    return (settings.cloud_llm_token or "").strip()


def _cloud_proxy() -> str | None:
    raw = (settings.cloud_llm_proxy or settings.channel_proxy or "").strip()
    return raw or None


def route_for_surface(surface: str) -> dict:
    override = _routing_override(surface)
    if override and not _rejects_pinned_gpu1(surface, override):
        return override
    if surface in CLOUD_SURFACES and settings.cloud_llm_url and _cloud_token():
        return {
            "kind": "cloud",
            "url": settings.cloud_llm_url.rstrip("/"),
            "model": settings.cloud_llm_model,
            "token": _cloud_token(),
            "proxy": _cloud_proxy(),
            "source": "default",
        }
    model = _default_local_model(surface)
    return {
        "kind": "local",
        "url": settings.local_llm_url.rstrip("/"),
        "model": model,
        "token": settings.local_llm_token,
        "proxy": None,
        "source": "default",
    }


def _default_local_model(surface: str) -> str:
    if surface in PINNED_SURFACES:
        return (settings.studio_llm_model or "qwen3.5-9b").strip() or "qwen3.5-9b"
    if surface in VOICE_SURFACES:
        return settings.local_llm_model
    return settings.chat_llm_model


def _rejects_pinned_gpu1(surface: str, override: dict) -> bool:
    if surface not in PINNED_SURFACES:
        return False
    if str(override.get("kind") or "") != "local":
        return False
    model = str(override.get("model") or "").strip()
    if model not in GPU1_LOCAL:
        return False
    log.warning("llm routing ignored GPU1 model %s for pinned surface %s", model, surface)
    return True


def _routing_override(surface: str) -> dict | None:
    try:
        from app.services import llm_routing_service
        import os

        row = llm_routing_service.get(surface)
    except Exception:
        return None
    if not row:
        return None
    kind = str(row.get("kind") or "local")
    model = str(row.get("model") or "").strip()
    if not model:
        return None
    if kind == "cloud":
        provider = llm_routing_service.provider(str(row.get("provider") or ""))
        base = str(provider.get("base_url") or row.get("base_url") or settings.cloud_llm_url or "").rstrip("/")
        key_env = str(provider.get("key_env") or "CLOUD_LLM_TOKEN")
        token = (os.environ.get(key_env) or _cloud_token()).strip()
        if not base or not token:
            log.warning("llm routing cloud override missing base/token for %s", surface)
            return None
        return {
            "kind": "cloud",
            "url": base,
            "model": model,
            "token": token,
            "proxy": _cloud_proxy(),
            "source": "override",
        }
    return {
        "kind": "local",
        "url": settings.local_llm_url.rstrip("/"),
        "model": model,
        "token": settings.local_llm_token,
        "proxy": None,
        "source": "override",
    }


def _choice_text(payload: dict) -> str:
    msg = ((payload.get("choices") or [{}])[0].get("message") or {})
    content = str(msg.get("content") or "").strip()
    if content:
        return content
    return str(msg.get("reasoning_content") or msg.get("reasoning") or "").strip()


async def _running_models() -> set[str] | None:
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            res = await client.get(f"{_swap_base()}/running")
            res.raise_for_status()
            rows = res.json().get("running") or []
    except Exception:
        return None
    return {str(row.get("model")) for row in rows if row.get("model")}


async def _unload_model(model: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            await client.post(f"{_swap_base()}/api/models/unload/{model}")
    except Exception as exc:
        log.warning("llm unload %s failed: %s", model, type(exc).__name__)


async def _ensure_gpu1(model: str) -> None:
    if model not in GPU1_LOCAL:
        return
    found = await _running_models()
    if found is None:
        return
    for other in (found & GPU1_LOCAL) - {model}:
        await _unload_model(other)


def _classify_llm_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "unreachable"
    if isinstance(exc, httpx.HTTPStatusError):
        code = int(getattr(exc.response, "status_code", 0) or 0)
        if code == 429:
            return "rate-limit"
        if code >= 500:
            return "http-5xx"
        if code >= 400:
            return f"http-{code}"
    return "llm_unreachable"


def _last_user_prompt(messages: list[dict]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "") == "user":
            return str(item.get("content") or "")[:240]
    return ""


def report_llm_fail(
    *,
    surface: str,
    error_class: str,
    detail: str = "",
    request_id: str = "",
    prompt: str = "",
) -> None:
    emit_later(
        kind="llm",
        title="chat-failed",
        surface=surface,
        status="failed",
        stage=error_class,
        payload={
            "errorClass": error_class,
            "detail": (detail or "")[:400],
            "requestId": request_id,
            "prompt": (prompt or "")[:240],
        },
    )


async def _chat_completion(*, messages: list[dict], temperature: float, max_tokens: int, surface: str) -> str:
    route = route_for_surface(surface)
    body = {
        "model": route["model"],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    headers = {"Content-Type": "application/json", **llm_headers(surface=surface)}
    if route.get("source"):
        headers["X-Sozan-Route"] = str(route["source"])
    request_id = str(headers.get("X-Sozan-Request") or "")
    timeout = 180 if max_tokens > 700 else 120
    body["think"] = False
    if route["kind"] == "cloud":
        headers["Authorization"] = f"Bearer {route['token']}"
        headers["User-Agent"] = CLOUD_UA
        timeout = max(timeout, 90)
    else:
        body["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
        body["reasoning_format"] = "none"
        if route["token"]:
            headers["Authorization"] = f"Bearer {route['token']}"
        await _ensure_gpu1(route["model"])
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=route["proxy"]) as client:
                res = await client.post(f"{route['url']}/chat/completions", json=body, headers=headers)
                res.raise_for_status()
                return _choice_text(res.json())
        except Exception as exc:
            last_exc = exc
            klass = _classify_llm_error(exc)
            if attempt == 1 and klass in {"http-5xx", "unreachable"}:
                log.warning("llm %s retry after %s", surface, klass)
                import asyncio

                await asyncio.sleep(1.2)
                continue
            log.warning("llm %s failed: %s: %s", surface, type(exc).__name__, str(exc)[:200])
            report_llm_fail(
                surface=surface,
                error_class=klass,
                detail=f"{type(exc).__name__}: {str(exc)[:200]}",
                request_id=request_id,
                prompt=_last_user_prompt(messages),
            )
            raise
    raise last_exc or RuntimeError("llm")


async def complete_json(system: str, user: str, *, surface: str = "llm", max_tokens: int = 700) -> dict:
    try:
        text = await _chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            surface=surface,
        )
    except Exception:
        return dict(LLM_UNREACHABLE)
    data = parse_json_object(text)
    if not data:
        report_llm_fail(
            surface=surface,
            error_class="bad-json",
            detail="empty or unreadable model json",
            prompt=user[:240],
        )
        return dict(LLM_BAD_JSON)
    return data


def visible_chat_turns(turns: list[dict], *, limit: int = 12) -> list[dict]:
    messages: list[dict] = []
    for turn in turns[-limit:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        if role == "user" and re.search(r"https?://|[A-Fa-f0-9]{24,}", text):
            continue
        if role == "assistant" and (
            any(token in text for token in STALE_ASSISTANT)
            or (len(text) > 40 and LATIN_CHAR.search(text) and not _persian_enough(text))
        ):
            continue
        messages.append({"role": role, "content": text[:800]})
    return messages


async def complete_chat(*, system: str, turns: list[dict], surface: str = "shop") -> str:
    messages = [{"role": "system", "content": system}, *visible_chat_turns(turns)]
    if len(messages) < 2:
        return LLM_UNREACHABLE["reply"]
    try:
        text = await _chat_completion(messages=messages, temperature=0.4, max_tokens=700, surface=surface)
    except Exception:
        return LLM_UNREACHABLE["reply"]
    reply = spoken_model_reply(text)
    if reply == LLM_BAD_JSON["reply"]:
        report_llm_fail(
            surface=surface,
            error_class="bad-json",
            detail="unreadable chat reply",
            prompt=_last_user_prompt(messages),
        )
    return reply
