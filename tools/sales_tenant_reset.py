#!/usr/bin/env python3
"""Reset the dedicated sales-battery shop. Dry-run unless --apply and --state-dir.

The phone is a fixture, not a customer. Protected tenants and slugs are refused.
This script does not touch Docker, nginx, or any other shop.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PHONE = "09121110099"
PROTECTED_PHONES = {"09120007777", "09135409482", "09120000000"}
PROTECTED_SLUGS = {"joahr-froshi", "cahrm-srai-pars", "sozan"}
PRODUCTS = [
    ("کفش چرم مشکی", 4000000, 2, "مشکی", "۴۰"),
    ("کفش سفید دوخت", 3500000, 1, "سفید", "۳۸"),
    ("صندل تابستانی", 1800000, 0, "کرم", "۳۷"),
    ("کیف دوشی چرم", 2500000, 3, "قهوه‌ای", ""),
    ("کیف دستی کوچک", 1200000, 4, "مشکی", ""),
    ("کمربند چرم", 900000, 5, "مشکی", "۱۰۰"),
    ("انگشتر نقره", 2500000, 3, "نقره‌ای", ""),
    ("گردنبند فیروزه", 1800000, 0, "آبی", ""),
    ("دستبند مهره", 450000, 6, "قرمز", ""),
    ("گوشواره طلایی", 700000, 2, "طلایی", ""),
    ("شال نخی", 380000, 8, "کرم", ""),
    ("روسری ابریشم", 890000, 2, "سبز", ""),
    ("مانتو لینن", 2200000, 1, "خاکستری", "۴۰"),
    ("شلوار کتان", 1600000, 3, "سرمه‌ای", "۳۸"),
    ("پیراهن مردانه", 980000, 4, "سفید", "لارج"),
    ("کلاه نقاب‌دار", 320000, 7, "مشکی", ""),
    ("عینک آفتابی", 540000, 2, "مشکی", ""),
    ("ساعت بند چرم", 3100000, 1, "قهوه‌ای", ""),
    ("جاکلیدی فلزی", 150000, 10, "نقره‌ای", ""),
    ("ست هدیه", 2750000, 2, "کرم", ""),
]


def seed(state_dir: Path, *, apply: bool) -> None:
    if PHONE in PROTECTED_PHONES:
        raise SystemExit("refusing protected phone")
    tenant = state_dir / "tenants" / PHONE
    shop = tenant / "shop.json"
    slug = ""
    if shop.is_file():
        import json

        row = json.loads(shop.read_text(encoding="utf-8"))
        slug = str(row.get("slug") or "")
        if slug in PROTECTED_SLUGS:
            raise SystemExit(f"refusing protected slug {slug}")
    print(f"tenant {PHONE} dir={tenant} exists={tenant.exists()} slug={slug or '-'}")
    print(f"products {len(PRODUCTS)} orders 0")
    if not apply:
        print("dry-run")
        return
    if tenant.exists():
        shutil.rmtree(tenant)
    from unittest.mock import patch

    from app.config import settings
    from app.services import storefront_service
    from app.state_store import tenant_scope, write_json

    with patch.object(settings, "state_dir", str(state_dir)), tenant_scope(PHONE):
        write_json("shop.json", {"brand": "فروشگاه باتری", "tagline": "فقط آزمون", "slug": "sales-battery", "status": "idle"})
        from PIL import Image

        images = tenant / "scan-images"
        images.mkdir(parents=True, exist_ok=True)
        for index, (title, price, stock, color, size) in enumerate(PRODUCTS, 1):
            name = f"b{index:02d}.jpg"
            Image.new("RGB", (32, 32), (40, 36, 32)).save(images / name, format="JPEG")
            storefront_service.add_product(
                title=title,
                price=price,
                stock=stock,
                sku=f"b{index:02d}",
                image=name,
                colors=[color],
                sizes=size,
            )
        orders = tenant / "orders.json"
        if orders.exists():
            orders.unlink()
    print("seeded")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--state-dir", default="")
    args = parser.parse_args()
    if args.apply and not args.state_dir:
        raise SystemExit("--apply needs --state-dir")
    state = Path(args.state_dir) if args.state_dir else Path("/tmp/sozan-sales-battery-unused")
    seed(state, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
