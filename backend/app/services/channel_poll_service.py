from __future__ import annotations

import logging
import time

from app.services import (
    channel_service,
    instagram_oauth_service,
    instagram_service,
    plan_service,
    telegram_service,
    unipile_service,
)
from app.services.observe_client import emit_later
from app.state_store import iter_tenants, tenant_scope

log = logging.getLogger("sozan.channel-poll")
_IG_GAP_SEC = 30.0
_BACKOFF_SEC = 300.0
_FAIL_LIMIT = 3
_last_ig: dict[str, float] = {}
_fail_counts: dict[str, int] = {}
_backoff_until: dict[str, float] = {}
_gap_skips: dict[str, int] = {}
_poll_skip_emitted: set[str] = set()


def _poll_key(phone: str, platform: str, handle: str) -> str:
    return f"{phone}:{platform}:{handle}"


def _in_backoff(key: str) -> bool:
    until = _backoff_until.get(key) or 0.0
    return time.monotonic() < until


def _ig_due(key: str, now: float) -> bool:
    last = _last_ig.get(key) or 0.0
    if now - last < _IG_GAP_SEC:
        _gap_skips[key] = int(_gap_skips.get(key) or 0) + 1
        if _gap_skips[key] >= 2 and key not in _poll_skip_emitted:
            _poll_skip_emitted.add(key)
            emit_later(
                kind="channel",
                surface="inbox",
                title="poll-skip",
                payload={"key": key},
            )
        return False
    return True


def _mark_ig_polled(key: str, now: float) -> None:
    _last_ig[key] = now
    _gap_skips.pop(key, None)
    _poll_skip_emitted.discard(key)


def _note_poll_result(key: str, ok: bool) -> None:
    if ok:
        _fail_counts.pop(key, None)
        _backoff_until.pop(key, None)
        return
    n = int(_fail_counts.get(key) or 0) + 1
    _fail_counts[key] = n
    if n >= _FAIL_LIMIT:
        _backoff_until[key] = time.monotonic() + _BACKOFF_SEC
        _fail_counts[key] = 0


async def poll_tenant() -> None:
    from app.state_store import current_tenant

    phone = current_tenant()
    now = time.monotonic()
    for row in channel_service.iter_accounts():
        token = channel_service.token_for(row)
        platform = str(row.get("platform") or "")
        handle = str(row.get("handle") or "")
        unipile_id = channel_service.unipile_account_id(row) if platform == "instagram" else ""
        if not token and not unipile_id:
            continue
        if platform == "telegram":
            if not plan_service.current().get("dmSync"):
                continue
            key = _poll_key(phone, platform, handle)
            if _in_backoff(key):
                continue
            result = await telegram_service.pull_updates(token=token, handle=handle)
            ok = bool(result.get("ok"))
            _note_poll_result(key, ok)
            if not ok:
                log.warning("telegram poll: %s", result.get("error") or "failed")
                emit_later(
                    kind="channel",
                    surface="inbox",
                    title="telegram-poll-error",
                    payload={"error": str(result.get("error") or "failed")[:200], "handle": handle},
                )
            continue
        if platform == "instagram":
            if unipile_id:
                if not plan_service.current().get("dmSync"):
                    continue
                key = _poll_key(phone, platform, handle or unipile_id)
                if not _ig_due(key, now):
                    continue
                if _in_backoff(key):
                    continue
                _mark_ig_polled(key, now)
                result = await unipile_service.pull_directs(account_id=unipile_id, handle=handle)
            else:
                await instagram_oauth_service.refresh_row(row)
                row = channel_service.secret_for(str(row.get("id") or "")) or row
                token = channel_service.token_for(row)
                if not plan_service.current().get("dmSync"):
                    continue
                key = _poll_key(phone, platform, handle)
                if not _ig_due(key, now):
                    continue
                if _in_backoff(key):
                    continue
                _mark_ig_polled(key, now)
                result = await instagram_service.pull_directs(token=token, handle=handle)
            ok = bool(result.get("ok"))
            _note_poll_result(key, ok)
            if not ok:
                log.warning("instagram poll: %s", result.get("error") or "failed")
                emit_later(
                    kind="channel",
                    surface="inbox",
                    title="instagram-poll-error",
                    payload={"error": str(result.get("error") or "failed")[:200], "handle": handle},
                )


async def poll_all() -> None:
    for phone in iter_tenants():
        with tenant_scope(phone):
            await poll_tenant()
