"""Undo stack for live shop edits.

Every successful edit keeps a snapshot of the editable files taken just before it (`.sozan-undo/<n>/`) and a small
`<n>.json` with what the snapshot cannot hold (pending count, files the edit created, product photos, price flag).
«برگشت» in the panel pops one snapshot; a successful build clears the stack, so what was built can no longer be undone.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

UNDO_DIR = ".sozan-undo"
UNDO_CAP = 12

NOTHING_TO_UNDO = "چیزی برای برگشت نیست؛ بعد از هر بیلد تغییرهای قبلی قفل می‌شوند."


def _base(root: Path) -> Path:
    return root / UNDO_DIR


def _numbers(root: Path) -> list[int]:
    base = _base(root)
    if not base.is_dir():
        return []
    return sorted(int(path.name) for path in base.iterdir() if path.is_dir() and path.name.isdigit())


def depth(root: Path | None) -> int:
    return len(_numbers(root)) if root is not None else 0


def push(root: Path, snap: Path, meta: dict) -> int:
    """Move a finished turn snapshot onto the stack; returns the new depth."""
    base = _base(root)
    base.mkdir(parents=True, exist_ok=True)
    numbers = _numbers(root)
    seq = (numbers[-1] + 1) if numbers else 1
    shutil.move(str(snap), str(base / f"{seq:06d}"))
    (base / f"{seq:06d}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    numbers = _numbers(root)
    for old in numbers[: max(0, len(numbers) - UNDO_CAP)]:
        drop(root, old)
    return depth(root)


def peek(root: Path) -> tuple[int, dict] | None:
    numbers = _numbers(root)
    if not numbers:
        return None
    top = numbers[-1]
    try:
        meta = json.loads((_base(root) / f"{top:06d}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    return top, meta if isinstance(meta, dict) else {}


def rel_name(number: int) -> str:
    return f"{UNDO_DIR}/{number:06d}"


def drop(root: Path, number: int) -> None:
    shutil.rmtree(_base(root) / f"{number:06d}", ignore_errors=True)
    (_base(root) / f"{number:06d}.json").unlink(missing_ok=True)


def clear(root: Path | None) -> None:
    if root is not None:
        shutil.rmtree(_base(root), ignore_errors=True)


def clear_for(shop: dict) -> None:
    """After a successful build: what is live now can no longer be undone."""
    from app.services import shop_edit_service

    try:
        clear(shop_edit_service.build_dir_for(shop))
    except OSError:
        pass


def undo_last(shop: dict) -> dict:
    """Pop the newest snapshot: restore its files, put the pending counter and product photos back."""
    from app.services import shop_edit_service as edit
    from app.services.shop_service import _save_shop

    root = edit.build_dir_for(shop)
    if root is None:
        return {"ok": True, "patched": False, "reply": "پوشهٔ سایت پیدا نشد."}
    top = peek(root)
    if top is None:
        return {"ok": True, "patched": False, "reply": NOTHING_TO_UNDO, "undoDepth": 0}
    number, meta = top
    hero = root / edit.HERO_REL
    hero_now = hero.read_bytes() if hero.is_file() else None
    edit._restore_and_republish(shop, root, rel_name(number), [str(rel) for rel in meta.get("published") or []])
    if isinstance(meta.get("tree"), list):
        edit.remove_new_files(root, {str(rel) for rel in meta["tree"]})
    if meta.get("hero") is False and hero.is_file():
        hero.unlink()
    elif hero.is_file() and hero.read_bytes() != hero_now:
        edit.publish_shop_hero(shop, hero)
    new_file = str(meta.get("newFile") or "")
    if new_file and ".." not in new_file:
        (root / new_file).unlink(missing_ok=True)
    product = meta.get("product")
    if isinstance(product, dict) and product.get("id"):
        _restore_product(product)
    if "hidePrices" in meta:
        shop["hidePrices"] = bool(meta["hidePrices"])
    drop(root, number)
    shop["pendingBuild"] = max(0, int(meta.get("pending") or 0))
    shop["siteRevision"] = int(shop.get("siteRevision") or 0) + 1
    _save_shop(shop)
    left = depth(root)
    return {
        "ok": True,
        "patched": True,
        "reply": "به حالت قبل برگشت.",
        "preview": {"undo": True, "to": left, "reload": True},
        "pendingBuild": int(shop.get("pendingBuild") or 0),
        "undoDepth": left,
    }


def _restore_product(product: dict) -> None:
    from app.services import catalog_sync_service, storefront_service

    names = [str(name) for name in product.get("images") or [] if name]
    try:
        storefront_service.update_product(str(product["id"]), {"images": names, "image": names[0] if names else ""})
        catalog_sync_service.sync_live(changed_images=names)
    except (KeyError, ValueError):
        pass
