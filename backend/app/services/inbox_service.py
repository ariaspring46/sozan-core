from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from app.services.channel_service import PLATFORMS
from app.services.observe_client import emit_later
from app.services.tenant_lock import tenant_file_lock
from app.state_store import read_json, write_json

log = logging.getLogger("sozan.inbox")
REPLY_LIMITS = {"telegram": 4000, "instagram": 1000, "whatsapp": 1000}
MODE_RANK = {"": 0, "draft": 1, "send": 2}
MODE_PLAN_LABEL = {"": "رایگان", "draft": "پرو", "send": "پرو مکس"}
ECHO_SEC = 180
AUTO_GAP_SEC = 45
AUTO_SEND_HOUR_CAP = 20
AUTO_HOUR_SEC = 3600
THREAD_CAP = 200
MSG_CAP = 80
AUTO_RETRY_MAX = 2
SENDING_STALE_SEC = 120
SETTINGS_FILE = "inbox-settings.json"
_AUTO_TASKS: set[asyncio.Task] = set()
_DEFERRED: dict[str, asyncio.Task] = {}


def _state() -> dict:
    data = read_json("inbox.json", {"threads": []})
    if not isinstance(data, dict):
        data = {"threads": []}
    threads = data.get("threads")
    if not isinstance(threads, list):
        threads = []
    now = int(time.time())
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        if "lastReadAt" not in thread:
            thread["lastReadAt"] = int(thread.get("updatedAt") or now)
        if "paused" not in thread:
            thread["paused"] = False
        if "autoRetries" not in thread:
            thread["autoRetries"] = 0
    data["threads"] = threads
    return data


def _save(data: dict) -> None:
    threads = data.get("threads") if isinstance(data.get("threads"), list) else []
    if len(threads) > THREAD_CAP:
        threads = sorted(threads, key=lambda row: int(row.get("updatedAt") or 0), reverse=True)[:THREAD_CAP]
        data["threads"] = threads
    write_json("inbox.json", data)


def _inbox_settings() -> dict:
    data = read_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def plan_auto_reply_max() -> str:
    from app.services import plan_service

    mode = str(plan_service.current().get("autoReply") or "")
    return mode if mode in MODE_RANK else ""


def auto_reply_choice() -> str:
    stored = _inbox_settings().get("autoReply")
    if stored is None:
        return plan_auto_reply_max()
    mode = str(stored)
    return mode if mode in MODE_RANK else plan_auto_reply_max()


def effective_auto_reply() -> str:
    choice = auto_reply_choice()
    ceiling = plan_auto_reply_max()
    if MODE_RANK.get(choice, 0) > MODE_RANK.get(ceiling, 0):
        return ceiling
    return choice


def _mode_meta() -> dict:
    from app.services import plan_service

    plan = plan_service.current()
    return {
        "autoReply": effective_auto_reply(),
        "autoReplyMax": str(plan.get("autoReply") or ""),
        "autoReplyChoice": auto_reply_choice(),
        "planLabel": str(plan.get("label") or ""),
        "dmSync": bool(plan.get("dmSync")),
    }


def save_auto_reply(mode: str) -> dict:
    wanted = str(mode or "")
    if wanted not in MODE_RANK:
        raise ValueError("این حالت پاسخ خودکار نیست")
    ceiling = plan_auto_reply_max()
    if MODE_RANK[wanted] > MODE_RANK.get(ceiling, 0):
        needed = MODE_PLAN_LABEL.get(wanted) or "بالاتر"
        raise ValueError(f"این حالت در پلن {needed} است.")
    write_json(SETTINGS_FILE, {"autoReply": wanted})
    return list_threads()


def _unread_count(thread: dict) -> int:
    last_read = int(thread.get("lastReadAt") or 0)
    n = 0
    for msg in thread.get("messages") or []:
        if str(msg.get("role") or "") != "inbound":
            continue
        if int(msg.get("at") or 0) > last_read:
            n += 1
    return n


def _last_role(thread: dict) -> str:
    messages = thread.get("messages") or []
    last = messages[-1] if messages else {}
    kind = str(last.get("kind") or "")
    role = str(last.get("role") or "")
    if kind == "draft":
        return "draft"
    if kind == "failed":
        return "failed"
    if role == "inbound":
        return "inbound"
    return "outbound" if messages else ""


def _summary(thread: dict) -> dict:
    messages = thread.get("messages") or []
    last = messages[-1] if messages else {}
    platform = str(thread.get("platform") or "")
    pending = any(str(msg.get("kind") or "") == "draft" or msg.get("status") == "failed" for msg in messages)
    return {
        "id": thread.get("id"),
        "platform": platform,
        "platformLabel": PLATFORMS.get(platform, platform),
        "sender": thread.get("sender") or "مشتری",
        "updatedAt": thread.get("updatedAt") or 0,
        "lastText": str(last.get("text") or ""),
        "count": len(messages),
        "delivered": bool(thread.get("delivered", True)),
        "pending": pending,
        "paused": bool(thread.get("paused")),
        "handoffReason": str((thread.get("handoff") or {}).get("reason") or "")
        if isinstance(thread.get("handoff"), dict)
        else "",
        "unread": _unread_count(thread),
        "lastRole": _last_role(thread),
        "autoReply": str(thread.get("autoReply") or ""),
    }


def _messages(thread: dict) -> list[dict]:
    out = []
    for msg in thread.get("messages") or []:
        inbound = str(msg.get("role") or "") == "inbound"
        platform = str(thread.get("platform") or "")
        kind = str(msg.get("kind") or "")
        row = {
            "id": msg.get("id"),
            "role": "assistant" if inbound else "user",
            "text": msg.get("text") or "",
            "at": msg.get("at") or 0,
            "kind": kind or ("inbound" if inbound else "outbound"),
            "status": msg.get("status") or "",
            "error": msg.get("error") or "",
            "delivered": bool(msg.get("delivered", not inbound and kind != "draft")),
            "platform": platform if inbound else "",
            "platformLabel": PLATFORMS.get(platform, platform) if inbound else "",
            "sender": thread.get("sender") if inbound else "",
            "auto": bool(msg.get("auto")),
        }
        if msg.get("mediaKind") and msg.get("mediaName"):
            row["mediaKind"] = msg.get("mediaKind")
            row["mediaName"] = msg.get("mediaName")
        out.append(row)
    return out


def list_threads(*, q: str = "", platform: str = "", status_filter: str = "") -> dict:
    threads = sorted(_state()["threads"], key=lambda row: int(row.get("updatedAt") or 0), reverse=True)
    needle = (q or "").strip()
    wanted = (platform or "").strip().lower()
    filt = (status_filter or "").strip().lower()
    out = []
    for row in threads:
        summary = _summary(row)
        if wanted and summary["platform"] != wanted:
            continue
        waiting = bool(summary.get("handoffReason"))
        if filt == "unread" and not summary["unread"] and not waiting:
            continue
        if filt == "pending" and not summary["pending"] and not waiting:
            continue
        if needle:
            blob = f"{summary['sender']} {summary['lastText']} {summary['platformLabel']}"
            if needle not in blob:
                continue
        out.append(summary)
    return {**_mode_meta(), "threads": out}


def list_publish_audience(*, platform: str, q: str = "", limit: int = 24) -> list[dict]:
    wanted = (platform or "").strip().lower()
    needle = (q or "").strip()
    cap = max(1, min(int(limit or 24), 50))
    out: list[dict] = []
    threads = sorted(_state()["threads"], key=lambda row: int(row.get("updatedAt") or 0), reverse=True)
    for row in threads:
        if not isinstance(row, dict):
            continue
        if wanted and str(row.get("platform") or "") != wanted:
            continue
        recipient = str(row.get("senderId") or row.get("chatId") or "").strip()
        if not recipient:
            continue
        sender = str(row.get("sender") or "مشتری").strip() or "مشتری"
        messages = row.get("messages") if isinstance(row.get("messages"), list) else []
        last_row = messages[-1] if messages and isinstance(messages[-1], dict) else {}
        last = str(last_row.get("text") or "")
        pending = any(
            str(msg.get("kind") or "") == "draft" or msg.get("status") == "failed"
            for msg in (row.get("messages") or [])
            if isinstance(msg, dict)
        )
        if needle and needle not in f"{sender} {last} {recipient}":
            continue
        out.append(
            {
                "id": row.get("id"),
                "sender": sender,
                "recipientId": recipient,
                "lastText": last[:80],
                "pending": pending,
                "updatedAt": int(row.get("updatedAt") or 0),
            }
        )
        if len(out) >= cap:
            break
    return out


def unread_count() -> dict:
    return {"count": sum(_unread_count(row) for row in _state()["threads"])}


async def sync_now() -> dict:
    from app.services import channel_service, plan_service, telegram_service

    if not plan_service.current().get("dmSync"):
        raise ValueError("همگام‌سازی دایرکت در این پلن خاموش است.")
    imported = 0
    errors: list[str] = []
    hints: list[str] = []
    saw_telegram = False
    saw_instagram = False
    for row in channel_service.iter_accounts():
        platform = str(row.get("platform") or "")
        if platform == "telegram":
            saw_telegram = True
            token = channel_service.token_for(row)
            if not token:
                errors.append("توکن بات تلگرام نیست. از بیشتر → کانال‌ها وصل کن.")
                continue
            result = await telegram_service.pull_updates(token=token, handle=str(row.get("handle") or ""))
            if result.get("ok"):
                imported += int(result.get("imported") or 0)
            else:
                errors.append(str(result.get("error") or "تلگرام همگام نشد."))
        elif platform == "instagram":
            saw_instagram = True
            if channel_service.sendbox_account_id(row):
                hints.append("دایرکت اینستاگرام با وبهوک BoxAPI می‌آید.")
            else:
                errors.append(channel_service.IG_RECONNECT)
    if not saw_telegram and not saw_instagram:
        raise ValueError("حساب کانال وصل نیست. از بیشتر → کانال‌ها وصل کن.")
    return {
        **list_threads(),
        "ok": not errors,
        "imported": imported,
        "error": errors[0] if errors else "",
        "hint": hints[0] if hints else "",
    }


def discard_failed_message(thread_id: str, message_id: str) -> dict:
    with tenant_file_lock("inbox"):
        data = _state()
        thread = _find_thread(data, thread_id)
        if thread is None:
            raise KeyError("گفتگو پیدا نشد")
        target = None
        for msg in thread.get("messages") or []:
            if isinstance(msg, dict) and str(msg.get("id") or "") == message_id:
                target = msg
                break
        if target is None:
            raise KeyError("پیام پیدا نشد")
        kind = str(target.get("kind") or "")
        status = str(target.get("status") or "")
        if kind != "failed" and status != "failed":
            raise ValueError("فقط پیام ارسال‌نشده را می‌توان حذف کرد.")
        thread["messages"] = [
            msg for msg in (thread.get("messages") or []) if str(msg.get("id") or "") != message_id
        ]
        thread["updatedAt"] = int(time.time())
        _save(data)
    return get_thread(thread_id, mark_read=True)


def _find_thread(data: dict, thread_id: str) -> dict | None:
    for thread in data["threads"]:
        if str(thread.get("id")) == thread_id:
            return thread
    return None


def get_thread(thread_id: str, *, mark_read: bool = False) -> dict:
    if mark_read:
        with tenant_file_lock("inbox"):
            data = _state()
            thread = _find_thread(data, thread_id)
            if thread is None:
                raise KeyError("گفتگو پیدا نشد")
            thread["lastReadAt"] = int(time.time())
            _save(data)
    else:
        thread = _find_thread(_state(), thread_id)
        if thread is None:
            raise KeyError("گفتگو پیدا نشد")
    return {
        **_mode_meta(),
        "thread": _summary(thread),
        "messages": _messages(thread),
    }


def mark_handoff(thread_id: str, reason: str) -> None:
    """Stop the agent on this thread until the seller turns auto-reply back on."""
    reason = str(reason or "").strip()[:80]
    with tenant_file_lock("inbox"):
        data = _state()
        thread = _find_thread(data, thread_id)
        if thread is None:
            return
        thread["paused"] = True
        thread["handoff"] = {"reason": reason, "at": int(time.time())}
        thread["lastReadAt"] = 0
        thread["updatedAt"] = int(time.time())
        _save(data)


def patch_thread(thread_id: str, *, paused: bool | None = None) -> dict:
    with tenant_file_lock("inbox"):
        data = _state()
        thread = _find_thread(data, thread_id)
        if thread is None:
            raise KeyError("گفتگو پیدا نشد")
        if paused is not None:
            thread["paused"] = bool(paused)
            if not paused:
                thread.pop("handoff", None)
            thread["updatedAt"] = int(time.time())
            _save(data)
    return get_thread(thread_id, mark_read=True)


def _recent_outbound_texts(thread: dict, now: int) -> list[str]:
    out: list[str] = []
    for msg in reversed(thread.get("messages") or []):
        if str(msg.get("role") or "") != "outbound":
            continue
        if str(msg.get("kind") or "") == "failed":
            continue
        if int(msg.get("at") or 0) < now - ECHO_SEC:
            break
        blob = str(msg.get("text") or "").strip()
        if blob:
            out.append(blob)
        if len(out) >= 8:
            break
    return out


def _is_echo(thread: dict | None, text: str, *, now: int | None = None) -> bool:
    if thread is None:
        return False
    body = (text or "").strip()
    if not body:
        return False
    stamp = now if now is not None else int(time.time())
    return body in _recent_outbound_texts(thread, stamp)


def _auto_gap_remaining(thread: dict, now: float, *, mode: str) -> float:
    if mode != "send":
        return 0
    for msg in reversed(thread.get("messages") or []):
        if str(msg.get("role") or "") != "outbound":
            continue
        if str(msg.get("kind") or "") in {"failed", "draft"}:
            continue
        elapsed = float(now) - float(msg.get("at") or 0)
        if elapsed < AUTO_GAP_SEC:
            return float(AUTO_GAP_SEC - elapsed)
        return 0
    return 0


def _auto_reply_too_soon(thread: dict, now: int, *, mode: str = "send") -> bool:
    return _auto_gap_remaining(thread, now, mode=mode) > 0


def _auto_sends_last_hour(thread: dict, now: int) -> int:
    count = 0
    for msg in thread.get("messages") or []:
        if not msg.get("auto"):
            continue
        if str(msg.get("role") or "") != "outbound":
            continue
        if str(msg.get("kind") or "") in {"failed", "draft"}:
            continue
        if str(msg.get("status") or "") == "failed":
            continue
        if now - int(msg.get("at") or 0) < AUTO_HOUR_SEC:
            count += 1
    return count


def _match_thread(rows: list[dict], *, platform: str, sender: str, sender_id: str, chat_id: str) -> dict | None:
    named: list[dict] = []
    for row in rows:
        if row.get("platform") != platform:
            continue
        if chat_id and str(row.get("chatId") or "") == chat_id:
            return row
        if sender_id and str(row.get("senderId") or "") == sender_id:
            return row
        if not chat_id and not sender_id and sender and str(row.get("sender") or "") == sender:
            named.append(row)
    if len(named) == 1:
        return named[0]
    return None


def _find_ext(data: dict, *, platform: str, external_id: str) -> dict | None:
    if not external_id:
        return None
    for thread in data["threads"]:
        if thread.get("platform") != platform:
            continue
        for msg in thread.get("messages") or []:
            if str(msg.get("extId") or "") == external_id:
                return thread
    return None


def inbound(
    *,
    platform: str,
    sender: str,
    text: str,
    sender_id: str = "",
    chat_id: str = "",
    external_id: str = "",
    media: dict | None = None,
) -> dict:
    key = platform.strip().lower()
    if key not in PLATFORMS:
        raise ValueError("این پلتفرم پشتیبانی نمی‌شود")
    body = text.strip()
    who = sender.strip() or "مشتری"
    sid = sender_id.strip()
    cid = str(chat_id or "").strip()
    ext = str(external_id or "").strip()
    media_kind = str((media or {}).get("kind") or "").strip() if isinstance(media, dict) else ""
    media_name = str((media or {}).get("name") or "").strip() if isinstance(media, dict) else ""
    if not body:
        if media_kind:
            from app.services import chat_media_service

            body = chat_media_service.caption(media_kind)
        else:
            raise ValueError("متن پیام خالی است")
    with tenant_file_lock("inbox"):
        data = _state()
        if ext:
            existing = _find_ext(data, platform=key, external_id=ext)
            if existing is not None:
                return {"thread": _summary(existing), "messages": _messages(existing), "duplicate": True}
        thread = _match_thread(data["threads"], platform=key, sender=who, sender_id=sid, chat_id=cid)
        now = int(time.time())
        if thread is not None and _is_echo(thread, body, now=now):
            return {"thread": _summary(thread), "messages": _messages(thread), "duplicate": True, "echo": True}
        if thread is None:
            thread = {
                "id": str(uuid4()),
                "platform": key,
                "sender": who,
                "senderId": sid,
                "chatId": cid,
                "updatedAt": now,
                "messages": [],
                "paused": False,
                "autoRetries": 0,
                "lastReadAt": 0,
            }
            data["threads"].append(thread)
        if sid:
            thread["senderId"] = sid
        if cid:
            thread["chatId"] = cid
        if who:
            thread["sender"] = who
        row = {"id": str(uuid4()), "role": "inbound", "text": body, "at": now, "extId": ext}
        if media_kind and media_name:
            row["mediaKind"] = media_kind
            row["mediaName"] = media_name
        thread["messages"].append(row)
        thread["updatedAt"] = now
        thread["autoRetries"] = 0
        thread["messages"] = thread["messages"][-MSG_CAP:]
        _save(data)
    emit_later(
        kind="chat",
        surface="inbox",
        title=f"{key}-inbound",
        conversation_id=str(thread.get("id") or ""),
        turn_id=str((thread["messages"] or [{}])[-1].get("id") or ""),
        operation_id=ext,
        payload={"role": "inbound", "text": body, "platform": key, "sender": who, "threadId": thread.get("id")},
    )
    return {"thread": _summary(thread), "messages": _messages(thread), "duplicate": False}


async def handle_inbound(
    *,
    platform: str,
    sender: str,
    text: str,
    sender_id: str = "",
    chat_id: str = "",
    external_id: str = "",
    media: dict | None = None,
) -> dict:
    result = inbound(
        platform=platform,
        sender=sender,
        text=text,
        sender_id=sender_id,
        chat_id=chat_id,
        external_id=external_id,
        media=media,
    )
    if result.get("duplicate"):
        try:
            shown = get_thread(str(result["thread"]["id"]))
            shown["duplicate"] = True
            if result.get("echo"):
                shown["echo"] = True
            return shown
        except KeyError:
            return result
    thread_id = str(result["thread"]["id"])
    try:
        task = asyncio.get_running_loop().create_task(_auto_reply_safe(thread_id))
        _AUTO_TASKS.add(task)
        task.add_done_callback(_AUTO_TASKS.discard)
    except RuntimeError:
        await maybe_auto_reply(thread_id)
    try:
        return get_thread(thread_id)
    except KeyError:
        return result


async def _auto_reply_safe(thread_id: str) -> None:
    try:
        await maybe_auto_reply(thread_id)
    except Exception:
        log.exception("auto-reply failed")


async def drain_auto_replies() -> None:
    pending = [task for task in _AUTO_TASKS if not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _schedule_deferred_auto_reply(thread_id: str, wait: float) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    existing = _DEFERRED.get(thread_id)
    current = asyncio.current_task()
    if existing is not None and not existing.done() and existing is not current:
        return
    delay = max(0.05, float(wait))

    async def _run() -> None:
        try:
            await asyncio.sleep(delay)
            await maybe_auto_reply(thread_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("deferred auto-reply failed")
        finally:
            held = _DEFERRED.get(thread_id)
            if held is asyncio.current_task():
                _DEFERRED.pop(thread_id, None)

    task = loop.create_task(_run())
    _DEFERRED[thread_id] = task


async def drain_deferred_auto_replies() -> None:
    pending = [task for task in _DEFERRED.values() if not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def cancel_deferred_auto_replies() -> None:
    for task in list(_DEFERRED.values()):
        task.cancel()
    _DEFERRED.clear()


async def rearm_pending_auto_replies() -> int:
    """After a process restart, pick up unanswered inbound still waiting on the gap."""
    if not effective_auto_reply():
        return 0
    n = 0
    for thread in _state().get("threads") or []:
        if not isinstance(thread, dict):
            continue
        tid = str(thread.get("id") or "")
        if not tid or not _needs_auto_reply(thread):
            continue
        n += 1
        await maybe_auto_reply(tid)
    return n


def expire_stale_sending(stale_sec: int = SENDING_STALE_SEC) -> int:
    now = int(time.time())
    changed = 0
    with tenant_file_lock("inbox"):
        data = _state()
        for thread in data.get("threads") or []:
            if not isinstance(thread, dict):
                continue
            for msg in thread.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("status") or "") != "sending":
                    continue
                if now - int(msg.get("at") or 0) < stale_sec:
                    continue
                msg["status"] = "failed"
                msg["kind"] = "failed"
                msg["delivered"] = False
                msg["error"] = "ارسال قطع شد؛ دوباره بفرست"
                changed += 1
        if changed:
            _save(data)
    return changed


def _needs_auto_reply(thread: dict) -> str:
    if thread.get("paused"):
        return ""
    messages = thread.get("messages") or []
    last_i = -1
    last_text = ""
    for idx, msg in enumerate(messages):
        if msg.get("role") == "inbound":
            last_i = idx
            last_text = str(msg.get("text") or "")
    if last_i < 0:
        return ""
    after = messages[last_i + 1 :]
    answered = False
    has_failed = False
    for msg in after:
        kind = str(msg.get("kind") or "")
        role = str(msg.get("role") or "")
        if kind == "failed" or str(msg.get("status") or "") == "failed":
            has_failed = True
            continue
        if role == "outbound" or kind in {"draft", "outbound"}:
            answered = True
    if answered:
        return ""
    if has_failed and int(thread.get("autoRetries") or 0) >= AUTO_RETRY_MAX:
        return ""
    last_out = ""
    for msg in reversed(messages):
        if str(msg.get("role") or "") != "outbound":
            continue
        if str(msg.get("kind") or "") == "failed":
            continue
        last_out = str(msg.get("text") or "").strip()
        break
    if last_text.strip() and last_out and last_text.strip() == last_out:
        return ""
    if _is_echo(thread, last_text):
        return ""
    return last_text


def _bump_auto_retries(thread_id: str) -> int:
    with tenant_file_lock("inbox"):
        data = _state()
        thread = _find_thread(data, thread_id)
        if thread is None:
            return AUTO_RETRY_MAX
        n = int(thread.get("autoRetries") or 0) + 1
        thread["autoRetries"] = n
        _save(data)
        return n


async def maybe_auto_reply(thread_id: str) -> None:
    from app.services import voice_service

    mode = effective_auto_reply()
    if not mode:
        return
    data = _state()
    thread = _find_thread(data, thread_id)
    if thread is None or thread.get("paused"):
        return
    last = _needs_auto_reply(thread)
    if not last:
        return
    now = time.time()
    wait = _auto_gap_remaining(thread, now, mode=mode)
    if wait > 0:
        _schedule_deferred_auto_reply(thread_id, wait)
        return
    if mode == "send" and _auto_sends_last_hour(thread, now) >= AUTO_SEND_HOUR_CAP:
        return
    attempts = 0
    while attempts < AUTO_RETRY_MAX:
        attempts += 1
        draft = await voice_service.draft_reply(last, thread=thread)
        if not draft:
            emit_later(
                kind="inbox",
                surface="inbox",
                title="auto-reply-failed",
                status="failed",
                conversation_id=thread_id,
                payload={"errorClass": "llm", "mode": mode},
            )
            if _bump_auto_retries(thread_id) >= AUTO_RETRY_MAX:
                return
            continue
        try:
            await reply(
                thread_id,
                draft,
                deliver=(mode == "send"),
                as_draft=(mode == "draft"),
                auto=True,
            )
            return
        except Exception:
            if _bump_auto_retries(thread_id) >= AUTO_RETRY_MAX:
                return
            data = _state()
            thread = _find_thread(data, thread_id)
            if thread is None or not _needs_auto_reply(thread):
                return


async def reply(
    thread_id: str,
    text: str,
    *,
    deliver: bool = True,
    draft_id: str = "",
    as_draft: bool = False,
    auto: bool = False,
) -> dict:
    body = text.strip()
    if not body:
        raise ValueError("متن پاسخ خالی است")
    if not deliver:
        as_draft = True
    with tenant_file_lock("inbox"):
        data = _state()
        thread = _find_thread(data, thread_id)
        if thread is None:
            raise KeyError("گفتگو پیدا نشد")
        platform = str(thread.get("platform") or "")
        limit = REPLY_LIMITS.get(platform, 1000)
        body = body[:limit]
        now = int(time.time())
        target = None
        if draft_id:
            for msg in thread.get("messages") or []:
                if str(msg.get("id") or "") == draft_id:
                    target = msg
                    break
            if target is None:
                raise ValueError("پیش‌نویس پیدا نشد")
        sending = deliver and not as_draft
        if target is not None:
            target["text"] = body
            target["kind"] = "draft" if as_draft and not deliver else "outbound"
            target["status"] = "draft" if as_draft and not deliver else "sending"
            target["at"] = now
            target["error"] = ""
            msg_id = str(target.get("id") or "")
        else:
            msg_id = str(uuid4())
            row = {
                "id": msg_id,
                "role": "outbound",
                "kind": "draft" if as_draft and not deliver else "outbound",
                "status": "draft" if as_draft and not deliver else "sending",
                "text": body,
                "at": now,
                "delivered": False,
            }
            thread["messages"].append(row)
            target = row
        if auto:
            target["auto"] = True
        thread["updatedAt"] = now
        thread["messages"] = thread["messages"][-MSG_CAP:]
        _save(data)
    if sending:
        from app.services.channel_outbound_service import deliver as send_out

        try:
            await send_out(
                platform=str(thread.get("platform") or ""),
                sender_id=str(thread.get("senderId") or ""),
                chat_id=str(thread.get("chatId") or ""),
                text=body,
            )
        except Exception as exc:
            with tenant_file_lock("inbox"):
                data = _state()
                thread = _find_thread(data, thread_id)
                if thread is not None:
                    for msg in thread.get("messages") or []:
                        if str(msg.get("id") or "") == msg_id:
                            msg["status"] = "failed"
                            msg["kind"] = "failed"
                            msg["delivered"] = False
                            msg["error"] = str(exc)[:200] if isinstance(exc, ValueError) else "ارسال پاسخ نشد."
                            break
                    thread["delivered"] = False
                    _save(data)
            emit_later(
                kind="inbox",
                surface="inbox",
                title="auto-reply-failed",
                status="failed",
                conversation_id=thread_id,
                turn_id=msg_id,
                payload={"errorClass": "delivery", "error": str(exc)[:200]},
            )
            raise
        with tenant_file_lock("inbox"):
            data = _state()
            thread = _find_thread(data, thread_id)
            if thread is not None:
                for msg in thread.get("messages") or []:
                    if str(msg.get("id") or "") == msg_id:
                        msg["status"] = "sent"
                        msg["kind"] = "outbound"
                        msg["delivered"] = True
                        msg["error"] = ""
                        break
                thread["delivered"] = True
                _save(data)
    else:
        with tenant_file_lock("inbox"):
            data = _state()
            thread = _find_thread(data, thread_id)
            if thread is not None:
                thread["delivered"] = False
                thread["autoReply"] = "draft"
                _save(data)
    emit_later(
        kind="chat",
        surface="inbox",
        title=f"{thread.get('platform') or 'inbox'}-outbound",
        conversation_id=thread_id,
        turn_id=msg_id,
        status="ready" if sending else "draft",
        payload={
            "role": "outbound",
            "text": body,
            "platform": thread.get("platform") or "",
            "threadId": thread.get("id"),
            "delivered": bool(sending),
            "draft": bool(as_draft and not deliver),
        },
    )
    return get_thread(thread_id)
