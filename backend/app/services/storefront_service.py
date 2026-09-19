from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from app.state_store import read_json, write_json


def _list(name: str) -> list[dict]:
    rows = read_json(name, [])
    return rows if isinstance(rows, list) else []


def _save(name: str, rows: list[dict]) -> None:
    write_json(name, rows)


ASK_PRICE = "تماس بگیرید"
PRICE_NOTES = ("", "دایرکت", ASK_PRICE)
IMAGE_CAP = 5
COLOR_CAP = 6
TEXT_SHORT = 40
TEXT_LONG = 400


def price_label(price: int, note: str = "") -> str:
    cleaned = str(note or "").strip()
    if cleaned == "دایرکت":
        return "دایرکت"
    if cleaned == ASK_PRICE:
        return ASK_PRICE
    if int(price or 0) <= 0:
        return ASK_PRICE
    return ""


def _clean_text(raw: object, limit: int) -> str:
    return str(raw or "").strip()[:limit]


def _clean_category(raw: str) -> str:
    return _clean_text(raw, TEXT_SHORT)


def _clean_colors(raw: list | None) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        text = _clean_text(item, TEXT_SHORT)
        if text and text not in out:
            out.append(text)
        if len(out) >= COLOR_CAP:
            break
    return out


def _clean_discount(value: object) -> int:
    n = int(value or 0)
    if n < 0 or n > 90:
        raise ValueError("تخفیف باید بین ۰ تا ۹۰ باشد")
    return n


def _clean_price_note(raw: str) -> str:
    note = _clean_text(raw, TEXT_SHORT)
    if note not in PRICE_NOTES:
        raise ValueError("حالت قیمت معتبر نیست")
    return note


def _require_image(name: str) -> str:
    safe = Path(str(name or "")).name
    if not safe:
        return ""
    if safe != Path(str(name)).name:
        raise ValueError("نام تصویر نامعتبر است")
    from app.services.channel_scan_service import _scan_dir

    path = _scan_dir() / safe
    if not path.is_file():
        raise ValueError("تصویر کالا پیدا نشد")
    return safe


def _row_images(row: dict | None) -> list[str]:
    if not isinstance(row, dict):
        return []
    names: list[str] = []
    for item in row.get("images") or []:
        name = Path(str(item or "")).name
        if name and name not in names:
            names.append(name)
    main = Path(str(row.get("image") or "")).name
    if main and main not in names:
        names.insert(0, main)
    elif main and names and names[0] != main:
        names.remove(main)
        names.insert(0, main)
    return names[:IMAGE_CAP]


def _apply_media(row: dict, *, image: object = None, images: object = None, require: bool = True) -> None:
    current = _row_images(row)
    if images is not None:
        names: list[str] = []
        for item in images or []:
            raw = Path(str(item or "")).name
            safe = _require_image(raw) if require and raw else raw
            if safe and safe not in names:
                names.append(safe)
            if len(names) >= IMAGE_CAP:
                break
        current = names
    if image is not None:
        raw = Path(str(image or "")).name if str(image or "").strip() else ""
        safe = _require_image(raw) if require and raw else raw
        if safe:
            current = [safe] + [name for name in current if name != safe]
        elif images is not None:
            pass
        else:
            current = current[1:] if current else []
    current = current[:IMAGE_CAP]
    row["images"] = current
    row["image"] = current[0] if current else ""


def public_product(row: dict) -> dict:
    out = dict(row)
    images = _row_images(out)
    out["images"] = images
    out["image"] = images[0] if images else str(out.get("image") or "")
    out["category"] = _clean_category(str(out.get("category") or ""))
    out["subcategory"] = _clean_category(str(out.get("subcategory") or ""))
    out["colors"] = _clean_colors(out.get("colors") if isinstance(out.get("colors"), list) else [])
    out["sizes"] = _clean_text(out.get("sizes"), TEXT_SHORT)
    out["description"] = _clean_text(out.get("description"), TEXT_LONG)
    out["sku"] = _clean_text(out.get("sku"), 80)
    discount = int(out.get("discount") or 0)
    if discount < 0:
        discount = 0
    if discount > 90:
        discount = 90
    out["discount"] = discount
    price = int(out.get("price") or 0)
    note = str(out.get("priceNote") or "")
    out["priceLabel"] = price_label(price, note)
    if discount > 0 and price > 0:
        out["finalPrice"] = int(price * (100 - discount) / 100)
    else:
        out.pop("finalPrice", None)
    return out


def list_products() -> dict:
    return {"products": [public_product(row) for row in _list("products.json")]}


def categories() -> list[dict]:
    buckets: dict[str, dict] = {}
    for row in _list("products.json"):
        cat = _clean_category(str(row.get("category") or ""))
        if not cat:
            continue
        bucket = buckets.setdefault(cat, {"title": cat, "subcategories": [], "count": 0})
        bucket["count"] += 1
        sub = _clean_category(str(row.get("subcategory") or ""))
        if sub and sub not in bucket["subcategories"]:
            bucket["subcategories"].append(sub)
    scan = read_json("channel-scan.json", {})
    for item in (scan.get("categories") or []) if isinstance(scan, dict) else []:
        text = _clean_category(str(item))
        if text and text not in buckets:
            buckets[text] = {"title": text, "subcategories": [], "count": 0}
    return sorted(buckets.values(), key=lambda row: (-int(row.get("count") or 0), str(row.get("title") or "")))


def add_product(
    *,
    title: str,
    price: int,
    stock: int,
    sku: str,
    image: str = "",
    images: list | None = None,
    source: str = "",
    sourceHandle: str = "",
    description: str = "",
    category: str = "",
    subcategory: str = "",
    colors: list | None = None,
    sizes: str = "",
    priceNote: str = "",
    discount: int = 0,
) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("نام محصول را بنویس")
    if price < 0 or stock < 0:
        raise ValueError("قیمت و موجودی منفی نمی‌شود")
    row = {
        "id": str(uuid4()),
        "title": title,
        "price": int(price),
        "stock": int(stock),
        "sku": _clean_text(sku, 80),
        "image": "",
        "images": [],
        "source": source.strip(),
        "sourceHandle": sourceHandle.strip(),
        "description": _clean_text(description, TEXT_LONG),
        "category": _clean_category(category),
        "subcategory": _clean_category(subcategory),
        "colors": _clean_colors(colors),
        "sizes": _clean_text(sizes, TEXT_SHORT),
        "priceNote": _clean_price_note(priceNote),
        "discount": _clean_discount(discount),
        "at": int(time.time()),
    }
    _apply_media(row, image=image or "", images=images)
    rows = _list("products.json")
    rows.append(row)
    _save("products.json", rows)
    return {"product": public_product(row), "products": [public_product(item) for item in rows]}


def count_scanned_handle(source_handles: list[str]) -> int:
    """Products already imported from any of `source_handles`."""
    wanted = {str(item or "").strip() for item in source_handles if str(item or "").strip()}
    if not wanted:
        return 0
    return sum(1 for row in _list("products.json") if str(row.get("sourceHandle") or "").strip() in wanted)


def remove_scanned_handle(source_handle: str) -> None:
    handle = source_handle.strip()
    if not handle:
        return
    rows = [row for row in _list("products.json") if str(row.get("sourceHandle") or "") != handle]
    _save("products.json", rows)


def clear_scanned_catalog() -> None:
    rows = [row for row in _list("products.json") if not str(row.get("source") or "").strip()]
    _save("products.json", rows)


def retitle_scanned_from_captions() -> int:
    from app.services.channel_scan_service import _looks_like_product_title, product_title_from_caption

    rows = _list("products.json")
    changed = 0
    seen: set[str] = set()
    for row in rows:
        if not row.get("source"):
            continue
        current = str(row.get("title") or "").strip()
        if current and _looks_like_product_title(current):
            seen.add(current)
            continue
        title = product_title_from_caption(str(row.get("description") or ""))
        if title and title != current and title not in seen:
            row["title"] = title
            changed += 1
            seen.add(title)
        elif current:
            seen.add(current)
    if changed:
        _save("products.json", rows)
    return changed


def upsert_scanned_product(
    *,
    title: str,
    price: int,
    description: str,
    sku: str,
    image: str,
    source: str,
    sourceHandle: str,
    category: str = "",
    colors: list | None = None,
    sizes: str = "",
    priceNote: str = "",
    sourcePostId: str = "",
    sourceCaption: str = "",
    extractor: str = "",
    confidence: float = 0.0,
    priceStatus: str = "",
    priceUnit: str = "toman",
    stableKey: str = "",
    stock: int | None = None,
) -> dict:
    rows = _list("products.json")
    cat = _clean_category(category)
    color_list = _clean_colors(colors)
    size_text = _clean_text(sizes, TEXT_SHORT)
    try:
        note = _clean_price_note(priceNote)
    except ValueError:
        note = _clean_text(priceNote, TEXT_SHORT)
    key = (stableKey or "").strip()
    for row in rows:
        same_key = key and str(row.get("stableKey") or "") == key
        same_title = str(row.get("title") or "").strip() == title.strip() and str(row.get("sourceHandle") or "") == sourceHandle
        if not same_key and not same_title:
            continue
        row["price"] = int(price)
        row["description"] = description
        if image:
            try:
                _apply_media(row, image=image, require=True)
            except ValueError:
                _apply_media(row, image=Path(str(image)).name, require=False)
        row["source"] = source
        if cat:
            row["category"] = cat
        if color_list:
            row["colors"] = color_list
        if size_text:
            row["sizes"] = size_text
        row["priceNote"] = note
        if sourcePostId:
            row["sourcePostId"] = sourcePostId
        if sourceCaption:
            row["sourceCaption"] = sourceCaption
        if extractor:
            row["extractor"] = extractor
        if confidence:
            row["confidence"] = confidence
        if priceStatus:
            row["priceStatus"] = priceStatus
        row["priceUnit"] = priceUnit or "toman"
        if key:
            row["stableKey"] = key
        if stock is not None:
            row["stock"] = int(stock)
        _save("products.json", rows)
        return public_product(row)
    image_name = ""
    if image:
        try:
            image_name = _require_image(image)
        except ValueError:
            image_name = ""
    added = add_product(
        title=title,
        price=price,
        stock=24 if stock is None else int(stock),
        sku=sku,
        image=image_name,
        source=source,
        sourceHandle=sourceHandle,
        description=description,
        category=cat,
        colors=color_list,
        sizes=size_text,
        priceNote=note if note in PRICE_NOTES else "",
    )
    row = added["product"]
    stored = _list("products.json")
    for item in stored:
        if item.get("id") == row.get("id"):
            item["sourcePostId"] = sourcePostId
            item["sourceCaption"] = sourceCaption
            item["extractor"] = extractor
            item["confidence"] = confidence
            item["priceStatus"] = priceStatus
            item["priceUnit"] = priceUnit or "toman"
            item["stableKey"] = key
            break
    _save("products.json", stored)
    return public_product(next((item for item in stored if item.get("id") == row.get("id")), row))


def update_product(product_id: str, patch: dict) -> dict:
    rows = _list("products.json")
    found = None
    for row in rows:
        if str(row.get("id")) == product_id:
            found = row
            break
    if found is None:
        raise KeyError("محصول پیدا نشد")
    if "title" in patch and patch["title"] is not None:
        title = str(patch["title"]).strip()
        if not title:
            raise ValueError("نام محصول را بنویس")
        found["title"] = title
    if "price" in patch and patch["price"] is not None:
        if int(patch["price"]) < 0:
            raise ValueError("قیمت منفی نمی‌شود")
        found["price"] = int(patch["price"])
    if "stock" in patch and patch["stock"] is not None:
        if int(patch["stock"]) < 0:
            raise ValueError("موجودی منفی نمی‌شود")
        found["stock"] = int(patch["stock"])
    if "sku" in patch and patch["sku"] is not None:
        found["sku"] = _clean_text(patch["sku"], 80)
    if "description" in patch and patch["description"] is not None:
        found["description"] = _clean_text(patch["description"], TEXT_LONG)
    if "category" in patch and patch["category"] is not None:
        found["category"] = _clean_category(str(patch["category"]))
    if "subcategory" in patch and patch["subcategory"] is not None:
        found["subcategory"] = _clean_category(str(patch["subcategory"]))
    if "colors" in patch and patch["colors"] is not None:
        found["colors"] = _clean_colors(patch["colors"] if isinstance(patch["colors"], list) else [])
    if "sizes" in patch and patch["sizes"] is not None:
        found["sizes"] = _clean_text(patch["sizes"], TEXT_SHORT)
    if "priceNote" in patch and patch["priceNote"] is not None:
        found["priceNote"] = _clean_price_note(str(patch["priceNote"]))
    if "discount" in patch and patch["discount"] is not None:
        found["discount"] = _clean_discount(patch["discount"])
    if "image" in patch or "images" in patch:
        _apply_media(
            found,
            image=patch["image"] if "image" in patch else None,
            images=patch["images"] if "images" in patch else None,
        )
    _save("products.json", rows)
    if {"price", "priceNote", "image", "images"} & set(patch.keys()):
        try:
            from app.services.shop_service import bump_pending_build

            bump_pending_build()
        except Exception:
            pass
    return {"product": public_product(found), "products": [public_product(item) for item in rows]}


def set_main_image(product_id: str, name: str) -> dict:
    return update_product(product_id, {"image": name})


def adjust_stock(product_id: str, delta: int) -> dict:
    if delta == 0:
        raise ValueError("مقدار تغییر صفر است")
    rows = _list("products.json")
    found = next((row for row in rows if str(row.get("id")) == product_id), None)
    if found is None:
        raise KeyError("کالا پیدا نشد")
    next_stock = int(found.get("stock") or 0) + int(delta)
    if next_stock < 0:
        raise ValueError("موجودی کمتر از صفر نمی‌شود")
    found["stock"] = next_stock
    _save("products.json", rows)
    return {"product": public_product(found), "products": [public_product(item) for item in rows]}


def remove_product(product_id: str) -> dict:
    rows = _list("products.json")
    removed = next((row for row in rows if str(row.get("id")) == product_id), None)
    kept = [row for row in rows if str(row.get("id")) != product_id]
    _save("products.json", kept)
    return {
        "products": [public_product(item) for item in kept],
        "removedImages": _row_images(removed) if removed else [],
    }


def remove_product_by_title(title: str) -> dict:
    wanted = title.strip()
    rows = [row for row in _list("products.json") if str(row.get("title") or "").strip() != wanted]
    _save("products.json", rows)
    return {"products": [public_product(item) for item in rows]}


def referenced_image_names() -> set[str]:
    names: set[str] = set()
    for row in _list("products.json"):
        names.update(_row_images(row))
    return names


def list_sales() -> dict:
    rows = sorted(_list("sales.json"), key=lambda row: int(row.get("at") or 0), reverse=True)
    return {"sales": rows}


def add_sale(*, title: str, amount: int, customer: str, channel: str) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("شرح فروش را بنویس")
    if amount < 0:
        raise ValueError("مبلغ منفی نمی‌شود")
    row = {
        "id": str(uuid4()),
        "title": title,
        "amount": int(amount),
        "customer": customer.strip() or "مشتری",
        "channel": channel.strip() or "فروشگاه",
        "status": "paid",
        "at": int(time.time()),
    }
    rows = _list("sales.json")
    rows.append(row)
    _save("sales.json", rows)
    return {"sale": row, "sales": sorted(rows, key=lambda item: int(item.get("at") or 0), reverse=True)}
