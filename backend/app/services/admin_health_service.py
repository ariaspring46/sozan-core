"""One read-only snapshot of the hub for the admin panel: is everything up, what failed in the last hour/day, money
and AI left. Every probe is independent and bounded in time; a probe that fails shows as unknown, never as an error
page. Nothing here writes state.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

import httpx

from app.config import settings

ROOT = Path(__file__).resolve().parents[3]
SERVICES = ("sozan-api", "sozan-worker", "sozan-panel", "nginx")
PHONE = re.compile(r"09\d{9}")
HTTP_LINE = re.compile(r'"(GET|POST|PATCH|PUT|DELETE) (\S+) HTTP/1\.1" (\d{3})')
PROBLEM = re.compile(r"Traceback|ERROR|Exception|failed|ConnectTimeout|did not connect", re.IGNORECASE)


def _run(args: list[str], timeout: float = 4.0) -> str:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return out.stdout
    except Exception:
        return ""


def _mask(text: str) -> str:
    return PHONE.sub(lambda m: m.group(0)[:4] + "…" + m.group(0)[-3:], text)


def services() -> dict[str, str]:
    states = _run(["systemctl", "is-active", *SERVICES]).split()
    return {name: (states[i] if i < len(states) else "unknown") for i, name in enumerate(SERVICES)}


def machine() -> dict:
    usage = shutil.disk_usage("/")
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            mem[key] = int(value.strip().split()[0])
    except Exception:
        pass
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    return {
        "diskFreeGb": round(usage.free / 1e9, 1),
        "diskUsedPct": round(usage.used * 100 / usage.total),
        "memAvailableGb": round(mem.get("MemAvailable", 0) / 1e6, 1),
        "load1": round(load[0], 2),
        "cpus": os.cpu_count() or 0,
    }


def public() -> dict:
    """The site as a visitor sees it, through the CDN, plus the 5-minute dns-watch verdict."""
    out: dict = {}
    started = time.perf_counter()
    try:
        res = httpx.get(f"{settings.public_api_url.rstrip('/')}/health", timeout=6)
        out["apiCode"] = res.status_code
    except Exception as exc:
        out["apiCode"] = 0
        out["apiError"] = type(exc).__name__
    out["apiMs"] = int((time.perf_counter() - started) * 1000)
    stamp = Path.home() / "sozan-bench" / "dns-watch.down"
    out["downSince"] = stamp.read_text().strip() if stamp.exists() else ""
    return out


def backups() -> dict:
    root = Path(os.environ.get("SOZAN_BACKUP_DIR") or Path.home() / "backups" / "sozan")
    runs = sorted(p for p in root.glob("2*") if (p / "OK").exists()) if root.is_dir() else []
    if not runs:
        return {"lastAgeHours": None}
    last = runs[-1]
    return {"lastAgeHours": round((time.time() - last.stat().st_mtime) / 3600, 1), "count": len(runs)}


def _journal(since: str) -> list[str]:
    raw = _run(["journalctl", "-u", "sozan-api", "-u", "sozan-worker", "--since", since, "-o", "short-iso", "--no-pager"], timeout=8)
    return raw.splitlines()


def logs() -> dict:
    """Counts for the last hour and day, and the latest problem lines (phones masked)."""
    day = _journal("-24h")
    hour_cut = time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() - 3600))

    def tally(lines: list[str]) -> dict:
        codes: Counter = Counter()
        otp: Counter = Counter()
        c = Counter()
        for line in lines:
            m = HTTP_LINE.search(line)
            if m:
                code = int(m.group(3))
                codes["5xx" if code >= 500 else "4xx" if code >= 400 else "ok"] += 1
                if m.group(2).startswith("/auth/otp/send") and m.group(1) == "POST":
                    otp[str(code)] += 1
                continue
            if re.search(r"llm \S+ failed", line):
                c["llmFailed"] += 1
            if "melipayamak" in line and "failed" in line:
                c["smsFailed"] += 1
            if "proxy did not connect" in line:
                c["tunnelDown"] += 1
            if "Traceback" in line:
                c["crashes"] += 1
        return {"requests": dict(codes), "otpSend": dict(otp), **dict(c)}

    hour = [line for line in day if line[:16] >= hour_cut]
    recent = [
        _mask(line.split(": ", 1)[-1])[:220]
        for line in day
        if PROBLEM.search(line) and not HTTP_LINE.search(line)
    ][-12:]
    return {"hour": tally(hour), "day": tally(day), "recent": recent}


def ai() -> dict:
    from app.services import ai_budget_service, proxy_health

    out: dict = {}
    try:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        ledger = ai_budget_service._ledger()
        out["spentTodayUsd"] = round(sum((ledger.get(today) or {}).values()), 4)
    except Exception:
        out["spentTodayUsd"] = None
    token = str(getattr(settings, "open_router_api_token", "") or os.environ.get("open_router_api_token", "")).strip()
    if token:
        fallback = proxy_health.openrouter_fallback()
        for via in dict.fromkeys([None, fallback]):  # direct first, then the fallback SOCKS
            try:
                res = httpx.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=proxy_health.timeout(6, via),
                    proxy=via,
                )
                data = (res.json() or {}).get("data") or {}
                out["openrouterLeftUsd"] = round(float(data.get("total_credits") or 0) - float(data.get("total_usage") or 0), 2)
                out.pop("openrouterError", None)
                break
            except Exception as exc:
                out["openrouterLeftUsd"] = None
                out["openrouterError"] = type(exc).__name__
    return out


def people() -> dict:
    root = settings.state_path / "tenants"
    cut = time.time() - 86400
    active = 0
    total = 0
    if root.is_dir():
        for p in root.iterdir():
            if not p.is_dir() or p.name == "_none":
                continue
            total += 1
            newest = max((f.stat().st_mtime for f in p.glob("router-*") if f.is_file()), default=0)
            if newest >= cut:
                active += 1
    return {"tenants": total, "activeToday": active}


def shops() -> dict:
    mapped = 0
    try:
        mapped = sum(1 for line in (ROOT / "deploy" / "shop-upstreams.map").read_text().splitlines() if line.strip())
    except Exception:
        pass
    running = [n for n in _run(["docker", "ps", "--format", "{{.Names}}"]).split() if n.startswith("sozan-")]
    return {"mapped": mapped, "containersUp": len(running)}


def _alerts(snap: dict) -> list[dict]:
    out: list[dict] = []

    def add(level: str, text: str) -> None:
        out.append({"level": level, "text": text})

    down = [k for k, v in snap["services"].items() if v != "active"]
    if down:
        add("red", "سرویس از کار افتاده: " + "، ".join(down))
    pub = snap["public"]
    if pub.get("apiCode") != 200:
        add("red", f"سایت از بیرون در دسترس نیست (API از راه CDN: {pub.get('apiCode') or pub.get('apiError')})")
    elif pub.get("downSince"):
        add("yellow", f"بررسی ۵ دقیقه‌ای از {pub['downSince'][:16]} خطا دیده")
    m = snap["machine"]
    if m["diskFreeGb"] < 5:
        add("red", f"دیسک کم: {m['diskFreeGb']} گیگ آزاد")
    elif m["diskFreeGb"] < 10:
        add("yellow", f"دیسک: {m['diskFreeGb']} گیگ آزاد")
    if m["memAvailableGb"] < 1:
        add("yellow", f"حافظهٔ آزاد کم: {m['memAvailableGb']} گیگ")
    b = snap["backups"].get("lastAgeHours")
    if b is None or b > 26:
        add("red", "پشتیبان شبانه بیش از یک روز است اجرا نشده")
    hour = snap["logs"]["hour"]
    if hour.get("smsFailed"):
        add("red", f"ارسال کد ورود در یک ساعت گذشته {hour['smsFailed']} بار شکست خورده")
    if hour.get("requests", {}).get("5xx", 0) >= 5:
        add("red", f"{hour['requests']['5xx']} خطای ۵xx در یک ساعت گذشته")
    if hour.get("llmFailed", 0) >= 5:
        add("yellow", f"هوش مصنوعی در یک ساعت گذشته {hour['llmFailed']} بار شکست خورده")
    if hour.get("tunnelDown"):
        add("yellow", "تونل اوپن‌روتر در یک ساعت گذشته قطع شده (مسیر مستقیم/آروان جایگزین شده)")
    left = snap["ai"].get("openrouterLeftUsd")
    if left is not None and left < 5:
        add("red" if left < 1 else "yellow", f"اعتبار اوپن‌روتر: {left} دلار")
    if snap["shops"]["containersUp"] < snap["shops"]["mapped"] - 1:
        add("yellow", f"ویترین‌های بالا {snap['shops']['containersUp']} از {snap['shops']['mapped']}")
    return out


def snapshot() -> dict:
    snap: dict = {"at": int(time.time())}
    for key, probe in (
        ("services", services),
        ("machine", machine),
        ("public", public),
        ("backups", backups),
        ("logs", logs),
        ("ai", ai),
        ("people", people),
        ("shops", shops),
    ):
        try:
            snap[key] = probe()
        except Exception as exc:
            snap[key] = {"error": type(exc).__name__}
    try:
        snap["deployed"] = (ROOT / "DEPLOYED_COMMIT").read_text().strip()[:12]
    except Exception:
        snap["deployed"] = ""
    try:
        snap["alerts"] = _alerts(snap)
    except Exception:
        snap["alerts"] = []
    return snap
