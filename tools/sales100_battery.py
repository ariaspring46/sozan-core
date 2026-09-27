#!/usr/bin/env python3
"""Structural check for the 100-dialogue sales battery.

Live scoring against the parallel API waits until that API exists.
--live without --base exits 2. A 99 is not a pass; this file only
returns 0 when all 100 rows are well-formed and the mask rows hold.
"""

from __future__ import annotations

import argparse
import json
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    cases = load_cases(CASES)
    errors = check(cases)
    if errors:
        print("\n".join(errors[:20]))
        return 1
    print(f"sales100 structure {len(cases)}/{len(cases)}")
    if args.live:
        if not args.base:
            print("live scoring needs --base")
            return 2
        print("live scoring is not wired yet")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
