"""Offline sales-call simulator. Uses ornith-phone and the live SalesState machine."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from brain import Brain
from sales import (
    ADDRESS_LINE,
    HELLO_LINE,
    SalesState,
    finish_spoken,
    gift_line,
    note_spoken,
    plan_turn,
    sales_open,
)

os.environ.setdefault("GIFT_CODE_SPOKEN", "سوزان سی")
os.environ.setdefault("LLM_URL", "http://127.0.0.1:19292/v1")
os.environ.setdefault("LLM_MODEL", "ornith-phone")

PATHS: list[dict] = [
    {"name": "salon", "turns": ["سلام", "من آرایشگاه دارم", "چجوری شروع کنم", "باشه"], "gift": False},
    {"name": "busy", "turns": ["الو", "سرم شلوغه", "بعداً"], "gift": True},
    {"name": "price", "turns": ["سلام سوزان", "گرونه", "پرو چقدره"], "gift": True},
    {"name": "trust", "turns": ["سلام", "اعتماد ندارم", "کارت نمیخوام"], "gift": False},
    {"name": "has-site", "turns": ["سلام", "سایت دارم", "پس فرقش چیه"], "gift": False},
    {"name": "cant", "turns": ["سلام", "بلد نیستم", "پیجمو چجوری بدم"], "gift": False},
    {"name": "send-link", "turns": ["سلام", "لینکو بفرست", "کجا برم"], "gift": False},
    {"name": "robot", "turns": ["سلام", "رباتی؟", "خب سایت کجاست"], "gift": False},
    {"name": "later-gift", "turns": ["سلام", "بعداً زنگ میزنم"], "gift": True},
    {"name": "bye-early", "turns": ["سلام", "خداحافظ"], "gift": False},
    {"name": "hold-music", "turns": ["ترایلی دارم", "سلام"], "gift": False},
    {"name": "talk", "turns": ["صحبت کن", "چی میفروشی این"], "gift": False},
    {"name": "studio", "turns": ["سلام", "عکس و فیلم هم میسازی", "باشه میرم سایت"], "gift": False},
    {"name": "page-name", "turns": ["سلام", "پیجمو چجوری بدم", "تو تماس بفرستم"], "gift": False},
    {"name": "where-panel", "turns": ["سلام", "توی کدوم پنل عکس بفرستم"], "gift": False},
    {"name": "howdy", "turns": ["سوزان حالت چطوره", "برای آنلاین شاپ هم هست"], "gift": False},
    {"name": "bag", "turns": ["سلام", "کیف میفروشم تو دایرکت", "باز کردم"], "gift": False},
    {"name": "refuse", "turns": ["سلام", "لازم نیست", "گرونه"], "gift": True},
    {"name": "noise-then", "turns": ["چه خوشگله کنار", "سلام سوزان چیه"], "gift": False},
    {"name": "cost", "turns": ["سلام", "هزینه شو چجوری باید پرداخت کنم"], "gift": True},
    {"name": "who", "turns": ["سلام", "برای چه مشاغلی به کار میاد"], "gift": False},
    {"name": "more", "turns": ["سلام", "چه کارایی دیگه داری", "اوکی میرم"], "gift": False},
    {"name": "fragment", "turns": ["سلام", "میخوام برام بسازی", "اسم سایت چیه"], "gift": False},
    {"name": "confirm", "turns": ["سلام", "کجا شروع کنم", "آره باز کردم"], "gift": False},
    {"name": "thanks-bye", "turns": ["سلام", "باشه ممنون خدا"], "gift": False},
    {"name": "ask-site-three", "turns": ["سلام", "اسم سایتتون چیه", "دوباره بگو آدرس", "آدرس سایت چیه"], "gift": False},
    {"name": "discount", "turns": ["سلام", "تخفیف دارید؟"], "gift": True},
    {"name": "what-do", "turns": ["سلام", "چه کارایی به ما انجام میدی"], "gift": False},
]

BANNED = ("همین تماس", "همین‌جا بنویس", "عکس بفرست", "شماره بده", "رمز", "کارت")


def _run_path(brain: Brain, path: dict) -> dict:
    state = SalesState()
    brain.start_sales(sales_open(), HELLO_LINE)
    lines = [f"Sozan: {HELLO_LINE}"]
    spoken_all: list[str] = []
    gifts = 0
    first_times: list[float] = []
    for heard in path["turns"]:
        plan = plan_turn(state, heard)
        if plan.kind == "hold":
            lines.append(f"User: {heard} -> HOLD")
            continue
        if plan.kind in {"hello", "close", "address"}:
            spoken = plan.line or HELLO_LINE
            brain.commit_assistant(spoken)
            note_spoken(state, spoken)
            spoken_all.append(spoken)
            lines.append(f"User: {heard}")
            lines.append(f"Sozan: {spoken}")
            first_times.append(0.0)
            continue
        started = time.monotonic()
        raw_parts = []
        for bit in brain.sales_stream(plan.cue):
            raw_parts.append(str(bit.get("sentence") or ""))
            if not first_times or first_times[-1] == -1:
                pass
            if len(raw_parts) >= 2:
                break
        first_times.append(float(brain.last_sales_stats.get("first_token_s") or (time.monotonic() - started)))
        raw = " ".join(raw_parts)
        spoken, tags = finish_spoken(raw, state, heard)
        if "gift" in tags and plan.allow_gift and not state.gifted:
            spoken = f"{spoken} {gift_line()}".strip()
            state.gifted = True
            gifts += 1
        if not spoken:
            spoken = "بگو، گوش می‌کنم."
        brain.commit_assistant(raw or spoken)
        note_spoken(state, spoken)
        spoken_all.append(spoken)
        lines.append(f"User: {heard}")
        lines.append(f"Sozan: {spoken}")
        if "end" in tags or plan.kind == "close":
            break
    return {
        "name": path["name"],
        "lines": lines,
        "spoken": spoken_all,
        "gifts": gifts,
        "linked": state.linked or any("sozan-core" in line or "ورود" in line for line in spoken_all),
        "first_times": first_times,
        "want_gift": path["gift"],
        "turns": len([line for line in lines if line.startswith("User:")]),
    }


def _check(row: dict) -> list[str]:
    reasons = []
    spoken = row["spoken"]
    if any(not (item or "").strip() for item in spoken):
        reasons.append("empty")
    repeated = [item for item in spoken if item != ADDRESS_LINE and spoken.count(item) > 1]
    if repeated:
        reasons.append("repeat")
    blob = " ".join(spoken)
    if any(part in blob for part in BANNED):
        reasons.append("banned")
    if row["turns"] >= 4 and not row["linked"] and row["name"] not in {"hold-music", "noise-then"}:
        reasons.append("no-cta")
    cta_hits = sum(1 for item in spoken if "sozan-core" in item or "ورود" in item or "کُر" in item)
    if cta_hits > 2 and row["name"] not in {"ask-site-three", "fragment", "confirm", "send-link"}:
        reasons.append("cta-repeat")
    if row["name"] in {"ask-site-three", "fragment", "confirm"} and not any(
        "کُر" in item or "sozan-core" in item or "ورود" in item for item in spoken
    ):
        reasons.append("no-address")
    if row["want_gift"] is False and row["gifts"]:
        reasons.append("gift-unwanted")
    if row["want_gift"] and row["gifts"] > 1:
        reasons.append("gift-twice")
    return reasons


def main() -> None:
    brain = Brain()
    try:
        brain.wait_until_ready(20)
    except Exception as exc:
        raise SystemExit(f"ornith-phone not ready: {exc}") from exc
    brain.start_sales(sales_open(), HELLO_LINE)
    try:
        brain.warm_sales(sales_open(), HELLO_LINE)
    except Exception:
        pass
    failed = 0
    for path in PATHS:
        row = _run_path(brain, path)
        reasons = _check(row)
        status = "ok" if not reasons else "fail:" + ",".join(reasons)
        if reasons:
            failed += 1
        print(f"{status}\t{path['name']}\tcta={row['linked']}\tgift={row['gifts']}\ttimes={row['first_times']}")
        for line in row["lines"]:
            print(f"  {line}")
    print(f"paths {len(PATHS)} failed {failed}")
    if failed:
        raise SystemExit(failed)


def gpu1_phone_only() -> bool:
    import json
    import urllib.request

    blocked = {"qwen3.8-27b", "ornith-1.5-35b", "gpt-oss-20b", "qwen3-coder-next"}
    try:
        with urllib.request.urlopen("http://127.0.0.1:19292/running", timeout=3) as res:
            rows = json.loads(res.read().decode()).get("running") or []
    except Exception as exc:
        print(f"eval refused; llama-swap unreachable: {exc}")
        return False
    loaded = {str(row.get("model") or "") for row in rows}
    if "ornith-phone" not in loaded:
        print("eval refused; ornith-phone is not loaded")
        return False
    extra = loaded & blocked
    if extra:
        print(f"eval refused; other GPU1 models loaded: {sorted(extra)}")
        return False
    return True


if __name__ == "__main__":
    if not gpu1_phone_only():
        raise SystemExit(2)
    main()
