#!/usr/bin/env python3
"""Dry-run by default. --apply deletes only the listed test tenants and their shops."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path("/home/ubuntu/sozan-core")
DATA = ROOT / "backend" / "data"
MAP = ROOT / "deploy" / "shop-upstreams.map"
ALLOWED = {"09128880001", "09128880002", "09128880003"}
PROTECTED_PHONES = {"09120007777", "09135409482", "09120000000"}
PROTECTED_SLUGS = {"joahr-froshi", "cahrm-srai-pars", "sozan"}


def run(cmd: list[str], apply: bool) -> None:
    print(" ".join(cmd))
    if apply:
        subprocess.run(cmd, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = args.apply
    slugs: list[str] = []
    for phone in sorted(ALLOWED):
        slug = ""
        shop = DATA / "tenants" / phone / "shop.json"
        if shop.is_file():
            row = json.loads(shop.read_text())
            slug = str(row.get("slug") or "").strip()
            if slug:
                slugs.append(slug)
        print(f"tenant {phone} slug={slug or '-'}")
    for slug in slugs:
        if slug in PROTECTED_SLUGS:
            raise SystemExit(f"refusing protected slug {slug}")
    for phone in ALLOWED & PROTECTED_PHONES:
        raise SystemExit(f"refusing protected phone {phone}")

    for slug in slugs:
        run(["docker", "rm", "-f", f"sozan-{slug}"], apply)
        for site in (
            Path("/home/ubuntu/site-builder/builds") / slug,
            Path("/home/ubuntu/site-builder/sites") / slug,
        ):
            print(f"site_dir {site} exists={site.exists()}")
            if apply and site.exists():
                shutil.rmtree(site)
        if MAP.is_file():
            lines = [line for line in MAP.read_text().splitlines() if line.strip()]
            kept = [line for line in lines if slug not in line.split()[0]]
            print(f"map_drop {len(lines) - len(kept)}")
            if apply and len(kept) != len(lines):
                MAP.write_text("\n".join(kept) + "\n")
        if apply:
            run(["sudo", "nginx", "-t"], True)
            run(["sudo", "systemctl", "reload", "nginx"], True)
        else:
            print("nginx -t && reload")

    for phone in sorted(ALLOWED):
        path = DATA / "tenants" / phone
        print(f"rm_tenant {path} exists={path.exists()}")
        if apply and path.exists():
            shutil.rmtree(path)
        profiles = DATA / "profiles.json"
        if profiles.is_file():
            rows = json.loads(profiles.read_text())
            if isinstance(rows, dict):
                had = phone in rows
                print(f"profile {phone} present={had}")
                if apply and had:
                    rows.pop(phone, None)
                    profiles.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        run(
            [
                "docker",
                "exec",
                "deploy-postgres-1",
                "psql",
                "-U",
                "sozan",
                "-d",
                "sozan_ads",
                "-c",
                f"DELETE FROM users WHERE phone='{phone}';",
            ],
            apply,
        )
    print("APPLY" if apply else "DRY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
