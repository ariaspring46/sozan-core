# Real create_page executor; verification fails -> are the files it CREATED removed by the rollback?
import asyncio, tempfile
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import shop_edit_service as se

root = Path(tempfile.mkdtemp())
for rel, txt in {"lib/brand.ts": "export const brand = {}\n", "app/page.tsx": "<h1>x</h1>\n", "public/storefront-flags.json": "{}",
                 "public/catalog.json": "[]"}.items():
    (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text(txt)
before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.relative_to(root).parts[0].startswith(".sozan"))
with tenant_scope("09120001111"), patch.object(settings, "state_dir", tempfile.mkdtemp()), \
     patch("app.services.shop_edit_verify.verify_action", lambda **kw: {"ok": False}), patch.object(se, "publish_shop_runtime", lambda *a, **k: None), \
     patch("app.services.shop_service._save_shop", lambda s: None), patch("app.services.shop_service._shop", lambda: {"siteRevision": 0}):
    out = asyncio.run(se._run_action_list({"siteRevision": 0}, root, [{"type": "create_page", "kind": "about"}], prompt="صفحه درباره ما بساز", page="/"))
after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.relative_to(root).parts[0].startswith(".sozan"))
print("rolledBack:", out.get("rolledBack"), "| reply:", out.get("reply")[:60])
print("files left behind by the rolled-back turn:", sorted(set(after) - set(before)))
