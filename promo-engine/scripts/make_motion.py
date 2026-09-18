#!/usr/bin/env python3
"""CLI: ساخت لوگو موشن «آذر از آینده آمده» (حدود ۵ ثانیه).

نمونه:
    python scripts/make_motion.py                          # با brand/azar-seed128.png
    python scripts/make_motion.py --character brand/azar-seed42.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.motion import AzarMotionService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="لوگو موشن آذر")
    parser.add_argument(
        "--character",
        default="brand/azar-seed128.png",
        help="مسیر تصویر آذر (پیش‌فرض: brand/azar-seed128.png)",
    )
    args = parser.parse_args()

    char_path = Path(args.character)
    if not char_path.is_file():
        print(f"تصویر پیدا نشد: {char_path}", file=sys.stderr)
        sys.exit(1)

    service = AzarMotionService(character=char_path.resolve())
    produced = service.render()
    for key, path in produced.items():
        print(f"{key}\t{path}")


if __name__ == "__main__":
    main()