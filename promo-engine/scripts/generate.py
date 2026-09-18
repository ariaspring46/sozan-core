#!/usr/bin/env python3
"""CLI: تولید یک کمپین تبلیغاتی برند سوزان.

نمونه:
    python scripts/generate.py
    python scripts/generate.py --pillar shop
    python scripts/generate.py --pillar gateway --mood late-night
    python scripts/generate.py --status
    python scripts/generate.py --list
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.generate import generate, list_campaigns, status  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="موتور تبلیغاتی سوزان")
    parser.add_argument(
        "--pillar",
        choices=["shop", "gateway", "panel"],
        help="ستون محتوا (در صورت حذف: round-robin خودکار)",
    )
    parser.add_argument(
        "--mood",
        choices=["setup", "wit", "panel", "gateway", "late-night", "local", "privacy", "shop"],
        help="حال/قالب کپشن (اختیاری)",
    )
    parser.add_argument("--status", action="store_true", help="نمایش وضعیت اتوماسیون")
    parser.add_argument("--list", action="store_true", help="لیست کمپین‌های تولیدشده")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return

    if args.list:
        rows = list_campaigns()
        if not rows:
            print("هنوز کمپینی ساخته نشده.")
            return
        for row in rows:
            print(f"{row['slug']}\t{row['pillar']}\t{row['title']}")
        return

    result = asyncio.run(generate(pillar=args.pillar, mood=args.mood))
    if not result.get("ok"):
        print(f"خطا: {result.get('error')}", file=sys.stderr)
        if result.get("pillar"):
            print(f"ستون: {result['pillar']}", file=sys.stderr)
        sys.exit(1)

    print(f"کمپین ساخته شد: {result['slug']}")
    print(f"ستون: {result['pillar']}  حال: {result.get('mood', '')}")
    print(f"تیتر: {result['title']}")
    print(f"خروجی: {result['out_dir']}")
    print(f"زیپ: {result['zip']}")
    if result.get("errors"):
        for key, err in result["errors"].items():
            print(f"هشدار ({key}): {err}", file=sys.stderr)


if __name__ == "__main__":
    main()