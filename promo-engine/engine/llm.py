from __future__ import annotations

import json
import re

import httpx

from config import settings

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

LLM_UNREACHABLE = {
    "error": "llm_unreachable",
    "reply": "مدل محلی پاسخ نداد. سرویس llama-swap را چک کن و پیام را دوباره بفرست.",
}
LLM_BAD_JSON = {
    "error": "llm_bad_json",
    "reply": "مدل پاسخ خوانا نداد. پیام را کوتاه‌تر دوباره بفرست.",
}


def parse_json_object(text: str) -> dict:
    cleaned = THINK_BLOCK.sub("", text or "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def _chat_completion(*, messages: list[dict], temperature: float, max_tokens: int) -> str:
    body = {
        "model": settings.llm_model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    headers = {"Content-Type": "application/json"}
    if settings.llm_token:
        headers["Authorization"] = f"Bearer {settings.llm_token}"
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        res = await client.post(f"{settings.llm_url}/chat/completions", json=body, headers=headers)
        res.raise_for_status()
        return (((res.json().get("choices") or [{}])[0].get("message") or {}).get("content")) or ""


async def complete_json(system: str, user: str) -> dict:
    try:
        text = await _chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=900,
        )
    except Exception:
        return dict(LLM_UNREACHABLE)
    data = parse_json_object(text)
    if not data:
        return dict(LLM_BAD_JSON)
    return data