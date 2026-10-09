"""One router tool for a channel: is it connected, open the connect page, or read the page.

Instagram and Telegram share this path. A short follow-up keeps the channel from the recent turns.
"""

from __future__ import annotations

import re

_LABELS = {"instagram": "اینستاگرام", "telegram": "تلگرام", "whatsapp": "واتساپ", "rubika": "روبیکا"}
_CONNECT = ("وصل کنیم", "وصلش کنیم", "بریم وصل", "اتصال")
_STATUS = ("وصل شد", "وصل شده", "وصل کردم", "وصل است", "صحبت")
_SCAN = ("ببین", "ببینم", "ببینی", "بخون", "بخوان", "اسکن")
_LINK = {"href": "/more/channels", "label": "باز کردن کانال‌ها"}


def _platform_in(text: str) -> str:
    if "تلگرام" in text:
        return "telegram"
    if "واتساپ" in text:
        return "whatsapp"
    if "روبیکا" in text:
        return "rubika"
    if "اینستا" in text or "پیج" in text:
        return "instagram"
    return ""


def _followup(text: str) -> bool:
    words = [part for part in re.split(r"\s+", (text or "").strip()) if part]
    return bool(words) and len(words) <= 8 and not _platform_in(text)


def recent_channel(rows: list | None) -> dict | None:
    """The platform named in the last few seller lines. A short follow-up uses this instead of a second topic store."""
    window = [row for row in (rows or []) if isinstance(row, dict) and row.get("role") == "user"][-6:]
    for row in reversed(window):
        text = str(row.get("text") or "")
        if any(mark in text for mark in ("اینستا", "تلگرام", "واتساپ", "روبیکا", "کانال", "پیج")):
            return {"platform": _platform_in(text)}
    return None


def choose(spoken: str, rows: list | None = None) -> dict | None:
    """The channel action for this turn, or None when the turn is not about a channel."""
    from app.services.channel_scan_service import handle_in_text
    from app.services.turn_parse import parse_turn

    text = spoken or ""
    turn = parse_turn(text)
    current = recent_channel(rows or [])
    named = bool(_platform_in(text) or "کانال" in text)
    marked = any(mark in text for mark in (*_STATUS, *_CONNECT, *_SCAN, "وصل"))
    about = turn.topic in {"channel_status", "channel_connect", "channel_scan"} or (named and marked)
    # A short follow-up keeps the channel only when it still talks about connecting, status, or reading the page.
    if not about and current is not None and _followup(text) and marked:
        about = True
    if not about:
        return None
    platform = _platform_in(text) or str((current or {}).get("platform") or "") or "instagram"
    if any(mark in text for mark in _STATUS):
        action = "status"
    elif turn.topic == "channel_connect" or any(mark in text for mark in _CONNECT):
        action = "connect"
    elif turn.topic == "channel_scan" or any(mark in text for mark in _SCAN):
        action = "scan"
    else:
        action = "status"
    return {
        "platform": platform,
        "action": action,
        "handle": handle_in_text(text),
    }


def routed(spoken: str) -> bool:
    from app.services import router_service

    return choose(spoken, router_service._messages()) is not None


def _account(platform: str) -> dict:
    from app.services.channel_service import account_for_platform, is_connected

    row = account_for_platform(platform) or {}
    if row and is_connected(row):
        return row
    return {}


def _handle_of(platform: str, named: str = "") -> str:
    from app.services.channel_scan_service import get_scan

    if named:
        return named.lstrip("@")
    row = _account(platform)
    handle = str(row.get("handle") or "").lstrip("@")
    if handle:
        return handle
    for item in reversed(get_scan().get("accounts") or []):
        if isinstance(item, dict) and str(item.get("platform") or "") == platform and item.get("handle"):
            return str(item.get("handle") or "").lstrip("@")
    return ""


_MINE = re.compile(r"پیج\s*(?:من|خودم)|پیجم|صفحه\s*(?:ی\s*|‌ی\s*)?(?:من|خودم)|صفحه‌ام|کانال\s*(?:من|خودم)|کانالم|مال\s*منه")


def own_page(platform: str, handle: str, spoken: str = "") -> bool:
    """Only the seller's own page may fill the catalog, the voice, or a build from the chat.

    Own means: the seller says so («پیج من …»), it is the connected account, it is the page already in the seller's
    scan file, or its products are already in the catalog. Any other handle (a competitor, an example page) is only
    read. Review 2026-10-09: «پیج @رقیبم رو ببین» imported that page into the seller's shop.
    """
    name = str(handle or "").strip().lstrip("@").lower()
    if not name:
        return False
    if _MINE.search(spoken or ""):
        return True
    connected = str(_account(platform).get("handle") or "").strip().lstrip("@").lower()
    if connected and connected == name:
        return True
    from app.services.channel_scan_service import get_scan

    for item in get_scan().get("accounts") or []:
        if isinstance(item, dict) and str(item.get("handle") or "").strip().lstrip("@").lower() == name:
            return True
    from app.services.storefront_service import count_scanned_handle

    raw = str(handle or "").strip()
    return count_scanned_handle([raw, raw.lstrip("@"), "@" + raw.lstrip("@")]) > 0


def _scan_clause(platform: str, handle: str) -> str:
    from app.services.channel_scan_service import get_scan, scan_status

    if platform == "instagram":
        from app.services import channel_service, sendbox_service

        row = channel_service.account_for_platform("instagram") or {}
        reason = sendbox_service.posts_block_reason(channel_service.sendbox_account_id(row))
        if reason:
            return reason
    status = scan_status()
    if status.get("status") == "running":
        return "دارم پیج را می‌خوانم."
    if status.get("status") == "error" and status.get("error"):
        return str(status.get("error") or "")
    scan = get_scan()
    count = int(scan.get("productCount") or 0)
    page = handle or "، ".join(str(item) for item in (status.get("handles") or []) if item)
    if page:
        return f"آخرین خواندن @{page.lstrip('@')}: {count} کالا."
    return ""


def status_line(platform: str) -> str:
    label = _LABELS.get(platform, platform)
    row = _account(platform)
    if not row:
        return f"{label} قطع است."
    handle = str(row.get("handle") or "").lstrip("@")
    line = f"{label} @{handle} وصل است." if handle else f"{label} وصل است."
    extra = _scan_clause(platform, handle)
    return f"{line} {extra}".strip()


def connected_lines() -> list[str]:
    from app.services.channel_service import list_accounts

    rows = [row for row in (list_accounts().get("accounts") or []) if isinstance(row, dict)]
    if not rows:
        return ["هیچ کانالی به فروشگاه وصل نیست."]
    return [status_line(str(row.get("platform") or "")) for row in rows if row.get("platform")]


def connect_line(platform: str) -> tuple[str, dict]:
    label = _LABELS.get(platform, platform)
    return f"{label} از صفحهٔ کانال‌ها وصل می‌شود.", {"link": dict(_LINK)}


def _login_block(platform: str) -> str:
    if platform != "instagram":
        return ""
    from app.services import channel_service, sendbox_service

    row = channel_service.account_for_platform("instagram") or {}
    return sendbox_service.posts_block_reason(channel_service.sendbox_account_id(row))


def result_sentence(platform: str, handle: str) -> str:
    """What the download found. A saved login error is used only when no page came down."""
    from app.services.channel_scan_service import get_scan, page_seen, page_view, scan_status

    label = _LABELS.get(platform, platform)
    name = handle.lstrip("@") or label
    view = page_view(platform, handle)
    status = scan_status()
    if page_seen(view):
        titles = list(view.get("titles") or [])
        cats = "، ".join(view.get("categories") or []) or "—"
        colors = "، ".join(view.get("colors") or []) or "—"
        if titles:
            names = "، ".join(titles[:6])
            return (
                f"پیج @{name} را خواندم: {names}. دسته‌ها: {cats}. رنگ‌ها: {colors}. "
                "اگر این‌ها روی سایت بیاید بگو."
            )
        about = str(view.get("about") or "").strip()
        caption = str((view.get("captions") or [""])[0] or "").strip()
        seen = about or caption
        if seen:
            return f"پیج @{name} را خواندم. {seen}"
        images = int(view.get("images") or 0)
        if images:
            return f"پیج @{name} را خواندم: {images} عکس، بدون کپشن کالا."
        scan = get_scan()
        total = int(scan.get("productCount") or 0)
        return (
            f"پیج @{name} را خواندم: {total} کالا. دسته‌ها: {cats}. رنگ‌ها: {colors}. "
            "اگر این‌ها روی سایت بیاید بگو."
        )
    reason = _login_block(platform)
    if reason:
        return f"{label} @{name}: {reason}"
    if status.get("status") == "error" and status.get("error"):
        return f"{label} @{name}: {status.get('error')}"
    return f"پیج @{name} خوانده نشد."


def _review_brief(platform: str, handle: str, view: dict) -> str:
    lines = [f"پلتفرم: {platform}", f"حساب: @{handle.lstrip('@')}"]
    if view.get("about"):
        lines.append(f"معرفی: {view['about']}")
    if view.get("categories"):
        lines.append("دسته‌ها: " + "، ".join(view["categories"]))
    if view.get("titles"):
        lines.append("کالاها: " + "، ".join(view["titles"]))
    if view.get("captions"):
        lines.append("کپشن‌ها:\n" + "\n".join(f"- {item}" for item in view["captions"]))
    if view.get("images"):
        lines.append(f"تعداد عکس: {view['images']}")
    return "\n".join(lines)[:3500]


async def review_sentence(platform: str, handle: str) -> str:
    """An opinion on the page that was just downloaded, the same text the shop build reads."""
    from app.services.channel_scan_service import page_seen, page_view
    from app.services.llm import complete_text_chat
    from app.services.persian_text import REFUSAL_GENERIC, SAFE_EMPTY, guard_output

    view = page_view(platform, handle)
    if not page_seen(view):
        return result_sentence(platform, handle)
    reply = await complete_text_chat(
        system=(
            "پیج فروشنده همین الان دانلود شده، همان مسیری که برای ساخت سایت پیج اینستاگرام یا کانال تلگرام خوانده می‌شود. "
            "نظر کوتاه فارسی بده: پیج چه می‌گوید، لحنش چیست، و یک کمبود مشخص. فقط از متن داده‌شده. "
            "نگو صفحه باز نمی‌شود و از ورود یا توکن حرف نزن."
        ),
        turns=[{"role": "user", "text": _review_brief(platform, handle, view)}],
        surface="scan",
        temperature=0.4,
        max_tokens=280,
    )
    guarded = guard_output(reply or "") if reply else ""
    refused = guarded in {REFUSAL_GENERIC, SAFE_EMPTY, "این را در چت نمی‌گویم."}
    if guarded and not refused and all(mark not in guarded for mark in ("نمی‌توانم", "منقضی", "توکن")):
        return guarded
    return result_sentence(platform, handle)


def _watch(platform: str, handle: str, *, review: bool = False):
    from app.state_store import current_tenant

    from app.services import router_service

    phone = current_tenant()
    thread_id = router_service.current_thread_id()

    def notify():
        from app.state_store import tenant_scope

        async def post() -> None:
            text = await review_sentence(platform, handle) if review else result_sentence(platform, handle)
            with tenant_scope(phone):
                router_service.post_notice(thread_id, text)

        return post()

    return notify


def announce_connected(platform: str, handle: str) -> None:
    """A line in the seller's latest thread after a channel is bound."""
    try:
        from app.services import router_service

        label = _LABELS.get(platform, platform)
        name = str(handle or "").lstrip("@")
        shown = f"@{name}" if name else label
        router_service.post_notice(
            router_service.latest_thread_id(),
            f"{label} {shown} وصل شد؛ دارم پیج را می‌خوانم.",
        )
    except Exception:
        return


async def run(spoken: str, args: dict) -> tuple[str, dict]:
    from app.services import router_service
    from app.services.channel_scan_service import start_scan

    picked = choose(spoken, router_service._messages()) or {}
    platform = str(args.get("platform") or picked.get("platform") or "instagram")
    action = str(args.get("action") or picked.get("action") or "status")
    if action not in {"status", "connect", "scan"}:
        action = "status"
    if platform not in _LABELS:
        platform = "instagram"
    handle = str(args.get("handle") or picked.get("handle") or "").lstrip("@")
    if action == "connect":
        line, extra = connect_line(platform)
        if _account(platform):
            line = status_line(platform)
        else:
            return line, extra
        return line, {"link": dict(_LINK)}
    if action == "scan":
        handle = _handle_of(platform, handle)
        if not handle:
            return "اسم پیج یا کانال را بگو تا بخوانم.", {"link": dict(_LINK)}
        if not own_page(platform, handle, spoken):
            from app.services.channel_scan_service import start_other_scan

            start_other_scan([{"platform": platform, "handle": handle}], notify=_watch(platform, handle, review=True))
            return (
                f"دارم پیج @{handle} را می‌خوانم. چون پیج خودت نیست، فقط نظرم را می‌گویم و چیزی به کاتالوگ یا لحنت اضافه نمی‌کنم.",
                {},
            )
        review = "نظر" in spoken
        start_scan(
            [{"platform": platform, "handle": handle}],
            notify=_watch(platform, handle, review=review),
            import_catalog=not review,
        )
        return f"دارم پیج @{handle} را می‌خوانم.", {}
    line = status_line(platform)
    if not _account(platform):
        return line, {"link": dict(_LINK)}
    return line, {}
