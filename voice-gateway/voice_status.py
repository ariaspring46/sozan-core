"""Phone-line status for monitoring. Counts only. No speech, numbers, or secrets."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tehran")
LOG = Path.home() / "local-ai" / "sozan-voice-log" / "calls.jsonl"
OUT = Path.home() / "local-ai" / "sozan-voice-log" / "status.json"


def _journal(since: str) -> str:
    return subprocess.check_output(
        ["journalctl", "--user", "-u", "sozan-voice.service", "--since", since, "--no-pager", "-o", "cat"],
        text=True,
        errors="replace",
    )


def _today_rows() -> list[dict]:
    if not LOG.is_file():
        return []
    day = datetime.now(TZ).date()
    rows = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("sim"):
            continue
        ts = float(row.get("ts") or 0)
        if not ts:
            continue
        if datetime.fromtimestamp(ts, TZ).date() != day:
            continue
        rows.append(row)
    return rows


def _calls(rows: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    previous = 0.0
    for row in rows:
        ts = float(row.get("ts") or 0)
        if current and ts - previous > 45:
            groups.append(current)
            current = []
        current.append(row)
        previous = ts
    if current:
        groups.append(current)
    return groups


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def build() -> dict:
    now = datetime.now(TZ)
    recent = _journal("3 min ago")
    today = _journal("today")
    rows = _today_rows()
    groups = _calls(rows)
    gaps = [
        float(row.get("first_audio") or 0) + 0.45
        for row in rows
        if row.get("kind") == "model" and float(row.get("first_audio") or 0) > 0
    ]
    interested = 0
    for group in groups:
        kinds = {str(row.get("kind") or "") for row in group}
        if kinds & {"address", "feature", "model"}:
            interested += 1
    return {
        "ts": now.isoformat(timespec="seconds"),
        "sip_registered": "sip registered" in recent,
        "stt_ready": False,
        "calls_today": len(groups),
        "errors_today": sum(line.count("sales stream failed") + line.count("sip dial failed") + line.count("dial refused") for line in today.splitlines()),
        "answer_gap_median_s": _median(gaps),
        "outcomes_today": {
            "answered": len(groups),
            "interested": interested,
            "dnc": today.count("sales outcome dnc"),
            "error": today.count("sales stream failed") + today.count("sip dial failed"),
        },
        "speech_in_training": False,
    }


def main() -> None:
    # stt_ready needs the service to be active, not a stale journal line alone.
    active = subprocess.check_output(
        ["systemctl", "--user", "is-active", "sozan-voice.service"],
        text=True,
        errors="replace",
    ).strip()
    status = build()
    today = _journal("today")
    status["stt_ready"] = active == "active" and "fast stt ready" in today
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT.chmod(0o644)
    gap = status["answer_gap_median_s"]
    gap_s = "none" if gap is None else f"{gap:.2f}"
    print(
        "STATUS"
        f" sip={int(status['sip_registered'])}"
        f" stt={int(status['stt_ready'])}"
        f" calls={status['calls_today']}"
        f" errors={status['errors_today']}"
        f" gap={gap_s}"
    )


if __name__ == "__main__":
    main()
