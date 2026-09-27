"""Play one persona against the local sales gateway and score the call."""

from __future__ import annotations

import json
import re
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PERSONAS = json.loads((ROOT / "sim_personas.json").read_text(encoding="utf-8"))
RUNS = Path("/dev/shm/sozan-sim/runs.jsonl")
CTRL = 5075

BANNED = ("شماره بده", "رمز", "کارت", "عکس بفرست", "اسم پیج رو بفرست", "پیجت رو بفرست")
TO_MARK = re.compile(r"(^|[^ن])(پیجت|برات|برو |بزن )([^و]|$)")


def cmd(text: str, timeout: float = 40) -> str:
    sock = socket.create_connection(("127.0.0.1", CTRL), timeout=timeout)
    with sock:
        sock.sendall((text.strip() + "\n").encode("utf-8"))
        sock.settimeout(timeout)
        return sock.recv(16000).decode("utf-8", errors="replace").strip()


def persona_by_id(pid: str) -> dict:
    for row in PERSONAS:
        if row["id"] == pid:
            return row
    raise KeyError(pid)


def decide(persona: dict, turns: list[dict]) -> str | None:
    hidden = persona.get("hidden") or ""
    kind = persona.get("kind")
    trade = persona.get("trade") or "کالا"
    if kind == "silence":
        return None
    if kind == "carrier" and turns:
        return None
    if not turns:
        opening = persona.get("opening") or "سلام وقتتون بخیر"
        if len(opening.split()) < 3:
            opening = "سلام وقتتون بخیر"
        return opening
    last = turns[-1]
    if last.get("hangup"):
        return None
    line = (last.get("line") or "") + " " + (last.get("ear") or "")
    n = len(turns)
    asked_addr = any("کُر" in (t.get("line") or "") or "sozan-core" in (t.get("line") or "") or "ورود" in (t.get("line") or "") for t in turns)
    asked_what = any("چی می‌فروش" in (t.get("line") or "") or "می‌فروشه" in (t.get("line") or "") for t in turns)

    if kind == "nontarget":
        return "خداحافظ"

    if hidden == "repeat_addr":
        if n == 1:
            return "اسم سایتتون چیه بفرمایید"
        if n == 2:
            return "یک بار دیگه آدرس سایت رو بگید"
        if asked_addr:
            return "باشه ممنون الان بازش می‌کنم ورود رو می‌زنم"
        return "آدرس سایت رو واضح بگید"

    if hidden == "source":
        if n == 1:
            return "شماره منو از کجا آوردید اصلاً"
        if "نمی‌دونم" in line or "نمیدونم" in line or "لیست" in line or "پیج" in line:
            return "باشه پس چیکار می‌کنید دقیقاً"
        if asked_addr:
            return "باشه چشم الان میرم تو سایت و ورود رو می‌زنم"
        return "از کجا شماره منو دارید"

    if hidden == "whatsapp":
        if n == 1:
            return "تو واتساپ لینک بفرست برام"
        if asked_addr:
            return "باشه چشم الان میرم تو سایت و ورود رو می‌زنم"
        return "لینک رو تو واتساپ بده"

    if hidden == "scam":
        if n == 1:
            return "کلاهبرداری نیست این؟ از کجا معلوم"
        if asked_addr or "رایگان" in line:
            return "اگر رایگانه خودم میرم سایت ببینم"
        return "مطمئن باشم کلاه نیست"

    if hidden == "robot":
        if n == 1:
            return "رباتی تو یا آدم واقعی"
        if "دستیار" in line or "صوتی" in line:
            return f"باشه من {trade} می‌فروشم چجوری شروع کنم"
        return "واقعی هستی یا ربات"

    if hidden == "busy":
        if n == 1:
            return "سرم شلوغه سریع بگو چی می‌خوای"
        if asked_addr:
            return "باشه یادداشت کردم بعداً میام"
        return "آدرس سایت رو سریع بگو"

    if hidden == "refuse":
        if n == 1:
            return "لازم نیست ممنون نمیخوام"
        return "خداحافظ"

    if n == 1 and asked_what:
        return f"من {trade} می‌فروشم تو اینستاگرام"
    if n == 1:
        return f"من {trade} می‌فروشم، شما چیکار می‌کنید"

    if hidden == "price" and n == 2:
        return "هزینه‌ش چقدره گرون نباشه"
    if hidden == "how" and n == 2:
        return "چجوری کار می‌کنه از کجا باید شروع کنم"
    if hidden == "dm" and n == 2:
        return "پیجمو چجوری باید بهتون بدم تو دایرکت؟"
    if hidden == "trust" and n == 2:
        return "از کجا اعتماد کنم درست کار می‌کنه"
    if hidden == "later" and n == 2:
        return "الان وقت ندارم بعداً زنگ می‌زنم"
    if hidden == "has_site" and n == 2:
        return "سایت خودم رو دارم فرقش چیه"
    if hidden == "cant" and n == 2:
        return "من اصلاً بلد نیستم سایت بسازم سخت نیست"
    if hidden == "time" and n == 2:
        return "طول می‌کشه سرم شلوغه"
    if hidden == "link" and n == 2:
        return "لینک سایت رو بفرست برام"
    if hidden == "studio" and n == 2:
        return "عکس و فیلم هم می‌سازی یا فقط سایت"

    if asked_addr and hidden in {"price", "later"} and n >= 3:
        if hidden == "price" and "سوزان سی" in line:
            return "باشه چشم الان میرم تو سایت و ورود رو می‌زنم"
        if "رایگان" in line or asked_addr:
            return "باشه چشم الان میرم تو سایت و ورود رو می‌زنم"
    if asked_addr and n >= 3:
        return "باشه چشم الان میرم تو سایت و ورود رو می‌زنم"
    if n >= 4:
        return "خداحافظ"
    return "بیشتر توضیح بدید چجوری شروع کنم"


def flags_for(turns: list[dict], persona: dict) -> list[str]:
    flags = []
    lines = [t.get("line") or "" for t in turns]
    blob = " ".join(lines)
    if any(not (t.get("line") or "").strip() and t.get("kind") not in {"hold"} for t in turns):
        flags.append("empty")
    if any(part in blob for part in BANNED):
        flags.append("banned")
    for line in lines:
        padded = f" {line} "
        padded = padded.replace("پیجتون", " ").replace("براتون", " ").replace("برید ", " ").replace("بزنید", " ")
        if re.search(r" پیجت | برات | برو | بزن ", padded):
            flags.append("to-address")
            break
    if any(len((line or "").split()) > 25 and "سوزان سی" not in (line or "") for line in lines):
        flags.append("long")
    if any(float(t.get("first_audio") or 0) > 2.0 for t in turns if t.get("kind") == "model"):
        flags.append("slow")
    addr_turns = [t for t in turns if "کُر" in (t.get("line") or "") or "sozan-core" in (t.get("line") or "")]
    if addr_turns and not any("کر" in (t.get("ear") or "") or "کور" in (t.get("ear") or "") or "سوزان" in (t.get("ear") or "") for t in addr_turns):
        flags.append("addr-unheard")
    gifts = [t for t in turns if t.get("gift")]
    hidden = persona.get("hidden")
    if gifts and hidden not in {"price", "later", "refuse"}:
        flags.append("gift-early")
    cta = sum(1 for line in lines if "ورود" in line or "sozan-core" in line or "کُر" in line)
    asked = any("سایت" in (t.get("said") or "") or "آدرس" in (t.get("said") or "") or "لینک" in (t.get("said") or "") for t in turns)
    if cta > 2 and not asked:
        flags.append("cta-repeat")
    said = [t.get("said") or "" for t in turns]
    if len(lines) != len(set(lines)) and not (hidden == "repeat_addr"):
        flags.append("repeat")
    return flags


def score(persona: dict, turns: list[dict], flags: list[str]) -> int:
    kind = persona.get("kind")
    if kind == "carrier":
        return 4 if any(t.get("hangup") for t in turns) else 1
    if kind == "silence":
        return 4 if any(t.get("hangup") for t in turns) else 0
    if not turns:
        return 0
    blob = " ".join(t.get("line") or "" for t in turns)
    said = " ".join(t.get("said") or "" for t in turns)
    if "banned" in flags:
        return 0
    if kind == "nontarget":
        if any(part in blob for part in ("خداحافظ", "اشتباه", "روز", "نمی‌دونم", "نمیدونم")):
            return 3
        return 1
    agreed = any(part in said for part in ("میرم", "می‌رم", "ورود", "بازش", "باشه چشم", "باشه امروز"))
    knows = "sozan-core" in blob or "کُر" in blob or "ورود" in blob
    if agreed and knows:
        result = 4
    elif knows:
        result = 3
    elif "وبسایت" in blob or "سایت" in blob or "اینستا" in blob:
        result = 2
    else:
        result = 1
    if "empty" in flags and result >= 3:
        return result - 1
    if "empty" in flags:
        return min(result, 1)
    return result


def run_persona(pid: str) -> dict:
    persona = persona_by_id(pid)
    start = cmd(f"CALL {pid}", timeout=35)
    turns: list[dict] = []
    try:
        for _ in range(8):
            spoken = decide(persona, turns)
            if not spoken:
                break
            raw = cmd(f"SAY {spoken}", timeout=30)
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                row = {"said": spoken, "line": "", "error": raw}
            turns.append(row)
            if row.get("hangup") or "خداحافظ" in spoken:
                break
    finally:
        cmd("BYE", timeout=8)
    flags = flags_for(turns, persona)
    result = score(persona, turns, flags)
    out = {
        "id": pid,
        "name": persona.get("name"),
        "kind": persona.get("kind"),
        "hidden": persona.get("hidden"),
        "result": result,
        "flags": flags,
        "start": start,
        "turns": turns,
    }
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
    return out


def dump(row: dict) -> None:
    print(
        f"== {row['id']} {row.get('name')} kind={row.get('kind')} hidden={row.get('hidden')} result={row['result']} flags={row['flags']}",
        flush=True,
    )
    for t in row.get("turns") or []:
        print(
            f"  C: {t.get('said')}\n  S: {t.get('line')}  [heard={t.get('heard')!s:.40s} ear={t.get('ear')!s:.40s} t={t.get('elapsed')}]",
            flush=True,
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: sim_run.py p01")
    row = run_persona(sys.argv[1])
    dump(row)
