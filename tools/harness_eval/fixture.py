"""The eval fixture: one dedicated tenant and its site folder, frozen as a golden copy and restored before every case.

Only paths under ~/sozan-eval are ever removed or written here. The seed comes from tools/sales_tenant_reset.py, with
the fixture's own phone and slug. Production tenants are never opened.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import common

STATE = common.EVAL_HOME / "state"
GOLDEN = common.EVAL_HOME / "golden"
SITE = common.EVAL_HOME / "site"
READ_LIMIT = 2_000_000


def tenant_dir() -> Path:
    return STATE / "tenants" / common.FIXTURE_PHONE


def live_roots() -> dict[str, Path]:
    return {"tenant": tenant_dir(), "site": SITE}


def golden_roots() -> dict[str, Path]:
    return {"tenant": GOLDEN / "tenant", "site": GOLDEN / "site"}


def build_golden() -> None:
    """Seeds the fixture once and freezes it. Needs the app importable and STATE_DIR already pointing at STATE."""
    if (GOLDEN / "tenant" / "shop.json").is_file():
        return
    STATE.mkdir(parents=True, exist_ok=True)
    for name in ("settings.json", "llm-routing.json", "ai-budget.json", "profiles.json"):
        source = common.PROD_DATA / name
        if source.is_file():
            shutil.copy(source, STATE / name)
    sys.path.insert(0, str(common.TOOLS))
    import sales_tenant_reset as seeder

    seeder.PHONE = common.FIXTURE_PHONE
    seeder.seed(STATE, apply=True)
    shop = tenant_dir() / "shop.json"
    row = json.loads(shop.read_text(encoding="utf-8"))
    row.update(
        {
            "brand": "آزمون سوزان",
            "tagline": "فقط آزمون",
            "slug": common.FIXTURE_SLUG,
            "status": "idle",
            "url": f"https://{common.FIXTURE_SLUG}.sozan-core.ir",
        }
    )
    shop.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    SITE.mkdir(parents=True, exist_ok=True)
    GOLDEN.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tenant_dir(), GOLDEN / "tenant", ignore=shutil.ignore_patterns(".lock-*"))
    shutil.copytree(SITE, GOLDEN / "site", dirs_exist_ok=True)


def restore() -> None:
    """Puts the tenant and the site folder back to the golden copy. Refuses any path outside the eval home."""
    home = common.EVAL_HOME.resolve()
    for target in (tenant_dir(), SITE):
        if home not in target.resolve().parents:
            raise RuntimeError(f"refusing to reset {target}: outside {home}")
    if tenant_dir().exists():
        shutil.rmtree(tenant_dir())
    shutil.copytree(GOLDEN / "tenant", tenant_dir())
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(GOLDEN / "site", SITE)


def golden_hashes() -> dict[str, str]:
    return {**common.tree_hashes(GOLDEN / "tenant", "tenant"), **common.tree_hashes(GOLDEN / "site", "site")}


def live_hashes() -> dict[str, str]:
    return {**common.tree_hashes(tenant_dir(), "tenant"), **common.tree_hashes(SITE, "site")}


def read_value(rel: str, *, golden: bool):
    """Parsed JSON, or text, or None when the file is missing. `rel` is `tenant/...` or `site/...`."""
    key, _, inner = rel.partition("/")
    roots = golden_roots() if golden else live_roots()
    path = roots[key] / inner
    if not path.is_file():
        return None
    if path.stat().st_size > READ_LIMIT:
        return "<too large to read>"
    text = path.read_text(encoding="utf-8", errors="replace")
    if rel.endswith(".json"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text
