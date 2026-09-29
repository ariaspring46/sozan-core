#!/usr/bin/env python3
"""C — Sozan monitor (monitoring-plan.md MVP).

Checks (each pass):
  - landing / panel / api (+ /health paymentReady, edgeDry must be false)
  - every live storefront: DNS, HTTPS 200, certificate days left
  - heartbeat home -> hub (ssh) and observe service up
  - new observe alerts/events (credit-or-key and provider-auth alert at once,
    the rest only in the nightly summary; new dns-failed events alert at once)

Alert channel is swappable: `file` now (~/local-ai/monitor/), `telegram` the
moment TELEGRAM_BOT_TOKEN appears in ~/local-ai/config/sozan-monitor.env.
Telegram sends directly from this machine and falls back to the hub proxy.
No secrets and no customer data ever leave the process into logs or the page.

Usage:
  python3 sozan_monitor.py run              # one pass (timer: every 5 min)
  python3 sozan_monitor.py summary          # 21:30 digest (timer)
  python3 sozan_monitor.py telegram-setup   # find chat_id after owner /start
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

HOME = Path.home()
STATE_DIR = HOME / "local-ai" / "monitor"
STATE_FILE = STATE_DIR / "state.json"
HISTORY_FILE = STATE_DIR / "history.jsonl"
ALERT_LOG = STATE_DIR / "alerts.log"
STATUS_PAGE = STATE_DIR / "status.html"
ENV_FILE = HOME / "local-ai" / "config" / "sozan-monitor.env"
OBSERVE_DB = HOME / "local-ai" / "observe" / "observe.sqlite"

try:
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # noqa: BLE001 — fallback if tzdata is missing
    TEHRAN = timezone(timedelta(hours=3, minutes=30))
DOMAIN = "sozan-core.ir"
CHECK_TIMEOUT = 10
CERT_WARN_DAYS = 14
# alert classes that must page the owner immediately
HOT_CLASSES = ("credit-or-key", "provider-auth", "auth", "401", "402", "payment")

OK, WARN, FAIL = "ok", "warn", "fail"

# بند ۲۴ بازبینی: these slugs must never host a storefront.
RESERVED_SLUGS = {
    "sozan", "app", "api", "www", "admin", "ai", "ai0", "status",
    "mail", "shop", "pay", "help", "blog",
}


def count_products(host: str) -> int | None:
    """Product cards on /products; None when the page can't be read."""
    try:
        out = subprocess.run(
            ["curl", "-sL", "-m", str(CHECK_TIMEOUT), f"https://{host}/products"],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT + 5,
        ).stdout
        if not out.strip():
            return None
        return out.count("product-card") or out.count("data-price=")
    except Exception:  # noqa: BLE001
        return None


def now() -> float:
    return time.time()


def tehran(ts: float) -> str:
    return datetime.fromtimestamp(ts, TEHRAN).strftime("%H:%M:%S")


def load_state() -> dict:
    if STATE_FILE.is_file():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"checks": {}, "observe_last_id": 0, "events_last_id": 0, "telegram_chat_id": ""}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- checks


def http_status(url: str) -> tuple[str, str, str]:
    """curl carries the shell proxy env (socks5); python urllib cannot."""
    try:
        code = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", str(CHECK_TIMEOUT), url],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT + 5,
        ).stdout.strip()
        if not code or not code.isdigit():
            return FAIL, "curl-error", ""
        body = ""
        if url.endswith("/health"):
            body = subprocess.run(
                ["curl", "-s", "-m", str(CHECK_TIMEOUT), url],
                capture_output=True, text=True, timeout=CHECK_TIMEOUT + 5,
            ).stdout
        return (OK if code == "200" else FAIL), f"HTTP {code}", body
    except Exception as exc:  # noqa: BLE001
        return FAIL, type(exc).__name__, ""


def cert_days(host: str) -> tuple[str, str]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=CHECK_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
        expire = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (expire - datetime.now(timezone.utc)).days
        status = OK if days > CERT_WARN_DAYS else WARN
        return status, f"{days}d"
    except Exception as exc:  # noqa: BLE001
        return FAIL, type(exc).__name__


def dns_status(host: str) -> tuple[str, str]:
    try:
        socket.setdefaulttimeout(CHECK_TIMEOUT)
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return OK, f"{len(infos)} addr"
    except Exception as exc:  # noqa: BLE001
        return FAIL, type(exc).__name__


def storefront_slugs() -> tuple[list[str], str]:
    """Live storefront slugs from the hub containers (read-only ssh)."""
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "hub",
             "docker ps --format '{{.Names}}|{{.Ports}}' | grep '^sozan-[^|]*|.*->3000/tcp' | cut -d'|' -f1 | sed 's/^sozan-//' | sort -u"],
            capture_output=True, text=True, timeout=20,
        )
        slugs = [s for s in out.stdout.split() if s and "/" not in s]
        return slugs, ("" if slugs else "ssh empty")
    except Exception as exc:  # noqa: BLE001
        return [], type(exc).__name__


def check_pass() -> tuple[dict, list[str]]:
    """Run every check once; returns (results, notes for the summary)."""
    results: dict[str, dict] = {}
    notes: list[str] = []

    def record(cid: str, status: str, detail: str) -> None:
        results[cid] = {"status": status, "detail": detail, "ts": now()}

    status, detail, _ = http_status(f"https://{DOMAIN}/")
    record("landing", status, detail)
    status, detail, _ = http_status(f"https://app.{DOMAIN}/")
    record("panel", status, detail)

    status, detail, body = http_status(f"https://api.{DOMAIN}/health")
    health = ""
    try:
        health = json.loads(body)
    except Exception:  # noqa: BLE001
        pass
    if status == OK and isinstance(health, dict):
        edge = health.get("edgeDry")
        payment = health.get("paymentReady")
        notes.append(f"paymentReady={payment}")
        if edge:
            status, detail = FAIL, "edgeDry=true on production"
        else:
            detail = f"ok paymentReady={payment}"
    record("api", status, detail)

    slugs, ssh_err = storefront_slugs()
    if ssh_err:
        record("hub-ssh", FAIL, ssh_err)
    else:
        record("hub-ssh", OK, f"{len(slugs)} shops")
    for slug in slugs:
        host = f"{slug}.{DOMAIN}"
        if slug in RESERVED_SLUGS:
            record(f"reserved:{slug}", WARN, "اسلاگ رزروشده در حال استفاده")
        d_status, d_detail = dns_status(host)
        record(f"dns:{slug}", d_status, d_detail)
        h_status, h_detail, _ = http_status(f"https://{host}/")
        record(f"shop:{slug}", h_status, h_detail)
        c_status, c_detail = cert_days(host)
        record(f"cert:{slug}", c_status, c_detail)
        n_products = count_products(host)
        if n_products is not None:
            record(f"catalog:{slug}", OK if n_products > 0 else WARN,
                   f"{n_products} کالا" if n_products else "کاتالوگ خالی")

    observe = subprocess.run(
        ["systemctl", "--user", "is-active", "sozan-observe.service"],
        capture_output=True, text=True,
    ).stdout.strip()
    record("observe-home", OK if observe == "active" else FAIL, observe or "unknown")
    return results, notes


# ---------------------------------------------------------------- observe feed


def observe_news(state: dict) -> tuple[list[dict], list[dict]]:
    """New alerts + dns-failed events since the last pass (read-only sqlite)."""
    alerts: list[dict] = []
    events: list[dict] = []
    if not OBSERVE_DB.is_file():
        return alerts, events
    try:
        db = sqlite3.connect(f"file:{OBSERVE_DB}?mode=ro", uri=True, timeout=5)
        last_a = int(state.get("observe_last_id") or 0)
        last_e = int(state.get("events_last_id") or 0)
        for row in db.execute(
            "SELECT id, ts, error_class, title FROM alerts WHERE id > ? ORDER BY id", (last_a,)
        ):
            alerts.append({"id": row[0], "ts": row[1], "class": row[2], "title": row[3]})
        for row in db.execute(
            "SELECT id, ts, kind, title FROM events WHERE id > ? AND kind IN ('dns-failed','watchdog') ORDER BY id",
            (last_e,),
        ):
            events.append({"id": row[0], "ts": row[1], "kind": row[2], "title": row[3]})
        if alerts:
            state["observe_last_id"] = alerts[-1]["id"]
        if events:
            state["events_last_id"] = events[-1]["id"]
        # first run: swallow history, alert only on the new ones
        if not last_a and alerts:
            state["observe_last_id"] = alerts[-1]["id"]
            alerts = []
        if not last_e and events:
            state["events_last_id"] = events[-1]["id"]
            events = []
    except Exception:  # noqa: BLE001
        pass
    return alerts, events


def hot_alerts(alerts: list[dict], events: list[dict]) -> list[str]:
    hot: list[str] = []
    for a in alerts:
        blob = f"{a['class']} {a['title']}"
        if any(k in blob for k in HOT_CLASSES):
            hot.append(f"هشدار {DOMAIN}: خطای سرویس مدل/پیامک ({a['class']}: {a['title']})")
    for e in events:
        hot.append(f"هشدار سوزان: رویداد {e['kind']} ({e['title']})")
    return hot


# ---------------------------------------------------------------- channels


def load_env() -> dict:
    env = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def telegram_send(text: str) -> bool:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        api, data=data, headers={"Content-Type": "application/json"}
    )
    for attempt in ("direct", "hub-proxy"):
        try:
            if attempt == "direct":
                with urllib.request.urlopen(req, timeout=15) as res:
                    res.read()
                return True
            # hub fallback: telegram is blocked from Iranian IPs; ride CHANNEL_PROXY
            cmd = (
                "set -a; . ~/sozan-core/.env 2>/dev/null; set +a; "
                f"curl -s --max-time 20 --proxy \"$CHANNEL_PROXY\" -X POST -H 'Content-Type: application/json' "
                f"-d {json.dumps(json.dumps({'chat_id': chat, 'text': text}))!r} "
                f"-w '%{{http_code}}' '{api}'"
            )
            out = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "hub", cmd],
                capture_output=True, text=True, timeout=30,
            )
            if out.stdout.strip().endswith("200"):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def notify(text: str) -> None:
    """Channel order: telegram when configured, file always."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now(), TEHRAN).strftime("%Y-%m-%d %H:%M:%S")
    with ALERT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {text}\n")
    telegram_send(text)


# ---------------------------------------------------------------- state, page


def apply_transitions(state: dict, results: dict) -> list[str]:
    """Alert once on fail start and once on recovery; combine one pass into one message."""
    messages: list[str] = []
    prev = state.get("checks", {})
    down_now, recovered = [], []
    for cid, res in results.items():
        was = prev.get(cid, {}).get("status")
        if res["status"] == FAIL and was != FAIL:
            down_now.append(f"{cid} ↓ {res['detail']}")
        elif res["status"] != FAIL and was == FAIL:
            recovered.append(f"{cid} ↑")
    if down_now:
        messages.append("هشدار سوزان: " + "؛ ".join(down_now))
    if recovered:
        messages.append("سوزان: برگشت — " + "؛ ".join(recovered))
    state["checks"] = results
    return messages


def history_append(results: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": now(), "n": len(results),
           "fail": sum(1 for r in results.values() if r["status"] == FAIL),
           "warn": sum(1 for r in results.values() if r["status"] == WARN)}
    with HISTORY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


LABEL = {"ok": "سبز", "warn": "زرد", "fail": "قرمز"}


def write_status_page(results: dict, notes: list[str]) -> None:
    rows = []
    for cid, res in sorted(results.items()):
        rows.append(
            f"<tr class={res['status']}><td>{cid}</td><td>{LABEL[res['status']]}</td>"
            f"<td>{res['detail']}</td><td>{tehran(res['ts'])}</td></tr>"
        )
    n_fail = sum(1 for r in results.values() if r["status"] == FAIL)
    n_warn = sum(1 for r in results.values() if r["status"] == WARN)
    overall = "قرمز" if n_fail else ("زرد" if n_warn else "سبز")
    html = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>وضعیت سوزان</title><style>
body{{font-family:system-ui,Tahoma;background:#F7F4EE;color:#1A1714;margin:1rem}}
h1{{font-size:1.1rem}} table{{border-collapse:collapse;width:100%;font-size:.85rem}}
td,th{{padding:.35rem .5rem;border-bottom:1px solid #eee;text-align:right}}
tr.fail td{{background:#fde8e8}} tr.warn td{{background:#fff6e0}} tr.ok td{{color:#1A1714}}
.badge{{display:inline-block;padding:.2rem .7rem;border-radius:1rem;font-weight:700}}
.ok .badge,.badge.ok{{background:#dcf5e3}} .badge.warn{{background:#fff1c2}} .badge.fail{{background:#f9d3d3}}
small{{color:#6b6257}}</style></head><body>
<h1>وضعیت سوزان — <span class="badge {n_fail and 'fail' or n_warn and 'warn' or 'ok'}">{overall}</span></h1>
<p><small>آخرین بررسی: {tehran(now())} تهران — {len(results)} بررسی، {n_fail} قرمز، {n_warn} زرد. {' — '.join(notes)}</small></p>
<table><tr><th>بخش</th><th>وضعیت</th><th>جزئیات</th><th>ساعت</th></tr>{''.join(rows)}</table>
<p><small>هشدارها: {'فایل محلی' if not load_env().get('TELEGRAM_BOT_TOKEN') else 'تلگرام + فایل'} — وضعیت این صفحه تا پایش هاب منتقل شود فقط روی ماشین خانه است.</small></p>
</body></html>"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PAGE.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------- commands


def cmd_run() -> int:
    state = load_state()
    results, notes = check_pass()
    for message in apply_transitions(state, results):
        notify(message)
    alerts, events = observe_news(state)
    for message in hot_alerts(alerts, events):
        notify(message)
    history_append(results)
    write_status_page(results, notes + [f"هشدارهای observe: {len(alerts)}"])
    save_state(state)
    n_fail = sum(1 for r in results.values() if r["status"] == FAIL)
    print(f"pass done: {len(results)} checks, {n_fail} fail, {len(alerts)} observe alerts")
    return 0


def cmd_summary() -> int:
    state = load_state()
    results = state.get("checks", {})
    n_fail = sum(1 for r in results.values() if r["status"] == FAIL)
    n_warn = sum(1 for r in results.values() if r["status"] == WARN)
    day_ago = now() - 86400
    fails = warns = passes = 0
    if HISTORY_FILE.is_file():
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if row.get("ts", 0) >= day_ago:
                fails += row.get("fail", 0)
                warns += row.get("warn", 0)
                passes += row.get("n", 0) - row.get("fail", 0) - row.get("warn", 0)
    total = fails + warns + passes
    uptime = (100 * passes / total) if total else 100
    lines = [
        "خلاصهٔ شبانهٔ سوزان:",
        f"وضعیت فعلی: {len(results)} بررسی، {n_fail} قرمز، {n_warn} زرد.",
        f"۲۴ ساعت اخیر: {uptime:.0f}٪ سبز.",
    ]
    bad = [cid for cid, r in results.items() if r["status"] != "ok"]
    if bad:
        lines.append("قرمز/زرد: " + "، ".join(bad))
    else:
        lines.append("همهٔ بخش‌ها سبز.")
    notify("\n".join(lines))
    print("summary sent")
    return 0


def cmd_telegram_setup() -> int:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(f"TELEGRAM_BOT_TOKEN را در {ENV_FILE} بگذارید (دسترسی 600) و به بات /start بدهید، بعد این دستور را دوباره بزنید.")
        return 1
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15) as res:
            data = json.loads(res.read())
    except Exception as exc:  # noqa: BLE001
        print("direct getUpdates failed:", type(exc).__name__, "— trying hub proxy")
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "hub",
             "set -a; . ~/sozan-core/.env 2>/dev/null; set +a; "
             f"curl -s --max-time 20 --proxy \"$CHANNEL_PROXY\" '{f'https://api.telegram.org/bot{token}/getUpdates'}'"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(out.stdout)
        except Exception:  # noqa: BLE001
            print("hub proxy failed too; no secrets printed")
            return 1
    chats = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid:
            chats[cid] = chat.get("first_name") or chat.get("title") or str(cid)
    if not chats:
        print("هیچ گفتگویی پیدا نشد؛ اول به بات /start بدهید.")
        return 1
    state = load_state()
    for cid, name in chats.items():
        print(f"chat_id={cid} ({name})")
    state["telegram_chat_id"] = str(next(iter(chats)))
    save_state(state)
    print(f"پیش‌فرض ذخیره شد: {state['telegram_chat_id']} — برای قفل کردن، TELEGRAM_CHAT_ID را در env بگذارید.")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "run":
        return cmd_run()
    if command == "summary":
        return cmd_summary()
    if command == "telegram-setup":
        return cmd_telegram_setup()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
