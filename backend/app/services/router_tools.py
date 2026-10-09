"""Seller-chat tools, declared once.

A tool is a name, the schema the chat model sees, a level, a rank (which call wins when the model makes several),
the groups it belongs to, and optionally its own card sentence and handler. router_service takes TOOLS, the level
sets and the ranks from here, so a new tool is one `register(Tool(...))` (plus its handler module) instead of edits
in five places of the router.

Levels:
- read: runs at once and never changes a seller file.
- write: always a confirmation card first; runs only after «تأیید».
- pass: the shop conversation (build, rebuild, advice). A rebuild still gets a card in router_service.

Groups are the toolsets the decider can open together (DECIDER_TOOL_GROUPS): the chosen tool first, then the read
tools of its groups, so the model can look before it writes. Writes outside the chosen tool are never added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

Handler = Callable[[str, dict], Awaitable[tuple[str, dict]]]
Summary = Callable[[dict, str], str]
LEVELS = ("read", "write", "pass")


@dataclass(frozen=True)
class Tool:
    name: str
    schema: dict
    level: str = "read"
    rank: int = 3
    groups: tuple[str, ...] = ()
    run: Handler | None = None
    summary: Summary | None = None


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.level not in LEVELS:
        raise ValueError(f"unknown tool level {tool.level}")
    name = str((tool.schema.get("function") or {}).get("name") or "")
    if name != tool.name:
        raise ValueError(f"schema name {name!r} is not {tool.name!r}")
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def names(level: str | None = None) -> frozenset[str]:
    return frozenset(tool.name for tool in _REGISTRY.values() if level is None or tool.level == level)


def schemas(only: list[str] | None = None) -> list[dict]:
    """Schemas in registration order (the order the chat model has always seen)."""
    wanted = set(only) if only is not None else None
    return [tool.schema for tool in _REGISTRY.values() if wanted is None or tool.name in wanted]


def rank(name: str) -> int:
    tool = _REGISTRY.get(name)
    return tool.rank if tool else 9


def handler(name: str) -> Handler | None:
    tool = _REGISTRY.get(name)
    return tool.run if tool else None


def summary(name: str, args: dict, spoken: str) -> str:
    tool = _REGISTRY.get(name)
    if tool is None or tool.summary is None:
        return ""
    return str(tool.summary(args, spoken) or "")


def toolset(name: str) -> list[str]:
    """The chosen tool first, then the read tools that share a group with it (never another write)."""
    tool = _REGISTRY.get(name)
    if tool is None:
        return []
    out = [name]
    for other in _REGISTRY.values():
        if other.name == name or other.level != "read" or other.name == "ask_user":
            continue
        if set(other.groups) & set(tool.groups):
            out.append(other.name)
    return out


async def _status(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services.router_status import _format_status, _status_payload

    return _format_status(await _status_payload()), {}


async def _channel(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services.channel_tool import run

    return await run(spoken, args)


_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "channel",
            "description": "وضعیت، وصل کردن، یا خواندن پیج اینستاگرام یا تلگرام. سؤال کلی فروشگاه نیست.",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": ["instagram", "telegram", "whatsapp", "rubika"]},
                    "action": {"type": "string", "enum": ["status", "connect", "scan"]},
                    "handle": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "status",
            "description": "پرسش وضعیت، اسکن، بیلد، پلن، کیف یا دامنه. حتی با کلمهٔ فروشگاه. کانال و پیج را به channel بده.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inbox_status",
            "description": "صندوق، خوانده‌نشده و پاسخ خودکار. پرسش وضعیت فروشگاه نیست.",
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
            "description": "ساخت ویترین از صفر. تغییر صفحهٔ زنده را به edit_shop بده. پرسش وضعیت را به status بده.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_shop",
            "description": "تغییر صفحهٔ زنده: رنگ، متن، هدر، پنهان کردن قیمت. متن تازه را خودت ننویس.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_product",
            "description": "افزودن کالا وقتی کاربر نام و قیمت تومان گفته. قیمت را از جملهٔ کاربر بردار.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "studio_chat",
            "description": "کپشن، کپی، شعار، پست یا استوری. متن تبلیغ را خودت ننویس؛ فقط این ابزار.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_post",
            "description": "فرستادن آخرین پست آماده. اینستاگرام دایرکت است و مخاطب می‌خواهد.",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": ["telegram", "whatsapp", "instagram"]},
                    "recipientId": {"type": "string"},
                },
                "required": ["platform"],
            },
        },
    },
]


# level, rank (lower wins), groups. Ranks and levels are the router's long-standing ones.
_PLACES: dict[str, tuple[str, int, tuple[str, ...]]] = {
    "channel": ("read", 3, ("channel",)),
    "status": ("read", 3, ("shop", "content", "channel")),
    "inbox_status": ("read", 3, ("inbox",)),
    "ask_user": ("read", 2, ()),
    "set_auto_reply": ("write", 0, ("inbox",)),
    "set_voice_tone": ("write", 0, ("inbox",)),
    "shop_chat": ("pass", 1, ("shop",)),
    "edit_shop": ("write", 0, ("shop",)),
    "add_product": ("write", 0, ("shop",)),
    "studio_chat": ("write", 0, ("content",)),
    "publish_post": ("write", 0, ("content", "channel")),
}
_HANDLERS: dict[str, Handler] = {"channel": _channel, "status": _status}

for _schema in _SCHEMAS:
    _name = str(_schema["function"]["name"])
    _level, _rank, _groups = _PLACES[_name]
    register(Tool(name=_name, schema=_schema, level=_level, rank=_rank, groups=_groups, run=_HANDLERS.get(_name)))

TOOLS = schemas()
WRITE_TOOLS = names("write")
READ_TOOLS = names("read")
PASSTHROUGH = names("pass")
TOOL_RANK = {name: rank(name) for name in names()}
