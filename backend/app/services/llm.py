from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

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
SHOP_CLOUD_SURFACES = frozenset({"shop", "shop-edit", "router"})
CLOUD_PRIMARY_SURFACES = frozenset({"shop", "shop-edit", "studio", "router"})
ARVAN_HOST_SUFFIX = "arvancloudai.ir"
CLOUD_PRIMARY_TIMEOUT = 120
PRIMARY_CLOUD_TIMEOUT = 10
FALLBACK_CLOUD_TIMEOUT = 45
DEFAULT_SHOP_CLOUD_MODEL = "DeepSeek-V4-Pro"
DEFAULT_STUDIO_CLOUD_MODEL = "Gemini-3.1-Flash-Lite-Preview"
GPU1_LOCAL = frozenset(
    {"qwen3.8-27b", "ornith-1.5-35b", "gpt-oss-20b", "qwen3-coder-next"}
)
# While the site-builder holds GPU1 (ACTIVE build lock or a GPU1 phase in
# queue/phase.json) the hub must not evict its worker; it shares 27B when that
# is what is loaded, else falls back to the always-on 9b.
FACTORY_GPU1_PHASES = frozenset({"TRANSITION", "DESIGN_27B", "DESIGN", "CODE_LIGHT", "CODE_HEAVY", "SUPERVISE", "COMFY"})
FACTORY_PHASE_MAX_AGE_SEC = 900
SHARED_GPU1_MODEL = "qwen3.8-27b"
ALWAYS_ON_MODEL = "qwen3.5-9b"

LLM_UNREACHABLE = {
    "reply": "مدل پاسخ نداد. پیام را دوباره بفرست.",
    "error": "llm_unreachable",
}
LLM_BAD_JSON = {
    "reply": "مدل پاسخ خوانا نداد. پیام را کوتاه‌تر دوباره بفرست.",
    "error": "llm_bad_json",
}
ROUTER_MAX_TOKENS = 150


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


def _str_setting(value: object, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip() or default
    return default


def _cloud_token() -> str:
    return _str_setting(settings.cloud_llm_token)


def _studio_cloud_token() -> str:
    return _str_setting(getattr(settings, "studio_cloud_token", ""))


def _cloud_proxy() -> str | None:
    raw = _str_setting(settings.cloud_llm_proxy) or _str_setting(settings.channel_proxy)
    return raw or None


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_arvan_url(url: str) -> bool:
    host = _host_of(url)
    return host == ARVAN_HOST_SUFFIX or host.endswith(f".{ARVAN_HOST_SUFFIX}")


def _proxy_for_url(url: str) -> str | None:
    host = _host_of(url)
    if _is_arvan_url(url) or host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return None
    return _cloud_proxy()


def _openrouter_token() -> str:
    return os.environ.get("open_router_api_token", "").strip()


def _route_token(url: str, explicit: str) -> str:
    if "openrouter.ai" in _host_of(url):
        named = _openrouter_token()
        if named:
            return named
    return explicit


def _openrouter_extra_body(url: str) -> dict:
    if "openrouter.ai" not in _host_of(url):
        return {}
    raw = os.environ.get("CLOUD_LLM_EXTRA_BODY", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _decorate_cloud_body(body: dict, route: dict) -> None:
    url = str(route.get("url") or "")
    if route.get("kind") == "cloud" and _is_arvan_url(url):
        body["think"] = False
    if route.get("kind") != "cloud":
        return
    for key, value in _openrouter_extra_body(url).items():
        if key == "think":
            continue
        body[key] = value


def _fallback_cloud_route() -> dict | None:
    url = os.environ.get("CLOUD_LLM_FALLBACK_URL", "").strip().rstrip("/")
    model = os.environ.get("CLOUD_LLM_FALLBACK_MODEL", "").strip()
    token = os.environ.get("CLOUD_LLM_FALLBACK_TOKEN", "").strip()
    if not url or not model or not token:
        return None
    auth = os.environ.get("CLOUD_LLM_FALLBACK_AUTH", "").strip() or "Bearer"
    return {
        "kind": "cloud",
        "url": url,
        "model": model,
        "token": _route_token(url, token),
        "proxy": _proxy_for_url(url),
        "auth": auth,
        "source": "fallback",
        "cloud": "fallback",
    }


def _emit_cloud_fallback(*, surface: str, reason: str, requested: str, used: str) -> None:
    emit_later(
        kind="llm",
        title="cloud-fallback",
        surface=surface,
        status="fallback",
        stage="cloud-fallback",
        payload={"requested": requested, "used": used, "reason": reason},
    )


def _auth_scheme(value: object) -> str:
    return _str_setting(value, "Bearer") or "Bearer"


def _shop_cloud_route(*, source: str = "default") -> dict | None:
    url = _str_setting(settings.cloud_llm_url).rstrip("/")
    token = _cloud_token()
    if not url or not token:
        return None
    return {
        "kind": "cloud",
        "url": url,
        "model": _str_setting(settings.cloud_llm_model, DEFAULT_SHOP_CLOUD_MODEL) or DEFAULT_SHOP_CLOUD_MODEL,
        "token": _route_token(url, token),
        "proxy": _proxy_for_url(url),
        "auth": _auth_scheme(getattr(settings, "cloud_llm_auth", "Bearer")),
        "source": source,
        "cloud": "shop",
    }


def _studio_cloud_route(*, source: str = "default") -> dict | None:
    url = _str_setting(getattr(settings, "studio_cloud_url", "")).rstrip("/")
    token = _studio_cloud_token()
    if not url or not token:
        return None
    return {
        "kind": "cloud",
        "url": url,
        "model": _str_setting(getattr(settings, "studio_cloud_model", ""), DEFAULT_STUDIO_CLOUD_MODEL)
        or DEFAULT_STUDIO_CLOUD_MODEL,
        "token": _route_token(url, token),
        "proxy": _proxy_for_url(url),
        "auth": _auth_scheme(getattr(settings, "studio_cloud_auth", "Bearer")),
        "source": source,
        "cloud": "studio",
    }


def _local_default_route(surface: str) -> dict:
    return {
        "kind": "local",
        "url": _str_setting(settings.local_llm_url, "http://127.0.0.1:9292/v1").rstrip("/"),
        "model": _default_local_model(surface),
        "token": _str_setting(settings.local_llm_token),
        "proxy": None,
        "auth": "Bearer",
        "source": "default",
    }


def route_for_surface(surface: str) -> dict:
    override = _routing_override(surface)
    if override and not _rejects_pinned_gpu1(surface, override):
        return override
    if surface in CLOUD_SURFACES:
        cloud = _shop_cloud_route()
        if cloud:
            return cloud
    if surface in SHOP_CLOUD_SURFACES:
        cloud = _shop_cloud_route()
        if cloud:
            return cloud
    if surface in PINNED_SURFACES:
        cloud = _studio_cloud_route()
        if cloud:
            return cloud
    return _local_default_route(surface)


def _default_local_model(surface: str) -> str:
    if surface in PINNED_SURFACES:
        return _str_setting(settings.studio_llm_model, "qwen3.5-9b") or "qwen3.5-9b"
    if surface in VOICE_SURFACES:
        return _str_setting(settings.local_llm_model) or "qwen3.8-27b"
    return _str_setting(settings.chat_llm_model) or "qwen3.8-27b"


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
            "token": _route_token(base, token),
            "proxy": _proxy_for_url(base),
            "auth": _auth_scheme(getattr(settings, "cloud_llm_auth", "Bearer")),
            "source": "override",
        }
    return {
        "kind": "local",
        "url": _str_setting(settings.local_llm_url, "http://127.0.0.1:9292/v1").rstrip("/"),
        "model": model,
        "token": _str_setting(settings.local_llm_token),
        "proxy": None,
        "auth": "Bearer",
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


def _factory_queue() -> Path:
    return Path(settings.site_builder_dir) / "queue"


def _pid_alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)  # type: ignore[arg-type]
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _phase_age_sec(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return max(0.0, time.time() - float(raw))
    except (TypeError, ValueError):
        pass
    try:
        stamp = time.mktime(time.strptime(str(raw), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None
    return max(0.0, time.time() - stamp)


def factory_holds_gpu1() -> str:
    """Why the site-builder owns GPU1 right now ('' when it does not).

    Signals: queue/fastpath/ACTIVE with a live pid (a build is running), or
    queue/phase.json in a GPU1 phase that was updated recently."""
    queue = _factory_queue()
    try:
        lock = json.loads((queue / "fastpath" / "ACTIVE").read_text(encoding="utf-8"))
        if str(lock.get("status") or "") == "running" and _pid_alive(lock.get("pid")):
            return f"build:{lock.get('id') or ''}"
    except (OSError, ValueError, TypeError):
        pass
    try:
        state = json.loads((queue / "phase.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    phase = str(state.get("phase") or "").upper()
    if phase not in FACTORY_GPU1_PHASES:
        return ""
    age = _phase_age_sec(state.get("updatedAt"))
    if age is None or age > FACTORY_PHASE_MAX_AGE_SEC:
        return ""
    return f"phase:{phase}"


async def _ensure_gpu1(model: str) -> str:
    """Make `model` usable on GPU1; returns the model to actually call.

    Evicts other GPU1 workers only when the factory is idle. While a build
    holds GPU1 the hub shares qwen3.8-27b if that is loaded, else qwen3.5-9b."""
    if model not in GPU1_LOCAL:
        return model
    found = await _running_models()
    if found is None:
        return model
    others = (found & GPU1_LOCAL) - {model}
    if not others:
        return model
    holder = factory_holds_gpu1()
    if not holder:
        for other in others:
            await _unload_model(other)
        return model
    pick = SHARED_GPU1_MODEL if SHARED_GPU1_MODEL in found else ALWAYS_ON_MODEL
    log.warning("llm gpu1 held by factory (%s); %s -> %s", holder, model, pick)
    emit_later(
        kind="llm",
        title="gpu1-busy",
        surface="llm",
        status="fallback",
        stage="gpu1-busy",
        payload={"holder": holder, "requested": model, "used": pick, "loaded": sorted(found & GPU1_LOCAL)},
    )
    return pick


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


def _usage_counts(payload: dict) -> dict[str, int]:
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    if not isinstance(usage, dict):
        return {"promptTokens": 0, "completionTokens": 0}
    try:
        prompt = int(usage.get("prompt_tokens") or 0)
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        completion = 0
    return {"promptTokens": max(0, prompt), "completionTokens": max(0, completion)}


def _emit_usage(*, surface: str, model: str, payload: dict, latency_ms: float = 0) -> dict:
    counts = _usage_counts(payload)
    usage = payload.get("usage") if isinstance(payload, dict) else {}
    cost = None
    if isinstance(usage, dict) and usage.get("cost") is not None:
        try:
            cost = float(usage.get("cost"))
        except (TypeError, ValueError):
            cost = None
    provider = str(payload.get("provider") or "") if isinstance(payload, dict) else ""
    observed = {
        "promptTokens": counts["promptTokens"],
        "completionTokens": counts["completionTokens"],
        "model": model or "",
        "provider": provider,
        "latencyMs": int(latency_ms),
    }
    if cost is not None:
        observed["cost"] = cost
    emit_later(kind="llm", title="llm-usage", surface=surface, status="ok", payload=observed)
    counts["provider"] = provider
    counts["latencyMs"] = int(latency_ms)
    if cost is not None:
        counts["cost"] = cost
    return counts


async def _complete_with_route(
    route: dict,
    *,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    surface: str,
    timeout_override: float | None = None,
    attempts: int = 2,
    report: bool = True,
) -> str:
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
    if route["kind"] != "cloud":
        body["think"] = False
    _decorate_cloud_body(body, route)
    if timeout_override is not None:
        timeout = timeout_override
    if route["kind"] == "cloud":
        scheme = _auth_scheme(route.get("auth"))
        headers["Authorization"] = f"{scheme} {route['token']}"
        headers["User-Agent"] = CLOUD_UA
        if timeout_override is None and surface in CLOUD_PRIMARY_SURFACES:
            timeout = CLOUD_PRIMARY_TIMEOUT
        elif timeout_override is None:
            timeout = max(timeout, 90)
    else:
        body["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
        body["reasoning_format"] = "none"
        if route["token"]:
            headers["Authorization"] = f"Bearer {route['token']}"
        body["model"] = await _ensure_gpu1(route["model"])
    last_exc: Exception | None = None
    started = time.perf_counter()
    for attempt in range(1, max(1, attempts) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=route["proxy"]) as client:
                res = await client.post(f"{route['url']}/chat/completions", json=body, headers=headers)
                res.raise_for_status()
                data = res.json()
                latency_ms = (time.perf_counter() - started) * 1000
                _emit_usage(
                    surface=surface,
                    model=str(route.get("model") or ""),
                    payload=data if isinstance(data, dict) else {},
                    latency_ms=latency_ms,
                )
                return _choice_text(data)
        except Exception as exc:
            last_exc = exc
            klass = _classify_llm_error(exc)
            if attempt < attempts and klass in {"http-5xx", "unreachable"}:
                log.warning("llm %s retry after %s", surface, klass)
                import asyncio

                await asyncio.sleep(1.2)
                continue
            log.warning("llm %s failed: %s: %s", surface, type(exc).__name__, str(exc)[:200])
            if report:
                report_llm_fail(
                    surface=surface,
                    error_class=klass,
                    detail=f"{type(exc).__name__}: {str(exc)[:200]}",
                    request_id=request_id,
                    prompt=_last_user_prompt(messages),
                )
            raise
    raise last_exc or RuntimeError("llm")


async def _chat_completion(*, messages: list[dict], temperature: float, max_tokens: int, surface: str) -> str:
    route = route_for_surface(surface)
    if route.get("kind") != "cloud":
        return await _complete_with_route(
            route,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            surface=surface,
        )
    fallback = _fallback_cloud_route()
    chained = bool(fallback) and str(fallback.get("url") or "") != str(route.get("url") or "")
    if chained:
        hops: list[tuple[dict, float, int]] = [
            (route, PRIMARY_CLOUD_TIMEOUT, 1),
            (fallback, FALLBACK_CLOUD_TIMEOUT, 2),
        ]
        allow_local = surface in CLOUD_PRIMARY_SURFACES
    else:
        primary_timeout = CLOUD_PRIMARY_TIMEOUT if surface in CLOUD_PRIMARY_SURFACES else 120
        hops = [(route, primary_timeout, 2)]
        allow_local = surface in CLOUD_PRIMARY_SURFACES and surface != "router"
    last_exc: Exception | None = None
    for index, (hop, timeout, attempts) in enumerate(hops):
        final_hop = index == len(hops) - 1 and not allow_local
        try:
            return await _complete_with_route(
                hop,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                surface=surface,
                timeout_override=timeout,
                attempts=attempts,
                report=final_hop,
            )
        except Exception as exc:
            last_exc = exc
            if final_hop:
                raise
            nxt = _local_default_route(surface) if index == len(hops) - 1 else hops[index + 1][0]
            _emit_cloud_fallback(
                surface=surface,
                reason=_classify_llm_error(exc),
                requested=str(hop.get("model") or ""),
                used=str(nxt.get("model") or ""),
            )
    local = _local_default_route(surface)
    log.warning("llm %s cloud failed; fallback local %s", surface, local.get("model"))
    try:
        return await _complete_with_route(
            local,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            surface=surface,
        )
    except Exception:
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


def _skip_user_turn(text: str, *, keep_links: bool) -> bool:
    has_url = bool(re.search(r"https?://", text))
    has_secret = bool(re.search(r"[A-Fa-f0-9]{24,}", text))
    if keep_links and has_url:
        return False
    return has_url or has_secret


def visible_chat_turns(turns: list[dict], *, limit: int = 12, keep_links: bool = False) -> list[dict]:
    messages: list[dict] = []
    for turn in turns[-limit:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        if role == "user" and _skip_user_turn(text, keep_links=keep_links):
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


def _tool_result(route: dict, payload: dict, counts: dict) -> dict:
    choice = (payload.get("choices") or [{}])[0] if isinstance(payload, dict) else {}
    msg = (choice.get("message") or {}) if isinstance(choice, dict) else {}
    finish = str(choice.get("finish_reason") or "") if isinstance(choice, dict) else ""
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
        calls.append({"id": str(raw.get("id") or ""), "name": name, "arguments": args})
    return {
        "text": str(msg.get("content") or "").strip(),
        "tool_calls": calls,
        "usage": counts,
        "finish_reason": finish,
        "provider": str(counts.get("provider") or ""),
        "model": str(route.get("model") or ""),
        "latencyMs": int(counts.get("latencyMs") or 0),
    }


async def _tools_once(
    route: dict,
    *,
    messages: list[dict],
    tools: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> dict:
    body = {
        "model": route["model"],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    headers = {"Content-Type": "application/json", **llm_headers(surface="router")}
    if route["kind"] != "cloud":
        body["think"] = False
        body["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
        body["reasoning_format"] = "none"
        if route.get("token"):
            headers["Authorization"] = f"Bearer {route['token']}"
        body["model"] = await _ensure_gpu1(route["model"])
    else:
        _decorate_cloud_body(body, route)
        scheme = _auth_scheme(route.get("auth"))
        headers["Authorization"] = f"{scheme} {route['token']}"
        headers["User-Agent"] = CLOUD_UA
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=route.get("proxy")) as client:
        res = await client.post(f"{route['url']}/chat/completions", json=body, headers=headers)
        res.raise_for_status()
        payload = res.json()
    counts = _emit_usage(
        surface="router",
        model=str(body.get("model") or route.get("model") or ""),
        payload=payload if isinstance(payload, dict) else {},
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return _tool_result(route, payload if isinstance(payload, dict) else {}, counts)


async def complete_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.2,
    max_tokens: int = ROUTER_MAX_TOKENS,
    timeout: float | None = None,
) -> dict:
    """Tool-call round for the product router. OpenRouter, then the configured cloud fallback, then local."""
    route = route_for_surface("router")
    if route.get("kind") != "cloud":
        raise RuntimeError("router_requires_cloud")
    fallback = _fallback_cloud_route()
    chained = bool(fallback) and str(fallback.get("url") or "") != str(route.get("url") or "")
    later = FALLBACK_CLOUD_TIMEOUT if timeout is None else timeout
    if chained:
        hops: list[tuple[dict, float]] = [(route, PRIMARY_CLOUD_TIMEOUT), (fallback, later)]
        allow_local = True
    else:
        hops = [(route, CLOUD_PRIMARY_TIMEOUT if timeout is None else timeout)]
        allow_local = False
    last_exc: Exception | None = None
    for index, (hop, hop_timeout) in enumerate(hops):
        try:
            return await _tools_once(
                hop,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=hop_timeout,
            )
        except Exception as exc:
            last_exc = exc
            if index == len(hops) - 1 and not allow_local:
                raise
            nxt = _local_default_route("router") if index == len(hops) - 1 else hops[index + 1][0]
            _emit_cloud_fallback(
                surface="router",
                reason=_classify_llm_error(exc),
                requested=str(hop.get("model") or ""),
                used=str(nxt.get("model") or ""),
            )
    local = _local_default_route("router")
    try:
        return await _tools_once(
            local,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=later,
        )
    except Exception:
        raise last_exc or RuntimeError("llm")
