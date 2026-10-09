from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.services import shop_edit_service, shop_service, storefront_service
from app.services.observe_client import emit_later

HINT_NEW_CATEGORY = "دستهٔ جدید در منو بعد از بیلد می‌آید"
HINT_NEEDS_RUNTIME = "برای نمایش کالاها روی سایت، بیلد بزن"


def _prior_slugs(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    cats: dict[str, str] = {}
    subs: dict[str, str] = {}
    path = root / "public" / "catalog.json"
    if not path.is_file():
        return cats, subs
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return cats, subs
    rows = loaded.get("products") if isinstance(loaded, dict) else []
    if not isinstance(rows, list):
        return cats, subs
    for row in rows:
        if not isinstance(row, dict):
            continue
        fa = str(row.get("categoryFa") or "").strip()
        slug = str(row.get("category") or "").strip()
        if fa and slug:
            cats.setdefault(fa, slug)
        sub_fa = str(row.get("subcategoryFa") or "").strip()
        sub = str(row.get("subcategory") or "").strip()
        if sub_fa and sub:
            subs.setdefault(sub_fa, sub)
    return cats, subs


def _shop_image_paths(row: dict) -> tuple[str, list[str]]:
    names: list[str] = []
    for item in row.get("images") or []:
        name = Path(str(item or "")).name
        if name and name not in names and name != "hero.png":
            names.append(name)
    main = Path(str(row.get("image") or "")).name
    if main and main not in names and main != "hero.png":
        names.insert(0, main)
    paths = [f"/products/{name}" for name in names]
    return (paths[0] if paths else ""), paths


def catalog_rows(shop: dict, *, prior_cats: dict[str, str], prior_subs: dict[str, str]) -> tuple[list[dict], bool]:
    hide = bool(shop.get("hidePrices"))
    pending_menu = False
    had_prior = bool(prior_cats)
    items: list[dict] = []
    for row in storefront_service.list_products().get("products") or []:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        category_fa = str(row.get("category") or "").strip() or "کالا"
        subcategory_fa = str(row.get("subcategory") or "").strip()
        if had_prior and category_fa not in prior_cats:
            pending_menu = True
        cat_slug = prior_cats.get(category_fa) or shop_service.factory_category_slug(category_fa)
        if subcategory_fa:
            sub_slug = prior_subs.get(subcategory_fa)
            if not sub_slug:
                derived_slug, derived_fa = shop_service.factory_item_sub(title, category_fa)
                if derived_fa == subcategory_fa:
                    sub_slug = derived_slug
                else:
                    sub_slug = shop_service.factory_category_slug(subcategory_fa)
                    if sub_slug == "goods":
                        sub_slug = derived_slug
        else:
            sub_slug, subcategory_fa = shop_service.factory_item_sub(title, category_fa)
        image, images = _shop_image_paths(row)
        price = int(row.get("price") or 0)
        note = str(row.get("priceNote") or "").strip()
        label = "بدون قیمت" if hide else storefront_service.price_label(price, note)
        item = {
            "id": str(row.get("id") or ""),
            "title": title,
            "description": str(row.get("description") or title)[:400],
            "price": price,
            "category": cat_slug,
            "categoryFa": category_fa,
            "image": image,
        }
        if images:
            item["images"] = images
        discount = int(row.get("discount") or 0)
        if discount:
            item["discount"] = discount
        if int(row.get("stock") or 0) <= 0:
            item["stock"] = 0  # only sold out is published; a count stays the seller's
        if label:
            item["priceLabel"] = label
        if sub_slug:
            item["subcategory"] = sub_slug
        if subcategory_fa:
            item["subcategoryFa"] = subcategory_fa
        specs = []
        colors = [str(item_color).strip() for item_color in (row.get("colors") or []) if str(item_color).strip()]
        if colors:
            specs.append({"label": "رنگ", "value": "، ".join(colors)})
        if row.get("sizes"):
            specs.append({"label": "سایز", "value": str(row.get("sizes"))})
        if specs:
            item["specs"] = specs
        items.append(item)
    return items, pending_menu


def shop_meta(shop: dict | None = None) -> dict:
    row = shop if isinstance(shop, dict) else shop_service.current_shop()
    root = shop_edit_service.build_dir_for(row)
    overlay = shop_edit_service.has_runtime_overlay(root)
    live = shop_service.shop_is_live(row)
    return {
        "live": live,
        "slug": str(row.get("slug") or ""),
        "pendingBuild": int(row.get("pendingBuild") or 0),
        "hidePrices": bool(row.get("hidePrices")),
        "runtimeCatalog": overlay,
        "needsBuild": bool(live and not overlay),
    }


def sync_live(*, changed_images: list[str] | None = None) -> dict:
    shop = shop_service.current_shop()
    live = shop_service.shop_is_live(shop)
    slug = str(shop.get("slug") or "").strip()
    protected = slug in shop_service.PROTECTED_SHOP_SLUGS
    root = shop_edit_service.build_dir_for(shop)
    result: dict = {"live": False, "slug": slug}
    if root is None:
        result["reason"] = "no-build-dir"
        emit_later(kind="catalog", surface="shop", title="sync-live", status="skipped", payload=result)
        return result
    prior_cats, prior_subs = _prior_slugs(root)
    rows, pending_menu = catalog_rows(shop, prior_cats=prior_cats, prior_subs=prior_subs)
    shop_edit_service.write_catalog_json(root, rows)
    from app.services.channel_scan_service import scan_dir as _scan_dir

    scan = _scan_dir()
    rels = ["public/catalog.json"]
    copied: list[str] = []
    for raw in changed_images or []:
        name = Path(str(raw or "")).name
        if not name:
            continue
        src = scan / name
        if not src.is_file():
            continue
        dest = root / "public" / "products" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        rels.append(f"public/products/{name}")
        copied.append(name)
    result["copied"] = copied
    result["pendingMenu"] = pending_menu
    if pending_menu:
        result["hint"] = HINT_NEW_CATEGORY
        if live and not protected:
            shop_service.bump_pending(shop)
            result["pendingBuild"] = int(shop_service.current_shop().get("pendingBuild") or 0)
    overlay = shop_edit_service.has_runtime_overlay(root)
    if live and not protected and not overlay:
        if int(shop_service.current_shop().get("pendingBuild") or 0) == 0:
            shop_service.bump_pending(shop)
        result["live"] = False
        result["reason"] = "no-runtime"
        result["hint"] = HINT_NEEDS_RUNTIME
        result["pendingBuild"] = int(shop_service.current_shop().get("pendingBuild") or 0)
        emit_later(kind="catalog", surface="shop", title="sync-live", status="ok", payload=result)
        return result
    if not live or protected:
        result["reason"] = "protected" if protected else "not-live"
        emit_later(kind="catalog", surface="shop", title="sync-live", status="ok", payload=result)
        return result
    shop_edit_service.publish_shop_runtime(shop, root, rels)
    result["live"] = True
    emit_later(kind="catalog", surface="shop", title="sync-live", status="ok", payload=result)
    return result
