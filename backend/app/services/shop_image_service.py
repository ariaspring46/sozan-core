"""Swap one picture on the live shop with a photo the seller uploaded.

The panel's preview reports the `src` of the picture the seller held a finger on. Three kinds can be swapped:
the big top picture (hero), the logo, and a product photo (that one goes through the inventory so the app and the
shop stay the same). Every swap is one «برگشت» step.
"""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from PIL import Image, ImageOps

from app.services import chat_media_service

MAX_BYTES = 8_000_000
HERO_SIDE = 1920
LOGO_SIDE = 512

CANNOT = "این عکس را نمی‌شود عوض کرد. عکس بالای سایت، لوگو یا عکس یکی از کالاها را نگه دار."


def _site_path(src: str) -> str:
    """The path of the picture inside the shop, also when Next served it through /_next/image?url=…"""
    raw = str(src or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path or ""
    if path.rstrip("/").endswith("/_next/image"):
        inner = (parse_qs(parsed.query).get("url") or [""])[0]
        path = urlparse(unquote(inner)).path or ""
    path = unquote(path)
    if ".." in path or "\\" in path or "\0" in path:
        return ""
    return str(PurePosixPath("/" + path.lstrip("/")))


def _row_by_product_path(product: str, products: list[dict]) -> dict | None:
    """The inventory row of a storefront card path like /products/<id>."""
    wanted = PurePosixPath(_site_path(product)).name if product else ""
    if not wanted or not _site_path(product).startswith("/products/"):
        return None
    return next((row for row in products if str(row.get("id") or "") == wanted), None)


def classify(src: str, products: list[dict], product: str = "") -> tuple[str, str, dict | None]:
    """(kind, file name, product row) for a picture; kind is '' when it cannot be swapped.

    `product` is the /products/<id> card the press sat in: a product with no photo yet (a placeholder, or nothing) still gets one."""
    path = _site_path(src)
    name = PurePosixPath(path).name if path else ""
    if name == "hero.png":
        return "hero", name, None
    if name == "brand-logo.png":
        return "logo", name, None
    if name and path.startswith("/products/"):
        for row in products:
            images = {Path(str(item)).name for item in (row.get("images") or [])}
            images.add(Path(str(row.get("image") or "")).name)
            if name in images:
                return "product", name, row
    row = _row_by_product_path(product, products)
    if row is not None:
        return "product", "", row
    return "", name, None


def _open(data: bytes, content_type: str, filename: str) -> Image.Image:
    if not data:
        raise ValueError("فایل خالی است")
    if len(data) > MAX_BYTES:
        raise ValueError("عکس بزرگ‌تر از ۸ مگابایت است")
    if chat_media_service.kind_of(content_type, filename) != "image":
        raise ValueError("فقط عکس می‌شود گذاشت")
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError("این فایل عکس معتبر نیست") from exc
    return ImageOps.exif_transpose(img)


def _fit(img: Image.Image, side: int) -> Image.Image:
    longest = max(img.size)
    if longest <= side:
        return img
    scale = side / float(longest)
    return img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.Resampling.LANCZOS)


def _png_bytes(img: Image.Image, *, alpha: bool) -> bytes:
    img = img.convert("RGBA" if alpha else "RGB")
    out = BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def replace_image(shop: dict, data: bytes, content_type: str, filename: str, src: str, product: str = "") -> dict:
    from app.services import catalog_sync_service, shop_edit_service as edit, shop_undo_service, storefront_service
    from app.services.shop_service import PROTECTED_SHOP_SLUGS

    slug = str(shop.get("slug") or "").strip()
    root = edit.build_dir_for(shop)
    if not slug or root is None:
        raise ValueError("فروشگاه هنوز ساخته نشده.")
    if slug in PROTECTED_SHOP_SLUGS:
        raise ValueError("این فروشگاه را از اینجا نمی‌شود ویرایش کرد.")
    products = storefront_service.list_products().get("products") or []
    kind, name, row = classify(src, products, product)
    if not kind:
        raise ValueError(CANNOT)
    img = _open(data, content_type, filename)

    pending_before = int(shop.get("pendingBuild") or 0)
    tree_before = edit._edit_tree(root)
    hero = root / edit.HERO_REL
    hero_before = hero.read_bytes() if hero.is_file() else None
    snap_name = f".sozan-turn-{uuid4().hex[:8]}"
    edit.snapshot_edit_files(root, snap_name)
    meta: dict = {
        "pending": pending_before,
        "tree": sorted(tree_before),
        "hero": hero_before is not None,
        "hidePrices": bool(shop.get("hidePrices")),
        "published": [],
    }
    needs_rebuild = True
    try:
        if kind == "hero":
            hero.parent.mkdir(parents=True, exist_ok=True)
            hero.write_bytes(_png_bytes(_fit(img, HERO_SIDE), alpha=False))
            edit.publish_shop_hero(shop, hero)
            reply = "عکس بالای سایت عوض شد."
        elif kind == "logo":
            logo = root / "public" / "brand-logo.png"
            if logo.is_file():
                kept = root / snap_name / "public" / "brand-logo.png"
                kept.parent.mkdir(parents=True, exist_ok=True)
                kept.write_bytes(logo.read_bytes())
            else:
                meta["newFile"] = "public/brand-logo.png"
            logo.write_bytes(_png_bytes(_fit(img, LOGO_SIDE), alpha=True))
            edit.publish_shop_runtime(shop, root, ["public/brand-logo.png"])
            meta["published"] = ["public/brand-logo.png"]
            reply = "لوگو عوض شد."
        else:
            from app.services import product_image_service

            old = [Path(str(item)).name for item in (row.get("images") or []) if item]
            main = Path(str(row.get("image") or "")).name
            if main and main not in old:
                old.insert(0, main)
            stored = product_image_service.store(data, content_type, filename)
            # a known photo is replaced in place; a product without one (or with a placeholder) gets the photo as its first
            fresh = [stored if item == name else item for item in old] if name in old else [stored, *old]
            meta["product"] = {"id": str(row.get("id") or ""), "images": old}
            storefront_service.update_product(str(row.get("id") or ""), {"images": fresh, "image": fresh[0]})
            sync = catalog_sync_service.sync_live(changed_images=[stored])
            needs_rebuild = not sync.get("live")
            reply = f"عکس «{row.get('title') or 'کالا'}» {'عوض شد' if name in old else 'گذاشته شد'}."
    except Exception:
        edit._rollback_turn(shop, root, snap_name, [], tree_before, hero_before)
        if isinstance(meta.get("product"), dict):
            shop_undo_service._restore_product(meta["product"])
        shutil.rmtree(root / snap_name, ignore_errors=True)
        raise
    snap = root / snap_name
    if snap.is_dir():
        shop_undo_service.push(root, snap, meta)
    out = edit._finish_edit(
        shop,
        reply,
        True,
        {"reload": True},
        prompt="عوض کردن عکس",
        root=root,
        needs_rebuild=needs_rebuild,
    )
    out["kind"] = kind
    return out
