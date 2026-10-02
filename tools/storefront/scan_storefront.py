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
import subprocess
import sys
from pathlib import Path

# Phrases no seller types verbatim; safe to ban in served HTML outright.
GENERIC_SEED_IMAGES = (
    "mobile-gen-",
    "laptop-gen-",
    "product-gen-",
    "seed-product",
)

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
IMG_SRC = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
PRICE_BLOCK = re.compile(r'data-price="[^"]*"[^>]*>(.*?)</', re.I | re.S)
DISCOUNT_BADGE = re.compile(r'data-discount-badge="[^"]*"[^>]*>(.*?)</', re.I | re.S)
ZERO_PRICE = re.compile(r"[۰0]\\s*تومان")
TRUST_SECTION = re.compile(r'data-sozan-trust="1"')

TRUST_TITLES = ("ارسال", "مرجوعی", "پرداخت در محل", "فاکتور")


def fetch(url: str) -> str:
    # curl carries the shell socks proxy env; python urllib cannot.
    out = subprocess.run(
        ["curl", "-sL", "-m", "20", url], capture_output=True, text=True, timeout=25
    )
    if not out.stdout:
        raise RuntimeError(f"empty response from {url}")
    return out.stdout


def policy_texts(policy: dict) -> list[str]:
    out: list[str] = []
    for value in policy.values():
        if isinstance(value, str) and value:
            out.append(value)
        elif isinstance(value, int):
            out.append(str(value))
    return out


def fa_num(value: int) -> str:
    grouped = f"{value:,}"
    return grouped.replace("0", "۰").replace("1", "۱").replace("2", "۲").replace("3", "۳") \
        .replace("4", "۴").replace("5", "۵").replace("6", "۶").replace("7", "۷") \
        .replace("8", "۸").replace("9", "۹").replace(",", "٬")


def expected_trust_cards(policy: dict) -> list[tuple[str, str]]:
    """Python mirror of policyTrustItems() in lib/policy.ts."""
    s = policy.get("shippingMethod", "")
    d = policy.get("shippingDays", "")
    c = policy.get("shippingCities", "")
    cost = policy.get("shippingCost")
    free = policy.get("freeShippingFrom")
    cards: list[tuple[str, str]] = []
    ship: list[str] = [x for x in (s, d, c) if isinstance(x, str) and x]
    if isinstance(cost, int) and cost > 0:
        ship.append(f"هزینهٔ ارسال {fa_num(cost)} تومان")
    if isinstance(free, int) and free > 0:
        ship.append(f"ارسال رایگان از خرید {fa_num(free)} تومان")
    if ship:
        cards.append(("ارسال", "؛ ".join(ship)))
    rdays = policy.get("returnDays")
    ret: list[str] = []
    if isinstance(rdays, int) and rdays > 0:
        ret.append(f"تا {fa_num(rdays)} روز")
    for key in ("returnNote", "returnPayer"):
        if policy.get(key):
            ret.append(str(policy[key]))
    if ret:
        cards.append(("مرجوعی", "؛ ".join(ret)))
    if policy.get("cod"):
        cards.append(("پرداخت در محل", str(policy["cod"])))
    if policy.get("invoice"):
        cards.append(("فاکتور", str(policy["invoice"])))
    return cards


CARD_RE = re.compile(r'<div[^>]*class="[^"]*surface-card[^"]*"[^>]*>(.*?)</div>', re.S)
P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", text).strip()


def trust_cards_from_html(html: str) -> list[tuple[str, str]]:
    start = TRUST_SECTION.search(html)
    if not start:
        return []
    section = html[start.start() : start.start() + 8000]
    cards: list[tuple[str, str]] = []
    for card in CARD_RE.findall(section):
        paras = [strip_tags(p) for p in P_RE.findall(card)]
        paras = [p for p in paras if p]
        if len(paras) >= 2:
            cards.append((paras[0], paras[1]))
        if len(cards) == 4:
            break
    return cards


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

        for src in IMG_SRC.findall(html):
            if any(g in src for g in GENERIC_SEED_IMAGES):
                problems.append(f"{where}generic seed image on page: {src}")
                continue
            if src.startswith("/"):
                try:
                    head = subprocess.run(
                        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                         "-m", "10", url.rstrip("/") + src],
                        capture_output=True, text=True, timeout=15,
                    ).stdout.strip()
                    if head != "200":
                        problems.append(f"{where}image not loadable {src} (HTTP {head})")
                except Exception:  # noqa: BLE001
                    problems.append(f"{where}image probe failed {src}")
            elif not src.startswith("data:"):
                problems.append(f"{where}remote image src: {src[:60]}")

        for badge in DISCOUNT_BADGE.findall(html):
            text = badge.strip()
            if LATIN_DIGIT.search(text) or "٪" not in text:
                problems.append(f"{where}discount badge not Persian-digits+٪: {text[:20]!r}")

        trust = TRUST_SECTION.search(html)
        if trust:
            if policy is None:
                problems.append(f"{where}trust/features section shown but no --policy passed to scanner")
            elif not expected_trust_cards(policy):
                problems.append(f"{where}trust/features section shown but policy has no set fields")
            else:
                # بند ۲۳: every card (trust or "features") must be exactly a
                # policy-built card — no invented claims anywhere on the page.
                rendered = trust_cards_from_html(html)
                expected = expected_trust_cards(policy)
                if not rendered:
                    problems.append(f"{where}trust section exists but no cards parsed")
                for title, body in rendered:
                    if (title, body) not in expected:
                        problems.append(f"{where}non-policy card: «{title}: {body[:50]}»")
                for title, _body in expected:
                    if title not in [t for t, _ in rendered]:
                        problems.append(f"{where}policy card missing from page: «{title}»")
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
