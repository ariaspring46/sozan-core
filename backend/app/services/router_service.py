from __future__ import annotations

import time
from uuid import uuid4

from app.services.observe_client import emit_later
from app.state_store import read_json, write_json

MESSAGES_FILE = "router-messages.json"
PENDING_FILE = "router-pending.json"
USAGE_FILE = "router-usage.json"
WRITE_TOOLS = frozenset({"set_auto_reply", "set_voice_tone"})
PASSTHROUGH = frozenset({"shop_chat", "studio_chat"})
READ_TOOLS = frozenset({"status", "ask_user", "inbox_status"})
ALLOWED = WRITE_TOOLS | PASSTHROUGH | READ_TOOLS
MAX_MESSAGES = 80
DAILY_TURNS = 80
DAILY_COMPLETION = 12000
MAX_TOKENS = {
    "read": 80,
    "reply": 150,
    "caption": 300,
    "edit": 400,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "status",
            "description": "وضعیت فروشگاه، اسکن، پلن، مانده کیف و دامنه",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inbox_status",
            "description": "خوانده‌نشده‌ها و حالت پاسخ خودکار صندوق",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "سؤال ساخت‌یافته وقتی خواسته مبهم است. دامنه: بپرس شخصی یا ساب‌دامین سوزان؛ NS را ست نکن، بگو بعد از تأیید نیم‌سرور آروان می‌آید.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_auto_reply",
            "description": "حالت پاسخ خودکار صندوق: خاموش، پیش‌نویس یا ارسال",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["", "draft", "send"]}},
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_voice_tone",
            "description": "لحن پاسخ دایرکت",
            "parameters": {
                "type": "object",
                "properties": {
                    "toneId": {"type": "string", "enum": ["warm", "formal", "street", "luxury"]},
                },
                "required": ["toneId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shop_chat",
            "description": "ادامهٔ گفتگوی ساخت و ادیت فروشگاه با همان مسیر امروز",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "studio_chat",
            "description": "ادامهٔ گفتگوی استودیوی محتوا با همان مسیر امروز",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
]

SYSTEM = "تو سوزان هستی. فارسی کوتاه، بدون مقدمه. تنظیمات با ابزار. فروشگاه=shop_chat، محتوا=studio_chat. دایرکت را جواب نده. مبهم=ask_user. کلید و JSON خام نشان نده."


def _messages() -> list[dict]:
    rows = read_json(MESSAGES_FILE, [])
    return rows if isinstance(rows, list) else []


def _save_messages(rows: list[dict]) -> None:
    write_json(MESSAGES_FILE, rows[-MAX_MESSAGES:])


def _pending() -> dict:
    row = read_json(PENDING_FILE, {})
    return row if isinstance(row, dict) else {}


def _save_pending(row: dict | None) -> None:
    write_json(PENDING_FILE, row or {})


def snapshot() -> dict:
    shop = read_json("shop.json", {})
    brand = ""
    if isinstance(shop, dict):
        brand = str(shop.get("brand") or "").strip()[:40]
    return {
        "messages": _messages(),
        "pendingConfirm": _public_pending(_pending()),
        "brand": brand,
    }


def _public_pending(row: dict) -> dict | None:
    if not row or not row.get("id"):
        return None
    return {
        "id": row.get("id"),
        "tool": row.get("tool"),
        "summary": row.get("summary") or "",
    }


def _append(role: str, text: str, **extra) -> dict:
    row = {"id": str(uuid4()), "role": role, "text": text, "at": int(time.time()), **extra}
    rows = _messages()
    rows.append(row)
    _save_messages(rows)
    return row


_TONE_FA = {"warm": "گرم", "formal": "رسمی", "street": "کوچه", "luxury": "لوکس"}


def _summary_for(name: str, args: dict) -> str:
    if name == "set_auto_reply":
        labels = {"": "خاموش", "draft": "پیش‌نویس", "send": "ارسال خودکار"}
        return f"پاسخ خودکار دایرکت بشود {labels.get(str(args.get('mode') or ''), '؟')}؟"
    if name == "set_voice_tone":
        tone = _TONE_FA.get(str(args.get("toneId") or ""), "؟")
        return f"لحن دایرکت بشود {tone}؟"
    return "این تغییر اعمال شود؟"


async def _status_payload() -> dict:
    from app.services import channel_service, plan_service, shop_service, wallet_service

    snap = shop_service.snapshot()
    shop = snap.get("shop") or {}
    scan = snap.get("scan") or {}
    build = snap.get("build") or {}
    accounts = channel_service.list_accounts().get("accounts") or []
    plan = plan_service.snapshot()
    wallet = wallet_service.get()
    return {
        "shopStatus": shop.get("status") or "",
        "slug": shop.get("slug") or "",
        "cnameOk": bool(shop.get("cnameOk")),
        "scanStatus": scan.get("status") or "",
        "scanNoPrice": scan.get("noPrice"),
        "scanNoImage": scan.get("noImage"),
        "buildStatus": build.get("status") or "",
        "channels": [
            {
                "platform": row.get("platform"),
                "handle": row.get("handle"),
                "connected": bool(row.get("connected")),
            }
            for row in accounts
        ],
        "plan": plan.get("plan") or plan.get("id") or "",
        "walletAvailable": int(wallet.get("available") or 0),
    }


def _format_status(data: dict) -> str:
    chans = data.get("channels") or []
    chan = "، ".join(f"{c.get('platform')} {'وصل' if c.get('connected') else 'قطع'}" for c in chans) if chans else "—"
    return (
        f"فروشگاه {data.get('shopStatus') or '—'} · اسکن {data.get('scanStatus') or '—'} · "
        f"بیلد {data.get('buildStatus') or '—'} · دامنه {'درست' if data.get('cnameOk') else 'ناقص'} · "
        f"پلن {data.get('plan') or '—'} · کیف {data.get('walletAvailable') or 0} · کانال {chan}"
    )


async def _inbox_payload() -> dict:
    from app.services import inbox_service

    threads = inbox_service.list_threads()
    unread = inbox_service.unread_count()
    return {
        "unread": int(unread.get("count") or 0),
        "autoReply": threads.get("autoReply") or "",
        "autoReplyMax": threads.get("autoReplyMax") or "",
        "threadCount": len(threads.get("threads") or []),
    }


def _format_inbox(data: dict) -> str:
    mode = {"": "خاموش", "draft": "پیش‌نویس", "send": "ارسال"}.get(str(data.get("autoReply") or ""), "خاموش")
    return f"خوانده‌نشده: {data.get('unread') or 0} · پاسخ خودکار: {mode} · گفتگوها: {data.get('threadCount') or 0}"


async def _run_tool(
    name: str,
    args: dict,
    *,
    campaigns=None,
    source_text: str = "",
    media=None,
    view_path: str = "",
    view_target: str = "",
) -> str:
    if name == "status":
        return _format_status(await _status_payload())
    if name == "inbox_status":
        return _format_inbox(await _inbox_payload())
    if name == "set_auto_reply":
        from app.services import inbox_service

        inbox_service.save_auto_reply(str(args.get("mode") or ""))
        return "حالت پاسخ خودکار به‌روز شد."
    if name == "set_voice_tone":
        from app.services import voice_service

        voice_service.apply_tone(str(args.get("toneId") or "warm"))
        return "لحن دایرکت به‌روز شد."
    if name == "shop_chat":
        from app.services import shop_service

        text = str(args.get("text") or source_text or "").strip()[:4000]
        out = await shop_service.chat(text, media, view_path, view_target)
        msgs = out.get("messages") or []
        last = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
        return str((last or {}).get("text") or "فروشگاه به‌روز شد.")
    if name == "studio_chat":
        if campaigns is None:
            return "استودیو الان در دسترس نیست."
        from app.services import studio_chat_service

        text = str(args.get("text") or source_text or "").strip()[:4000]
        out = await studio_chat_service.chat(text, campaigns, media)
        msgs = out.get("messages") or []
        last = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
        return str((last or {}).get("text") or "استودیو پاسخ داد.")
    return "این ابزار را ندارم."


def _emit(title: str, payload: dict, status: str = "ok") -> None:
    safe = {
        k: v
        for k, v in payload.items()
        if k not in {"token", "apiKey", "secret", "arguments_raw", "code", "otp"}
    }
    emit_later(kind="llm", title=title, surface="router", status=status, payload=safe)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _usage_row() -> dict:
    row = read_json(USAGE_FILE, {})
    if not isinstance(row, dict) or row.get("day") != _today():
        return {"day": _today(), "turns": 0, "promptTokens": 0, "completionTokens": 0}
    return row


def _over_daily_cap(row: dict) -> bool:
    return int(row.get("turns") or 0) >= DAILY_TURNS or int(row.get("completionTokens") or 0) >= DAILY_COMPLETION


def _add_usage(usage: dict | None) -> None:
    row = _usage_row()
    row["turns"] = int(row.get("turns") or 0) + 1
    if isinstance(usage, dict):
        row["promptTokens"] = int(row.get("promptTokens") or 0) + int(usage.get("promptTokens") or 0)
        row["completionTokens"] = int(row.get("completionTokens") or 0) + int(usage.get("completionTokens") or 0)
    write_json(USAGE_FILE, row)


def _brand_line() -> str:
    shop = read_json("shop.json", {})
    voice = read_json("voice.json", {})
    if not isinstance(shop, dict):
        shop = {}
    if not isinstance(voice, dict):
        voice = {}
    bits = [
        str(shop.get("brand") or "").strip()[:40],
        str(shop.get("status") or "").strip()[:20],
        str(voice.get("toneId") or "").strip()[:16],
    ]
    text = " · ".join(item for item in bits if item)
    return f"زمینه: {text}" if text else ""


def _ask_message(args: dict) -> tuple[str, list[str]]:
    question = str(args.get("question") or "").strip() or "کدام را می‌خواهی؟"
    options = [str(item).strip() for item in (args.get("options") or []) if str(item).strip()][:6]
    return question, options


def _tool_error(name: str, exc: Exception) -> str:
    if isinstance(exc, ValueError):
        text = str(exc).strip()
        if text:
            _emit("router-tool-error", {"tool": name, "error": text[:200]}, status="error")
            return text
    _emit("router-tool-error", {"tool": name, "error": type(exc).__name__}, status="error")
    return "این کار انجام نشد. یک بار دیگر بگو."


async def turn(
    text: str,
    *,
    confirm_id: str = "",
    cancel_id: str = "",
    campaigns=None,
    complete=None,
    media=None,
    view_path: str = "",
    view_target: str = "",
) -> dict:
    spoken = (text or "").strip()
    pending = _pending()
    if cancel_id and pending.get("id") == cancel_id:
        tool = str(pending.get("tool") or "")
        _save_pending(None)
        _append("assistant", "باشه، انجامش نمی‌دهم.")
        _emit("router-cancel", {"tool": tool})
        return snapshot()
    if confirm_id and pending.get("id") == confirm_id:
        _save_pending(None)
        name = str(pending.get("tool") or "")
        args = pending.get("arguments") if isinstance(pending.get("arguments"), dict) else {}
        try:
            reply = await _run_tool(
                name,
                args,
                campaigns=campaigns,
                source_text=str(pending.get("sourceText") or ""),
                media=pending.get("media"),
                view_path=str(pending.get("viewPath") or ""),
                view_target=str(pending.get("viewTarget") or ""),
            )
        except Exception as exc:
            _append("assistant", _tool_error(name, exc))
            return snapshot()
        _append("assistant", reply)
        _emit("router-tool", {"tool": name, "confirmed": True})
        return snapshot()
    if not spoken and not media:
        return snapshot()
    if _over_daily_cap(_usage_row()):
        _append("user", spoken or "پیوست")
        _append("assistant", "برای امروز کافی است؛ فردا دوباره از چت استفاده کن.")
        return snapshot()
    if pending.get("id"):
        _save_pending(None)
    _append("user", spoken or "پیوست")

    completer = complete
    if completer is None:
        from app.services.llm import complete_tools, visible_chat_turns

        async def completer(messages, tools):  # type: ignore[misc]
            return await complete_tools(messages=messages, tools=tools, max_tokens=MAX_TOKENS["reply"])

        history = [{"role": "system", "content": SYSTEM}]
        brand = _brand_line()
        if brand:
            history.append({"role": "system", "content": brand})
        history.extend(visible_chat_turns(_messages()))
    else:
        history = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": spoken or "پیوست"}]

    try:
        result = await completer(history, TOOLS)
    except Exception:
        _append("assistant", "مدل پاسخ نداد. پیام را دوباره بفرست.")
        _emit("router-llm-fail", {"error": "unreachable"}, status="error")
        return snapshot()
    _add_usage(result.get("usage") if isinstance(result, dict) else None)

    calls = result.get("tool_calls") if isinstance(result, dict) else None
    if not calls:
        reply = str((result or {}).get("text") or "").strip() or "بگو فروشگاه، محتوا یا صندوق — از همان‌جا کمکت می‌کنم."
        _append("assistant", reply)
        return snapshot()

    call = calls[0]
    name = str(call.get("name") or "")
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    if name not in ALLOWED:
        _append("assistant", "این کار را از چت نمی‌توانم انجام دهم.")
        _emit("router-unknown-tool", {"tool": name[:80]}, status="error")
        return snapshot()
    if name in WRITE_TOOLS:
        pending_id = str(uuid4())
        summary = _summary_for(name, args)
        _save_pending(
            {
                "id": pending_id,
                "tool": name,
                "arguments": args,
                "summary": summary,
                "sourceText": spoken,
                "viewPath": view_path,
                "viewTarget": view_target,
            }
        )
        _append("assistant", summary, kind="confirm", confirmId=pending_id)
        _emit("router-confirm", {"tool": name})
        return snapshot()
    if name == "ask_user":
        question, options = _ask_message(args)
        extra = {"kind": "ask", "options": options} if options else {"kind": "ask"}
        _append("assistant", question, **extra)
        _emit("router-tool", {"tool": "ask_user"})
        return snapshot()
    try:
        reply = await _run_tool(
            name,
            args,
            campaigns=campaigns,
            source_text=spoken,
            media=media,
            view_path=view_path,
            view_target=view_target,
        )
    except Exception as exc:
        _append("assistant", _tool_error(name, exc))
        return snapshot()
    _append("assistant", reply)
    _emit("router-tool", {"tool": name})
    return snapshot()
