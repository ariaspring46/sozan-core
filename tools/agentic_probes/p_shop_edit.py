# Shop-edit action loop: rollback on a failed verify, hero image rollback, leftover per-turn snapshots, 40-file cap.
import asyncio, tempfile
from pathlib import Path
from unittest.mock import patch
from app.config import settings
from app.state_store import tenant_scope
from app.services import shop_edit_service as se

def make_root(n_components=0):
    root = Path(tempfile.mkdtemp())
    for rel, txt in {"lib/brand.ts": "export const brand = { primary: '#111111' }\n", "app/page.tsx": "<h1>سلام</h1>\n",
                     "public/storefront-flags.json": "{}", "public/catalog.json": "[]"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text(txt, encoding="utf-8")
    for i in range(n_components):
        p = root / "components" / f"C{i:02d}.tsx"; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"<p>c{i}</p>\n")
    (root / "public/pages").mkdir(parents=True, exist_ok=True); (root / "public/pages/about.json").write_text('{"t":"old"}')
    (root / "public/images").mkdir(parents=True, exist_ok=True); (root / "public/images/hero.png").write_bytes(b"OLD-HERO")
    return root

def fake_execute(shop, root, action, page):
    rel = action["file"]; (root / rel).write_text(action["new"], encoding="utf-8"); return {"files": [rel], "preview": {}}
async def fake_hero(shop, root, prompt):
    (root / "public/images/hero.png").write_bytes(b"NEW-HERO"); return {"preview": {}}
def verify_fail_on(kind_to_fail):
    def v(*, action, **kw): return {"ok": action.get("tag") != kind_to_fail, "expected": "", "observed": ""}
    return v

def run(root, actions, verify):
    with patch.object(se, "_execute_action", fake_execute), patch.object(se, "apply_hero_image", fake_hero), \
         patch("app.services.shop_edit_verify.verify_action", verify), patch.object(se, "publish_shop_runtime", lambda *a, **k: None), \
         patch.object(se, "publish_shop_hero", lambda *a, **k: None), patch("app.services.shop_service._save_shop", lambda s: None), \
         patch("app.services.shop_service._shop", lambda: {"siteRevision": 0}), patch.object(se, "_finish_edit", lambda shop, reply, *a, **k: {"ok": True, "reply": reply}):
        return asyncio.run(se._run_action_list({"siteRevision": 0}, root, actions, prompt="x", page="/"))

with tenant_scope("09120001111"), patch.object(settings, "state_dir", tempfile.mkdtemp()):
    # 1) two edits, second fails verify -> first must be rolled back
    root = make_root()
    out = run(root, [{"type": "set_colors", "tag": "a", "file": "lib/brand.ts", "new": "export const brand = { primary: '#ff0000' }\n"},
                     {"type": "replace_text", "tag": "b", "file": "app/page.tsx", "new": "<h1>خراب</h1>\n"}], verify_fail_on("b"))
    print("1 rollback brand.ts restored:", "#111111" in (root / "lib/brand.ts").read_text(), "| page restored:", "سلام" in (root / "app/page.tsx").read_text(), "|", out.get("rolledBack"))
    # 2) hero image then a failing edit -> is the hero restored?
    root = make_root()
    run(root, [{"type": "hero_image", "tag": "h"}, {"type": "replace_text", "tag": "b", "file": "app/page.tsx", "new": "x"}], verify_fail_on("b"))
    print("2 hero after rolled-back turn:", (root / "public/images/hero.png").read_bytes())
    # 3) leftover per-turn snapshot dirs after 5 successful edits
    root = make_root()
    for i in range(5):
        run(root, [{"type": "set_colors", "tag": "a", "file": "lib/brand.ts", "new": f"export const brand = {{ primary: '#00000{i}' }}\n"}], verify_fail_on("none"))
    print("3 .sozan-turn-* dirs left after 5 edits:", len(list(root.glob(".sozan-turn-*"))))
    # 4) a storefront with 45 component files: is public/pages/about.json in the snapshot?
    root = make_root(n_components=45)
    print("4 files snapshotted:", len(se._copy_files(root)), "| about.json included:", any(p.name == "about.json" for p in se._copy_files(root)))
    run(root, [{"type": "create_page", "tag": "a", "file": "public/pages/about.json", "new": '{"t":"NEW"}'},
               {"type": "replace_text", "tag": "b", "file": "app/page.tsx", "new": "x"}], verify_fail_on("b"))
    print("  about.json after rolled-back turn:", (root / "public/pages/about.json").read_text())
