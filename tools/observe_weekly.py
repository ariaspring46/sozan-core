#!/usr/bin/env python3
"""Print this week's fallback and wrong-tool counts. Frequent lines become registry rows."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.fallback_tally import top  # noqa: E402


def main() -> int:
    for kind in ("fallback", "refusal", "wrong-tool"):
        rows = top(kind)
        print(kind)
        if not rows:
            print("  —")
            continue
        for text, count in rows:
            print(f"  {count}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
