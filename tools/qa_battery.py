#!/usr/bin/env python3
"""Offline and live sentences built from real catalog titles.

Offline checks which router gate opens. Live mode posts to a test account,
cancels every card, and never confirms a publish.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def sentences(products: list[str]) -> list[dict]:
    product = next((item.strip() for item in products if len(item.strip()) >= 2), "کالا")
    return [
        {"intent": "post", "text": f"برای {product} یک پست اینستاگرام بساز", "tool": "studio_chat"},
        {"intent": "stock", "text": f"موجودی {product}", "kind": "direct", "contains": product},
        {"intent": "add", "text": f"{product} را با قیمت ۱۰۰۰۰۰ تومان اضافه کن", "tool": "add_product"},
        {"intent": "discount", "text": f"برای تخفیف {product} پست بساز", "tool": "studio_chat", "forbid": "پرونده"},
        {"intent": "story", "text": f"یک استوری از {product} بساز", "tool": "studio_chat"},
        {"intent": "edit", "text": "رنگ فروشگاه را آبی کن", "tool": "edit_shop"},
    ]


def catalog_titles(root: Path) -> list[str]:
    titles: list[str] = []
    tenants = root / "tenants"
    if not tenants.is_dir():
        return titles
    for shop in sorted(tenants.iterdir()):
        path = shop / "products.json"
        if not path.is_file():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("title") or "").strip():
                titles.append(str(row.get("title")).strip())
    return titles


def grade(choice: dict, row: dict) -> bool:
    forbid = str(row.get("forbid") or "")
    text = str(choice.get("text") or "")
    if forbid and forbid in text:
        return False
    if row.get("kind") == "direct":
        if choice.get("kind") != "direct":
            return False
        needle = str(row.get("contains") or "")
        return not needle or needle in text
    return choice.get("kind") == "tool" and choice.get("tool") == row.get("tool")


def offline(products: list[str]) -> int:
    from app.services.router_service import decide

    bad = 0
    for row in sentences(products):
        choice = decide(row["text"])
        ok = grade(choice, row)
        print(("ok" if ok else "MISS"), row["intent"], choice.get("kind"), choice.get("tool") or choice.get("text", "")[:80])
        if not ok:
            bad += 1
    return bad


def live(base: str, token: str, products: list[str]) -> int:
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    bad = 0
    with httpx.Client(timeout=40, trust_env=False) as client:
        opened = client.post(f"{base}/chat/threads", headers=headers)
        thread_id = ""
        if opened.status_code == 200:
            thread_id = str((opened.json() or {}).get("threadId") or "")
        for row in sentences(products):
            body = {"text": row["text"], "threadId": thread_id}
            res = client.post(f"{base}/chat", headers=headers, json=body)
            data = res.json() if res.status_code == 200 else {}
            pending = data.get("pendingConfirm") or {}
            if pending.get("id"):
                client.post(
                    f"{base}/chat",
                    headers=headers,
                    json={"text": "", "threadId": thread_id, "cancelId": pending["id"]},
                )
                if pending.get("tool") == "publish_post":
                    bad += 1
            last = ((data.get("messages") or [{}])[-1]).get("text") or ""
            if row.get("forbid") and row["forbid"] in str(last):
                bad += 1
            print(row["intent"], res.status_code, str(last)[:80])
    return bad


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--state", default="")
    args = parser.parse_args()
    root = Path(args.state) if args.state else Path(os.environ.get("SOZAN_STATE") or "/home/ubuntu/sozan-core/backend/data")
    products = catalog_titles(root) or ["هودی"]
    if args.live:
        token_path = Path(os.environ.get("SOZAN_BATTERY_TOKEN") or "/home/ubuntu/sozan-core/backend/data/battery-token")
        token = token_path.read_text(encoding="utf-8").strip() if token_path.is_file() else ""
        if not token:
            print("no battery token; live skipped")
            return 0
        base = os.environ.get("SOZAN_BATTERY_BASE") or "http://127.0.0.1:8012"
        return 1 if live(base, token, products) else 0
    return 1 if offline(products) else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    raise SystemExit(main())
