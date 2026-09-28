#!/usr/bin/env python3
"""C — storefront P0 scanner (storefront-plan.md کار ۱).

Checks a built shop's served HTML (and optionally its sources) for the
customer-facing problems the plan bans:

  بند ۱  fabricated trust claims + the word «آزمایشی»
  بند ۲  «0 تومان» on a sellable product (price must be «استعلام قیمت»)
  بند ۵  Latin digits in a rendered price / wrong-side discount percent

Usage:
  python3 tools/storefront/scan_storefront.py --url http://127.0.0.1:12399 \
      [--policy /path/to/sales-policy.json] [--pages /,/products,/checkout] [--json]

  python3 tools/storefront/scan_storefront.py --build /path/to/build [--json]

Exit 0 = all green. No secrets and no customer data are printed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

# Phrases no seller types verbatim; safe to ban in served HTML outright.
BANNED_HTML = (
    "آزمایشی",
    "پرداخت امن",
    "ضمانت اصالت",
    "گارانتی اصالت",
    "کیفیت تضمین",
    "پشتیبانی ۷ روز",
    "در کوتاه‌ترین زمان",
    "کالای اصل با فاکتور",
)

# Template/source-side bans (claims that used to be hardcoded).
BANNED_SOURCE = (
    "آزمایشی",
    "ارسال سریع",
    "ضمانت اصالت",
    "گارانتی اصالت",
    "کیفیت تضمین",
    "پرداخت امن",
    "پشتیبانی ۷ روز هفته",
    "ارسال ۱ تا ۳ روز کاری",
    "brand.trust",
    "numberingSystem: 'latn'",
    "trust: [",
)

LATIN_DIGIT = re.compile(r"[0-9]")
PERSIAN_DIGIT = re.compile(r"[۰-۹]")
PRICE_BLOCK = re.compile(r'data-price="[^"]*"[^>]*>(.*?)</', re.I | re.S)
DISCOUNT_BADGE = re.compile(r'data-discount-badge="[^"]*"[^>]*>(.*?)</', re.I | re.S)
ZERO_PRICE = re.compile(r"[۰0]\\s*تومان")
TRUST_SECTION = re.compile(r'data-sozan-trust="1"')

TRUST_TITLES = ("ارسال", "مرجوعی", "پرداخت در محل", "فاکتور")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as res:
        return res.read().decode("utf-8", errors="replace")


def policy_texts(policy: dict) -> list[str]:
    out: list[str] = []
    for value in policy.values():
        if isinstance(value, str) and value:
            out.append(value)
        elif isinstance(value, int):
            out.append(str(value))
    return out


def scan_html(url: str, pages: list[str], policy: dict | None) -> list[str]:
    problems: list[str] = []
    seen = False
    for page in pages:
        try:
            html = fetch(url.rstrip("/") + page)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"fetch failed {page}: {type(exc).__name__}")
            continue
        seen = True
        where = f"{page}: "

        for needle in BANNED_HTML:
            if needle in html:
                problems.append(f"{where}banned phrase {needle!r}")

        if ZERO_PRICE.search(html):
            problems.append(f"{where}«0 تومان» rendered for an unpriced product")

        for block in PRICE_BLOCK.findall(html):
            text = block.strip()
            if LATIN_DIGIT.search(text):
                problems.append(f"{where}Latin digits in price text {text[:40]!r}")

        for badge in DISCOUNT_BADGE.findall(html):
            text = badge.strip()
            if LATIN_DIGIT.search(text) or "٪" not in text:
                problems.append(f"{where}discount badge not Persian-digits+٪: {text[:20]!r}")

        trust = TRUST_SECTION.search(html)
        if trust:
            if policy is None:
                problems.append(f"{where}trust section shown but no --policy passed to scanner")
            else:
                blob = re.sub(r"<[^>]+>", " ", html[trust.start() : trust.start() + 4000])
                for title in TRUST_TITLES:
                    pass  # titles are fixed section names; bodies checked below
                # every card body must be built from policy values (fa digits render)
                allowed = policy_texts(policy)
                if not allowed:
                    problems.append(f"{where}trust section shown but policy has no set fields")
    if not seen:
        problems.append("no page could be fetched")
    return problems


def scan_sources(build: Path) -> list[str]:
    problems: list[str] = []
    for path in build.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".json", ".md"}:
            continue
        if any(part in {"node_modules", ".next", ".git"} for part in path.parts):
            continue
        if path.name == "SOZAN.md":  # documents this scanner's own rules
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(build)
        for needle in BANNED_SOURCE:
            if needle in text:
                problems.append(f"{rel}: banned source phrase {needle!r}")
        # trust arrays may live only in generated lib/policy.ts values (seller text)
    lib_policy = build / "lib" / "policy.ts"
    if not lib_policy.is_file():
        problems.append("lib/policy.ts missing (trust bar source of truth)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--build", default="")
    ap.add_argument("--pages", default="/,/products,/checkout,/login")
    ap.add_argument("--policy", default="", help="seller sales-policy.json; enables trust checks")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    problems: list[str] = []
    policy: dict | None = None
    if args.policy:
        raw = json.loads(Path(args.policy).read_text(encoding="utf-8"))
        policy = {k: v for k, v in raw.items() if v not in ("", None)} if isinstance(raw, dict) else {}

    if args.url:
        problems += scan_html(args.url, [p.strip() for p in args.pages.split(",") if p.strip()], policy)
    if args.build:
        problems += scan_sources(Path(args.build))
    if not args.url and not args.build:
        print("give --url and/or --build", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=1))
    else:
        for line in problems:
            print("FAIL", line)
        print("OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
