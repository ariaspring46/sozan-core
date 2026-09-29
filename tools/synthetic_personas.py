#!/usr/bin/env python3
"""Synthetic persona data for the finetune trial (owner 16:05 #3).

Five shop personas — پوشاک، جواهر، قهوه، لوازم، زیبایی. Customer questions are
template-built from each persona's catalog, so the ground truth of every turn
is known by construction. Answers come from the real inbox agent on its cloud
chain; each reply then passes an auto-check for its intent, and only accepted
samples get the label {"accept": true}. Router samples carry the constructed
tool call as ground truth. Nothing here touches the locked batteries; no real
customer text is involved; the training_log pipeline masks and hashes as usual.

Run with the backend venv: backend/.venv/bin/python tools/synthetic_personas.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

_PHONE = "09121120088"

# (title, price, stock, colors, size)
PERSONAS = (
    {
        "name": "بوتیک آیدا",
        "slug": "aida-wear",
        "domain": "پوشاک",
        "items": [
            ("مانتو کرپ", 1250000, 4, ("کرم", "سرمه‌ای"), "۳۸"),
            ("شومیز حریر", 690000, 7, ("صورتی", "مشکی"), ""),
            ("شلوار پارچه‌ای", 980000, 3, ("طوسی",), "۴۰"),
            ("دامن کلوش", 760000, 0, ("زرد",), ""),
            ("کت جلو باز", 1980000, 2, ("کرم", "سبز"), "۴۲"),
            ("بلوز آستین کوتاه", 420000, 9, ("سفید", "آبی"), ""),
        ],
        "policy": {"shippingCost": 55000, "shippingMethod": "پست پیشتاز", "returnDays": 7, "cardToCard": "۶۰۳۷-۹۹۷۵-XXXX-XXXX به نام آ. رضایی"},
        "out": "کتانی ورزشی",
        "chit": ("سلام، سفارشم کی پست میشه؟", "مرسی از راهنمایی"),
    },
    {
        "name": "گالری زرین",
        "slug": "zarrin-gallery",
        "domain": "جواهر",
        "items": [
            ("گردنبند نقره ماه", 1450000, 5, ("نقره‌ای",), ""),
            ("انگشتر رینگ استیل", 890000, 6, ("طلایی", "نقره‌ای"), "۵۴"),
            ("گوشواره مروارید", 1750000, 2, ("سفید",), ""),
            ("دستبند چرم و استیل", 620000, 8, ("قهوه‌ای",), ""),
            ("ست کامل عروس", 5400000, 1, ("طلایی",), ""),
            ("آویز تسمه", 380000, 0, ("نقره‌ای",), ""),
        ],
        "policy": {"shippingCost": 70000, "shippingMethod": "تیپاکس", "returnDays": 3, "cardToCard": ""},
        "out": "ساعت مچی چرم",
        "chit": ("بسته‌بندی کادو دارید؟", "ممنون"),
    },
    {
        "name": "قهوه خانه رست",
        "slug": "roast-house",
        "domain": "قهوه",
        "items": [
            ("دانه عربیکا اتیوپی", 890000, 6, (), "۲۵۰ گرم"),
            ("دانه روبوستا برزیل", 650000, 8, (), "۱ کیلوگرم"),
            ("قوطی دم‌کردی", 320000, 4, ("استیل",), ""),
            ("مولکول قهوه فرانسه", 540000, 2, ("شیشه‌ای",), ""),
            ("پک هدیه سه‌تایی", 1450000, 3, ("کادویی",), ""),
            ("فیلتر کاغذی سایز ۲", 120000, 0, (), "۱۰۰ عددی"),
        ],
        "policy": {"shippingCost": 45000, "shippingMethod": "پست", "returnDays": 0, "cardToCard": "۶۲۱۹-۸۶۱۰-XXXX-XXXX به نام قهوه خانه رست"},
        "out": "آسیاب دستی قهوه",
        "chit": ("بوی تازه داره؟", "دست شما درد نکنه"),
    },
    {
        "name": "لوازم خانه بهار",
        "slug": "bahar-home",
        "domain": "لوازم",
        "items": [
            ("سرو قابلمه ۹ پارچه", 6800000, 2, ("گرانیت",), ""),
            ("ست سطل و جاسوئیچی", 740000, 5, ("طوسی",), ""),
            ("پارچ شیشه‌ای دو لیتری", 390000, 7, ("شفاف",), ""),
            ("دستگاه آب‌میوه گیری", 4300000, 0, ("سفید",), ""),
            ("جاادویه‌ای چوبی", 560000, 9, ("چوب",), ""),
            ("پله جمع‌شونده", 1250000, 3, ("آلومینیومی",), ""),
        ],
        "policy": {"shippingCost": 90000, "shippingMethod": "باربری", "returnDays": 7, "cardToCard": ""},
        "out": "اتو بخار مخفی",
        "chit": ("فروشگاه حضوری دارید؟", "ممنون از جوابتون"),
    },
    {
        "name": "آرایشی نیلا",
        "slug": "nila-beauty",
        "domain": "زیبایی",
        "items": [
            ("سرم ویتامین سی", 980000, 4, (), "۳۰ میلی"),
            ("کرم ضدآفتاب SPF50", 620000, 8, (), ""),
            ("شامپو تخصصی ضدریزش", 450000, 6, (), "۴۰۰ میلی"),
            ("پالت سایه ۱۲ رنگ", 1100000, 2, (), ""),
            ("رژ لب مات", 380000, 0, ("قرمز", "زرشکی"), ""),
            ("ماسک ورقه آبرسان", 90000, 12, (), ""),
        ],
        "policy": {"shippingCost": 40000, "shippingMethod": "پست پیشتاز", "returnDays": 0, "cardToCard": "۵۸۹۴-۶۳۱۱-XXXX-XXXX به نام نیلا"},
        "out": "برس حرارتی مو",
        "chit": ("اصالت کالا چطور تضمین میشه؟", "مرسی"),
    },
)

_POLICY_DEFAULTS = {
    "shippingMethod": "پست پیشتاز",
    "shippingCost": 55000,
    "shippingDays": "۲ تا ۴ روز کاری",
    "shippingCities": "همهٔ شهرها",
    "freeShippingFrom": 2000000,
    "returnDays": 7,
    "returnNote": "اگر استفاده نشده باشد",
    "returnPayer": "مشتری",
    "hours": "۱۰ تا ۱۹",
    "sizeExchange": "تا ۷ روز",
    "invoice": "بله",
    "cod": "نداریم",
}


def _turns(persona: dict) -> list[tuple[str, str, dict]]:
    """(text, intent, expectation) for one persona."""
    items = persona["items"]
    live = [item for item in items if item[2] > 0]
    turns: list[tuple[str, str, dict]] = []
    for item in live[:6]:
        turns.append((f"{item[0]} موجود است؟", "stock", {"stock": item[2]}))
    for item in live[:6]:
        turns.append((f"قیمت {item[0]} چقدره؟", "price", {"price": item[1]}))
    for item in items[:4]:
        turns.append((f"{item[0]} چه رنگ‌هایی داره؟", "color", {"title": item[0]}))
    for item in live[:6]:
        turns.append((f"می‌خوام {item[0]} رو بخرم، لینک بده", "buy", {"title": item[0], "price": item[1]}))
    for index in range(0, min(4, len(live) - 1), 2):
        first, second = live[index], live[index + 1]
        turns.append(
            (f"{first[0]} و {second[0]} موجوده؟", "multi", {"stocks": (first[2], second[2])})
        )
    turns.append(("هزینه ارسال چقدره؟", "ship", {"cost": persona["policy"]["shippingCost"]}))
    turns.append(("مرجوعی دارید؟", "return", {"days": persona["policy"]["returnDays"]}))
    turns.append((f"{persona['out']} دارید؟", "out", {}))
    for text in persona["chit"]:
        turns.append((text, "chit", {}))
    return turns


_ROUTER_TURNS: tuple[tuple[str, str], ...] = (
    ("قیمت این کالا چقدره؟", "stock"),
    ("موجودش هست؟", "stock"),
    ("یک عدد از این هم هست؟", "stock"),
    ("می‌خوام بخرم لینک بده", "payment_link"),
    ("همین الان پرداخت کنم چطوری؟", "payment_link"),
    ("لینک پرداخت بفرست", "payment_link"),
    ("مرسی از پیگیریت", ""),
    ("خواهش می‌کنم", ""),
)


def _fold(text: str) -> str:
    return str(text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


_PII_MARKS = ("[تلفن]", "[کارت]", "[شبا]", "[کد]", "[نشانی]")


def _check(intent: str, reply: str, want: dict, shop_url: str) -> tuple[bool, str]:
    text = str(reply or "").strip()
    if not text:
        return False, "empty"
    from app.services.inbox_agent_service import HANDOFF_LINE

    handoff = text == HANDOFF_LINE
    from app.services.pii_mask import mask_pii

    if any(mark in mask_pii(text) for mark in _PII_MARKS):
        return False, "pii"
    if re.search(r"https?://[^\s]+", text.replace(shop_url, "")) and intent != "buy":
        return False, "foreign-url"
    folded = _fold(text)
    if intent == "stock":
        if handoff or "موجود" not in text:
            return False, "stock"
        if str(want["stock"]) not in folded:
            return False, "amount"
        return True, "ok"
    if intent == "price":
        if handoff:
            return False, "handoff"
        if str(want["price"]) not in folded:
            return False, "amount"
        return True, "ok"
    if intent == "buy":
        if handoff:
            return False, "handoff"
        if shop_url not in text:
            return False, "link"
        if "کارت" not in text:
            return False, "receipt"
        if "فروشنده" not in text:
            return False, "self-confirm"
        if str(want["price"]) not in folded:
            return False, "amount"
        return True, "ok"
    if intent == "multi":
        if shop_url in text:
            return False, "unexpected-link"
        if handoff:
            return False, "handoff"
        if any(str(stock) not in folded for stock in want["stocks"]):
            return False, "amount"
        return True, "ok"
    if intent == "ship":
        if handoff:
            return False, "handoff"
        if str(want["cost"]) not in folded:
            return False, "amount"
        return True, "ok"
    if intent == "return":
        if handoff:
            return True, "ok-empty-policy"
        return True, "ok"
    if intent == "color":
        if handoff:
            return False, "handoff"
        if want["title"].split()[0] not in text:
            return False, "product"
        return True, "ok"
    if intent == "out":
        if handoff:
            return True, "ok-handoff"
        if re.search(r"\d{4,}", folded):
            return False, "invented-amount"
        return True, "ok"
    if intent == "chit":
        if handoff:
            return True, "ok-handoff"
        if re.search(r"\d{4,}", folded):
            return False, "invented-amount"
        return True, "ok"
    return False, "unknown-intent"


def _router_example(question: str, tool: str, persona: dict):
    from app.services.training_log import log_example

    output = (
        {"text": json.dumps({"tool": tool}, ensure_ascii=False), "tool": tool}
        if tool
        else {"text": "جواب کوتاه خودم می‌دهم.", "tool": ""}
    )
    return log_example(
        task="router",
        messages=[{"role": "user", "content": question}],
        output=output,
        labels={"accept": True, "autoCheck": "rule"},
        teacher="sozan/synthetic-rule",
        source="synthetic",
        surface="router",
    )


def run(count_target: int = 200, out: Path | None = None, *, router_only: bool = False) -> dict:
    os.environ.setdefault("SOZAN_EDGE_DRY", "1")
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key == "open_router_api_token" and not os.environ.get(key):
                os.environ[key] = val.strip().strip('"').strip("'")
    if not os.environ.get("open_router_api_token"):
        raise SystemExit("openrouter key missing")

    state = Path(tempfile.mkdtemp(prefix="sozan-synthetic-"))
    from unittest.mock import patch

    from app.config import settings
    from app.services import inbox_agent_service, storefront_service
    from app.state_store import tenant_scope, write_json
    from app.services import observe_client
    from app.services.training_log import log_label

    # One-shot asyncio.run per turn kills emit_later's background task, so train
    # events are captured here and really sent by one live loop at the end.
    inbox: list[dict] = []
    drained: list[dict] = []
    routed: list[dict] = []
    results: list[dict] = []

    def capture(**kwargs):
        drained.append(dict(kwargs))
        payload = kwargs.get("payload")
        if kwargs.get("kind") == "train" and kwargs.get("title") == "train-example" and isinstance(payload, dict):
            inbox.append(dict(payload))

    async def _drain() -> int:
        sent = 0
        for kwargs in drained:
            try:
                await observe_client.emit(**kwargs)
                sent += 1
            except Exception:
                continue
        await observe_client.flush_outbox()
        return sent

    persona_turns = [] if router_only else [(persona, turn) for persona in PERSONAS for turn in _turns(persona)]
    router_turns = [(persona, turn) for persona in PERSONAS for turn in _ROUTER_TURNS]
    plan_inbox = max(1, round(count_target * len(persona_turns) / (len(persona_turns) + len(router_turns)))) if persona_turns else 0
    plan_router = max(0, count_target - plan_inbox)
    selected_inbox = [persona_turns[i * len(persona_turns) // plan_inbox] for i in range(plan_inbox)]
    selected_router = [router_turns[i * len(router_turns) // plan_router] for i in range(plan_router)] if plan_router else []

    started = time.time()
    with patch.object(settings, "state_dir", str(state)), tenant_scope(_PHONE), patch.object(
        inbox_agent_service, "emit_later", capture
    ), patch("app.services.training_log.emit_later", capture):
        for persona in PERSONAS:
            write_json(
                "shop.json",
                {"brand": persona["name"], "slug": persona["slug"], "status": "live", "url": f"https://{persona['slug']}.example"},
            )
            for index, (title, price, stock, colors, size) in enumerate(persona["items"], 1):
                storefront_service.add_product(
                    title=title,
                    price=price,
                    stock=stock,
                    sku=f"{persona['slug'][:4]}{index:02d}",
                    colors=[color for color in colors if color],
                    sizes=size,
                )
            write_json("sales-policy.json", {**_POLICY_DEFAULTS, **persona["policy"]})
            shop_url = f"https://{persona['slug']}.example"
            for text, intent, want in [turn for owner, turn in selected_inbox if owner is persona]:
                inbox.clear()
                reply = asyncio.run(
                    inbox_agent_service.answer(text, thread={"sender": "مشتری آزمون"}, source="synthetic")
                )
                example = inbox[-1] if inbox else {}
                ok, note = _check(intent, reply, want, shop_url)
                eid = str(example.get("id") or "")
                if eid:
                    kwargs = {
                        "kind": "train",
                        "title": "train-label",
                        "surface": "train",
                        "payload": {
                            "exampleId": eid,
                            "labels": {"accept": ok, "autoCheck": intent if ok else f"{intent}:{note}"},
                            "ts": time.time(),
                            "tenant": str(example.get("tenant") or ""),
                        },
                    }
                    drained.append(kwargs)
                results.append(
                    {
                        "id": eid,
                        "persona": persona["domain"],
                        "intent": intent,
                        "ok": ok,
                        "note": note,
                        "path": str(example.get("output", {}).get("path") or ""),
                        "ms": int(example.get("latencyMs") or 0),
                        "teacher": str(example.get("teacher") or ""),
                    }
                )
            for text, tool in [turn for owner, turn in selected_router if owner is persona]:
                eid = _router_example(text, tool, persona)
                routed.append({"id": eid, "persona": persona["domain"], "intent": f"router:{tool or 'none'}", "ok": bool(eid)})

    sent = asyncio.run(_drain())

    passed = sum(1 for row in results if row["ok"])
    stats = {
        "generated": len(results) + len(routed),
        "inbox": len(results),
        "inboxAccepted": passed,
        "inboxRejected": len(results) - passed,
        "router": len(routed),
        "byIntent": {},
        "rejections": {},
        "teachers": sorted({row["teacher"] for row in results if row["teacher"]}),
        "stateDir": str(state),
        "seconds": round(time.time() - started),
    }
    for row in results:
        stats["byIntent"][row["intent"]] = stats["byIntent"].get(row["intent"], 0) + 1
        if not row["ok"]:
            key = f"{row['intent']}:{row['note']}"
            stats["rejections"][key] = stats["rejections"].get(key, 0) + 1
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "synthetic-report.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (Path(out) / "synthetic-results.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results + routed), encoding="utf-8"
        )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--out", default=str(Path.home() / "local-ai/sozan-train/synthetic"))
    parser.add_argument("--router-only", action="store_true")
    args = parser.parse_args()
    stats = run(args.count, Path(args.out), router_only=args.router_only)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
