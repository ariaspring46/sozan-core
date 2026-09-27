"""Outbound campaign runner. Dry-run unless --dial NUMBER is passed.

Numbers stay in ~/local-ai/config/sozan-campaign.json. This file never dials
by itself and never reads the SIP password.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sales import CAMPAIGN_PATH, DNC_PATH
from sip import normalize_dial

LOG_PATH = Path.home() / "local-ai" / "sozan-voice-log" / "calls.jsonl"
DIAL_HOST = "127.0.0.1"
DIAL_PORT = 5072


def load_list(path: Path) -> dict:
    if not path.is_file():
        return {"source": "", "contacts": [], "windows": [[10, 13], [16, 20]], "gap_s": 45, "daily_cap": 20, "tz": "Asia/Tehran"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("campaign file must be an object")
    return raw


def dnc_numbers() -> set[str]:
    if not DNC_PATH.is_file():
        return set()
    return {normalize_dial(line) for line in DNC_PATH.read_text(encoding="utf-8").splitlines() if normalize_dial(line)}


def within_hours(spec: dict, now: datetime | None = None) -> bool:
    tz = ZoneInfo(str(spec.get("tz") or "Asia/Tehran"))
    moment = now or datetime.now(tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    else:
        moment = moment.astimezone(tz)
    hour = moment.hour
    windows = spec.get("windows") or [[10, 13], [16, 20]]
    return any(int(start) <= hour < int(end) for start, end in windows)


def calls_today(now: datetime | None = None) -> int:
    tz = ZoneInfo("Asia/Tehran")
    moment = now or datetime.now(tz)
    day = moment.astimezone(tz).date().isoformat()
    if not LOG_PATH.is_file():
        return 0
    count = 0
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = float(row.get("ts") or 0)
        if ts and datetime.fromtimestamp(ts, tz).date().isoformat() == day and row.get("kind") == "hello":
            count += 1
    return count


def eligible(spec: dict) -> list[dict]:
    if str(spec.get("source") or "") != "instagram-shops":
        raise SystemExit("source must be instagram-shops, or change the spoken number-source line first")
    blocked = dnc_numbers()
    found = []
    for row in spec.get("contacts") or []:
        if not isinstance(row, dict):
            continue
        phone = normalize_dial(str(row.get("phone") or ""))
        if not phone or phone in blocked:
            continue
        found.append(row)
    return found


def dial_one(number: str) -> str:
    sock = socket.create_connection((DIAL_HOST, DIAL_PORT), timeout=8)
    with sock:
        sock.sendall(f"DIAL {number}\n".encode())
        sock.settimeout(8)
        return sock.recv(200).decode("utf-8", errors="replace").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dial", default="", help="one number, only when the owner asked")
    parser.add_argument("--file", default=str(CAMPAIGN_PATH))
    args = parser.parse_args()
    spec = load_list(Path(args.file))
    rows = eligible(spec)
    open_now = within_hours(spec)
    used = calls_today()
    cap = int(spec.get("daily_cap") or 20)
    print(f"contacts {len(rows)} hours={'open' if open_now else 'closed'} today={used}/{cap} gap_s={spec.get('gap_s') or 45}")
    if not args.dial:
        for row in rows[:10]:
            print(normalize_dial(str(row.get("phone") or "")), row.get("instagram") or "")
        return 0
    number = normalize_dial(args.dial)
    if not number:
        print("missing number")
        return 2
    if number not in {normalize_dial(str(row.get("phone") or "")) for row in rows}:
        print("number is not in the list or is on the do-not-call file")
        return 2
    if not open_now:
        print("outside calling hours")
        return 2
    if used >= cap:
        print("daily cap reached")
        return 2
    print(dial_one(number))
    return 0


if __name__ == "__main__":
    sys.exit(main())
