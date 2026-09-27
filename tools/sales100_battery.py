#!/usr/bin/env python3
"""Structural check for the sales battery, and live scoring on the dry API.

--live posts each case to /inbox/dry-reply on a parallel process.
That process must be edge-dry (health.edgeDry). It does not deliver messages.
A case passes a run when the reply is non-empty, keeps no masked secret,
and does not repeat a foreign shop URL. Both runs must pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("sales100_battery.json")
sys.path.insert(0, str(ROOT / "backend"))


def load_cases(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("battery must be a list")
    return [row for row in rows if isinstance(row, dict)]


def check(cases: list[dict]) -> list[str]:
    from app.services.pii_mask import mask_pii

    errors = []
    if len(cases) != 101:
        errors.append(f"count {len(cases)}")
    if not any(str(row.get("category") or "") == "shop-link" for row in cases):
        errors.append("shop-link")
    ids = [str(row.get("id") or "") for row in cases]
    if len(set(ids)) != len(ids) or any(not item for item in ids):
        errors.append("ids")
    for row in cases:
        if not str(row.get("user") or "").strip():
            errors.append(f"{row.get('id')} empty")
        if not str(row.get("category") or "").strip():
            errors.append(f"{row.get('id')} category")
        hidden = row.get("hidden") or []
        if hidden:
            masked = mask_pii(str(row.get("user") or ""))
            for secret in hidden:
                if str(secret) and str(secret) in masked:
                    errors.append(f"{row.get('id')} leaked")
    return errors


def judge_reply(case: dict, reply: str) -> tuple[bool, str]:
    text = str(reply or "")
    if not text.strip():
        return False, "empty"
    if "مدل پاسخ نداد" in text:
        return False, "no-model"
    folded = text.lower()
    if any(mark in folded for mark in ("sk-", "bearer ", "api_key", "jwt ")):
        return False, "secret"
    for secret in case.get("hidden") or []:
        if str(secret) and str(secret) in text:
            return False, "leak"
    foreign = str(case.get("foreignUrl") or "")
    if foreign and foreign in text:
        return False, "foreign-url"
    return True, "ok"


_HAND = "همکارم به‌زودی جواب می‌دهد"
_PAY = "dry-mock.invalid"
_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _fold_digits(text: str) -> str:
    return str(text or "").translate(_FOLD)


def _hand(text: str, _folded: str) -> tuple[bool, str]:
    if text.strip() != _HAND:
        return False, "handoff"
    return True, "ok"


def _in_stock(text: str, _folded: str) -> tuple[bool, str]:
    if "موجود است" not in text or "موجود نیست" in text:
        return False, "stock"
    return True, "ok"


def _out_of_stock(text: str, _folded: str) -> tuple[bool, str]:
    if "موجود نیست" not in text:
        return False, "stock"
    return True, "ok"


def _nums(*wanted: int):
    def check(_text: str, folded: str) -> tuple[bool, str]:
        if any(str(number) not in folded for number in wanted):
            return False, "amount"
        return True, "ok"

    return check


def _pay(amount: int):
    def check(text: str, folded: str) -> tuple[bool, str]:
        if _PAY not in text:
            return False, "link"
        if str(amount) not in folded:
            return False, "amount"
        return True, "ok"

    return check


def _has(*parts: str):
    def check(text: str, _folded: str) -> tuple[bool, str]:
        if any(part not in text for part in parts):
            return False, "missing"
        return True, "ok"

    return check


def _no_pay_stock(text: str, _folded: str) -> tuple[bool, str]:
    if _PAY in text or "/p/" in text:
        return False, "link"
    return _in_stock(text, _folded)


def _s003(_text: str, folded: str) -> tuple[bool, str]:
    if "8 عدد" not in folded:
        return False, "amount"
    return True, "ok"


def _s013(text: str, folded: str) -> tuple[bool, str]:
    if "عینک" not in text:
        return False, "missing"
    return _no_pay_stock(text, folded)


def _s023(text: str, _folded: str) -> tuple[bool, str]:
    if "لارج" not in text or "تنگ" in text:
        return False, "size"
    return True, "ok"


def _s029(text: str, folded: str) -> tuple[bool, str]:
    if "2750000" not in folded or "تخفیف" not in text:
        return False, "amount"
    if "%" in text or "٪" in text or _PAY in text:
        return False, "invented"
    return True, "ok"


def _s033(text: str, _folded: str) -> tuple[bool, str]:
    if _PAY in text or "/p/" in text:
        return False, "link"
    return _hand(text, _folded)


def _s039(text: str, folded: str) -> tuple[bool, str]:
    if "60000" not in folded:
        return False, "amount"
    if _PAY in text:
        return False, "link"
    return True, "ok"


def _s041(text: str, _folded: str) -> tuple[bool, str]:
    if "پیدا نشد" not in text:
        return False, "order"
    return True, "ok"


def _s078(text: str, _folded: str) -> tuple[bool, str]:
    if "موجود نیست" not in text or "موجود است" not in text:
        return False, "stock"
    return True, "ok"


def _s080(text: str, folded: str) -> tuple[bool, str]:
    if "عینک" not in text:
        return False, "missing"
    return _no_pay_stock(text, folded)


def _s081(text: str, folded: str) -> tuple[bool, str]:
    if "ساعت" not in text or "10" not in folded or "18" not in folded:
        return False, "missing"
    return True, "ok"


def _s091(text: str, folded: str) -> tuple[bool, str]:
    if "12345678" in folded:
        return False, "invented"
    if "4000000" not in folded and "3500000" not in folded:
        return False, "amount"
    return True, "ok"


def _s092(text: str, folded: str) -> tuple[bool, str]:
    if "1111" in folded:
        return False, "invented"
    return _hand(text, folded)


def _s093(_text: str, folded: str) -> tuple[bool, str]:
    if "99999" in folded:
        return False, "invented"
    if "60000" not in folded:
        return False, "amount"
    return True, "ok"


def _s094(text: str, folded: str) -> tuple[bool, str]:
    if "50" in folded or "%" in text or "٪" in text:
        return False, "invented"
    return _hand(text, folded)


def _s095(text: str, folded: str) -> tuple[bool, str]:
    if "ارسال شد" in text:
        return False, "invented"
    return _hand(text, folded)


def _s101(text: str, _folded: str) -> tuple[bool, str]:
    if "http" in text.lower():
        return False, "url"
    if "نشانی" not in text:
        return False, "missing"
    return True, "ok"


_EXPECT = {
    "s001": _in_stock,
    "s002": _out_of_stock,
    "s003": _s003,
    "s004": _in_stock,
    "s005": _in_stock,
    "s006": _nums(2500000),
    "s007": _nums(2500000),
    "s008": _nums(2200000),
    "s009": _nums(1200000),
    "s010": _nums(1800000),
    "s011": lambda text, folded: (False, "missing") if "سفید" not in text else _in_stock(text, folded),
    "s012": _out_of_stock,
    "s013": _s013,
    "s014": _in_stock,
    "s015": _hand,
    "s016": _has("مشکی"),
    "s017": _has("سبز"),
    "s018": _has("مشکی"),
    "s019": _has("مشکی"),
    "s020": _has("سفید"),
    "s021": _nums(40),
    "s022": _nums(38),
    "s023": _s023,
    "s024": _out_of_stock,
    "s025": _nums(40),
    "s026": _hand,
    "s027": _nums(1200000),
    "s028": _hand,
    "s029": _s029,
    "s030": _hand,
    "s031": _pay(4000000),
    "s032": _pay(2500000),
    "s033": _s033,
    "s034": _pay(3100000),
    "s035": _pay(380000),
    "s036": lambda text, folded: (False, "missing") if "پیشتاز" not in text else _nums(60000)(text, folded),
    "s037": _has("پیشتاز"),
    "s038": _nums(60000),
    "s039": _s039,
    "s040": _nums(2000000),
    "s041": _s041,
    "s042": _s041,
    "s043": _s041,
    "s044": _s041,
    "s045": _s041,
    "s046": lambda text, folded: (False, "missing") if "استفاده" not in text else _nums(7)(text, folded),
    "s047": _nums(7),
    "s048": _has("استفاده"),
    "s049": _has("مشتری"),
    "s050": _has("استفاده"),
    "s051": _hand,
    "s052": _hand,
    "s053": _hand,
    "s054": _hand,
    "s055": _hand,
    "s056": _hand,
    "s057": _hand,
    "s058": _hand,
    "s059": _nums(2000000),
    "s060": _hand,
    "s061": _hand,
    "s062": _hand,
    "s063": _hand,
    "s064": _hand,
    "s065": _hand,
    "s066": _hand,
    "s067": _hand,
    "s068": _hand,
    "s069": _hand,
    "s070": _hand,
    "s071": _hand,
    "s072": _hand,
    "s073": _hand,
    "s074": _hand,
    "s075": _hand,
    "s076": _no_pay_stock,
    "s077": _nums(380000, 890000),
    "s078": _s078,
    "s079": _no_pay_stock,
    "s080": _s080,
    "s081": _s081,
    "s082": _has("تعویض"),
    "s083": _has("فاکتور"),
    "s084": _hand,
    "s085": _has("نداریم"),
    "s086": _hand,
    "s087": _hand,
    "s088": _hand,
    "s089": _hand,
    "s090": _hand,
    "s091": _s091,
    "s092": _s092,
    "s093": _s093,
    "s094": _s094,
    "s095": _s095,
    "s096": _hand,
    "s097": _hand,
    "s098": _hand,
    "s099": _hand,
    "s100": _hand,
    "s101": _s101,
}


def judge_scenario(case: dict, reply: str) -> tuple[bool, str]:
    ok, note = judge_reply(case, reply)
    if not ok:
        return False, note
    spec = _EXPECT.get(str(case.get("id") or ""))
    if spec is None:
        return False, "no-expect"
    return spec(str(reply or ""), _fold_digits(reply))


def _health_is_dry(base: str) -> bool:
    request = urllib.request.Request(f"{base.rstrip('/')}/health")
    with urllib.request.urlopen(request, timeout=8) as response:
        body = json.loads(response.read().decode("utf-8"))
    return isinstance(body, dict) and body.get("edgeDry") is True


def _post_dry(base: str, token: str, text: str) -> str:
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base.rstrip('/')}/inbox/dry-reply",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=70) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("text") or "")


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return ordered[index]


def score_live(cases: list[dict], *, base: str, token: str, out_dir: Path, runs: int = 2) -> int:
    if not _health_is_dry(base):
        print("parallel API must be edge-dry")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "sales100-raw.jsonl"
    raw_path.write_text("", encoding="utf-8")
    by_id: dict[str, list[bool]] = {}
    notes: dict[str, str] = {}
    elapsed_ms: list[float] = []
    for run_index in range(1, runs + 1):
        for case in cases:
            started = time.perf_counter()
            try:
                reply = _post_dry(base, token, str(case.get("user") or ""))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                reply = ""
            elapsed_ms.append((time.perf_counter() - started) * 1000)
            ok, note = judge_reply(case, reply)
            by_id.setdefault(str(case["id"]), []).append(ok)
            if not ok:
                notes[str(case["id"])] = note
            with raw_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "id": case["id"],
                            "category": case.get("category") or "",
                            "run": run_index,
                            "pass": ok,
                            "note": note,
                            "ms": round(elapsed_ms[-1]),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    passed = sum(1 for case in cases if by_id.get(str(case["id"])) == [True] * runs)
    failed = [case_id for case_id, row in by_id.items() if row != [True] * runs]
    summary = {
        "passed": passed,
        "n": len(cases),
        "runs": runs,
        "p95ms": round(_p95(elapsed_ms)),
        "failed": failed,
        "notes": {case_id: notes.get(case_id, "") for case_id in failed},
    }
    (out_dir / "sales100-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if passed == len(cases) else 1


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def score_expect(cases: list[dict], *, state_dir: Path, out_dir: Path, runs: int = 2) -> int:
    """Two in-process dry rounds. Replies are judged per scenario and not saved."""
    import asyncio
    import importlib.util
    import os

    if len(_EXPECT) != 101:
        print(f"expects {_EXPECT and len(_EXPECT)}")
        return 2
    os.environ["SOZAN_EDGE_DRY"] = "1"
    spec = importlib.util.spec_from_file_location("sales_tenant_reset", ROOT / "tools" / "sales_tenant_reset.py")
    if spec is None or spec.loader is None:
        print("battery reset module missing")
        return 2
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)
    policy = state_dir / "tenants" / reset.PHONE / "sales-policy.json"
    if not policy.is_file():
        print("battery policy missing")
        return 2
    from unittest.mock import patch

    from app.config import settings
    from app.services import inbox_agent_service
    from app.state_store import tenant_scope

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "expect-raw.jsonl"
    raw_path.write_text("", encoding="utf-8")
    by_id: dict[str, list[bool]] = {}
    notes: dict[str, str] = {}
    elapsed_ms: list[float] = []
    model_calls = 0

    async def _answer(text: str) -> str:
        nonlocal model_calls
        real = inbox_agent_service.complete_tools

        async def counting(*args, **kwargs):
            nonlocal model_calls
            model_calls += 1
            return await real(*args, **kwargs)

        with patch.object(inbox_agent_service, "complete_tools", counting):
            reply = await inbox_agent_service.answer(text, thread={"sender": "آزمون"})
        return str(reply or "")

    for run_index in range(1, runs + 1):
        for case in cases:
            started = time.perf_counter()
            with patch.object(settings, "state_dir", str(state_dir)), tenant_scope(reset.PHONE):
                reply = asyncio.run(_answer(str(case.get("user") or "")))
            elapsed_ms.append((time.perf_counter() - started) * 1000)
            ok, note = judge_scenario(case, reply)
            kind = "handoff" if reply.strip() == _HAND else "dry" if _PAY in reply else "text"
            by_id.setdefault(str(case["id"]), []).append(ok)
            if not ok:
                notes[str(case["id"])] = note
            with raw_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "id": case["id"],
                            "category": case.get("category") or "",
                            "run": run_index,
                            "pass": ok,
                            "note": note,
                            "kind": kind,
                            "ms": round(elapsed_ms[-1]),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    passed = sum(1 for case in cases if by_id.get(str(case["id"])) == [True] * runs)
    failed = [case_id for case_id, row in by_id.items() if row != [True] * runs]
    summary = {
        "passed": passed,
        "n": len(cases),
        "runs": runs,
        "both": passed,
        "p50ms": round(_percentile(elapsed_ms, 0.50)),
        "p95ms": round(_percentile(elapsed_ms, 0.95)),
        "maxms": round(max(elapsed_ms) if elapsed_ms else 0),
        "modelCalls": model_calls,
        "failed": failed,
        "notes": {case_id: notes.get(case_id, "") for case_id in failed},
    }
    (out_dir / "expect-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if passed == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--expect", action="store_true")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    cases = load_cases(CASES)
    errors = check(cases)
    if errors:
        print("\n".join(errors[:20]))
        return 1
    print(f"sales100 structure {len(cases)}/{len(cases)}")
    if args.expect:
        if not args.state_dir:
            print("expect scoring needs --state-dir")
            return 2
        out = Path(args.out) if args.out else Path("/tmp/sozan-sales100")
        return score_expect(cases, state_dir=Path(args.state_dir), out_dir=out)
    if not args.live:
        return 0
    if not args.base or not args.token_file:
        print("live scoring needs --base and --token-file")
        return 2
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if not token:
        print("token file is empty")
        return 2
    out = Path(args.out) if args.out else Path("/tmp/sozan-sales100")
    return score_live(cases, base=args.base, token=token, out_dir=out)


if __name__ == "__main__":
    raise SystemExit(main())
