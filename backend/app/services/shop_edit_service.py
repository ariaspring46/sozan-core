from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

from app.config import settings
from app.services.llm import complete_json

BRAND_KEYS = (
    "name",
    "tagline",
    "primary",
    "accent",
    "deep",
    "soft",
    "background",
    "foreground",
    "ctaLabelFa",
    "cartCtaFa",
    "eyebrow",
    "moodFa",
)
COLOR_KEYS = frozenset({"primary", "accent", "deep", "soft", "background", "foreground"})
NAMED_COLORS = {
    "قرمز": "#B42318",
    "سرخ": "#B42318",
    "آبی": "#1D4ED8",
    "سبز": "#15803D",
    "مسی": "#C45C26",
    "زرشکی": "#7A1F2B",
    "طلایی": "#C9A227",
    "کرم": "#F3E6C8",
    "صورتی": "#DB2777",
    "بنفش": "#7C3AED",
    "نارنجی": "#EA580C",
    "مشکی": "#1A1714",
    "سیاه": "#1A1714",
}
REVERT_RE = re.compile(r"برگرد|حالت قبل|undo|revert|اشتباه ویرایش", re.I)
WRITE_RE = re.compile(r"^(?:بنویس(?:ید|ی)?)\s+[«\"']?(.+?)[»\"']?\s*$")
HERO_IMAGE_RE = re.compile(
    r"(?:تصویر|عکس).{0,48}(?:بساز|طراحی)|(?:بساز|طراحی).{0,48}(?:تصویر|عکس)|بک\s*گراند|پس[-\s]?زمینه",
    re.I,
)
FOREIGN_PAYLOAD_RE = re.compile(r"https?://|[A-Fa-f0-9]{24,}")
SUCCESS_CLAIM_RE = re.compile(r"به‌روزرسانی|بروزرسانی|ساخته شد|جایگزین|تولید شد|اعمال شد|موفقیت|حذف شد|نمایش داده نمی‌شود")
DELETE_TEXT_RE = re.compile(r"حذف کن|پاکش کن|پاک کن|این متن رو کلا حذف")
PREV_DIR = ".sozan-prev"
FRAME_DIR = ".sozan-frame"
LLM_ACTION_TYPES = frozenset(
    {
        "set_colors",
        "set_brand",
        "replace_text",
        "delete_text",
        "add_product",
        "remove_product",
        "set_header",
        "add_nav_link",
        "create_page",
        "ask_clarify",
        "hide_prices",
        "show_prices",
    }
)
PAGE_KINDS = frozenset({"about", "contact", "story", "faq"})
NAV_HREFS = frozenset({"/", "/products", "/cart", "/about", "/contact", "/story", "/faq", "/login"})
CHROME_LIVE_KINDS = frozenset({"hide_prices", "show_prices", "add_nav_link", "create_page", "set_header"})
EDIT_SYSTEM = """تو ویرایشگر فروشگاه سوزان هستی. فقط JSON بده:
{"reply":"کوتاه","actions":[{"type":"set_brand","fields":{"name":"..."}}]}
فایل و TSX ننویس. فقط اکشن و اسلات. نوع‌های مجاز:
set_colors, set_brand, replace_text, delete_text, add_product, remove_product,
set_header, add_nav_link, create_page, ask_clarify, hide_prices, show_prices.
set_colors.colors فقط primary accent deep soft background foreground با hex.
set_brand.fields فقط name tagline ctaLabelFa cartCtaFa eyebrow moodFa.
create_page.kind فقط about یا contact یا story یا faq. اگر نامشخص است type=ask_clarify.
add_nav_link.href فقط / /products /cart /about /contact /story /faq.
اگر اسلات اجباری خالی است ask_clarify بده نه حدس.
reply را کوتاه بنویس؛ مجری از نتیجهٔ دیسک جواب نهایی را می‌سازد."""


def safe_view_path(raw: str) -> str:
    value = (raw or "/").strip() or "/"
    if value.startswith("http"):
        value = urlparse(value).path or "/"
    value = value.split("?")[0].split("#")[0]
    if not value.startswith("/"):
        value = "/" + value
    if ".." in value or "\n" in value:
        return "/"
    return value[:120]


def _js_str(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _patch_object_keys(block: str, updates: dict) -> tuple[str, bool]:
    changed = False
    text = block
    for key in BRAND_KEYS:
        raw = updates.get(key)
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        if not value or len(value) > 80:
            continue
        if key in COLOR_KEYS and not re.fullmatch(r"#[0-9A-Fa-f]{3,8}", value):
            continue
        pattern = rf"({re.escape(key)}:\s*)(?:'[^']*'|\"[^\"]*\")"
        next_text, count = re.subn(pattern, rf"\g<1>{_js_str(value)}", text, count=1)
        if count:
            text = next_text
            changed = True
    return text, changed


def patch_brand_file(path: Path, updates: object) -> bool:
    from app.services.shop_edit_verify import brand_export_span

    if not path.is_file() or not isinstance(updates, dict):
        return False
    text = path.read_text(encoding="utf-8")
    span = brand_export_span(text)
    if span is None:
        next_text, changed = _patch_object_keys(text, updates)
        if changed:
            path.write_text(next_text, encoding="utf-8")
        return changed
    start, end = span
    block = text[start : end + 1]
    next_block, changed = _patch_object_keys(block, updates)
    if not changed:
        return False
    path.write_text(text[:start] + next_block + text[end + 1 :], encoding="utf-8")
    return True


HIDE_PRICES_CSS = 'html[data-hide-prices="1"] [data-price] {\n  display: none !important;\n}\n'
def _brand_vars_text(existing: str, colors: dict[str, str]) -> str:
    lines = existing if existing.strip() else ":root {\n}\n"
    if ":root {" not in lines:
        lines = ":root {\n}\n" + lines
    for key, value in colors.items():
        if key not in COLOR_KEYS or not re.fullmatch(r"#[0-9A-Fa-f]{3,8}", value.strip()):
            continue
        var = f"--brand-{key}"
        hex_v = value.strip()
        if re.search(rf"{re.escape(var)}\s*:", lines):
            lines = re.sub(
                rf"({re.escape(var)}\s*:\s*)#[0-9A-Fa-f]{{3,8}}",
                rf"\g<1>{hex_v}",
                lines,
                count=1,
            )
        else:
            lines = lines.replace(":root {", f":root {{\n  {var}: {hex_v};", 1)
    if "data-hide-prices" not in lines:
        lines = lines.rstrip() + "\n\n" + HIDE_PRICES_CSS
    if not lines.endswith("\n"):
        lines += "\n"
    return lines


def write_brand_vars(root: Path, colors: dict[str, str]) -> bool:
    if not colors:
        return False
    app_path = root / "app" / "brand-vars.css"
    public_path = root / "public" / "brand-vars.css"
    existing = ""
    for path in (public_path, app_path):
        if path.is_file():
            existing = path.read_text(encoding="utf-8")
            break
    text = _brand_vars_text(existing, colors)
    for path in (app_path, public_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return True


def write_storefront_flags(
    root: Path,
    *,
    hide_prices: bool | None = None,
    logo_fa: str | None = None,
    links: list | None = None,
) -> Path:
    path = root / "public" / "storefront-flags.json"
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    if hide_prices is not None:
        data["hidePrices"] = bool(hide_prices)
    if logo_fa is not None:
        data["logoFa"] = str(logo_fa)
    if links is not None:
        cleaned = []
        seen: set[str] = set()
        for item in links:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            label = str(item.get("label") or "").strip()[:40]
            if href not in NAV_HREFS or not label or href in seen:
                continue
            seen.add(href)
            cleaned.append({"label": label, "href": href})
        data["links"] = cleaned
    data.setdefault("hidePrices", False)
    data.setdefault("logoFa", "")
    data.setdefault("links", [{"label": "محصولات", "href": "/products"}])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _page_file(build_dir: Path, page: str) -> Path | None:
    if page == "/":
        path = build_dir / "app" / "page.tsx"
        return path if path.is_file() else None
    parts = [part for part in page.split("/") if part and part not in {".", ".."}]
    if not parts:
        return None
    path = build_dir.joinpath("app", *parts, "page.tsx")
    return path if path.is_file() else None


def _copy_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in (
        "lib/brand.ts",
        "lib/design-tokens.ts",
        "lib/products.ts",
        "lib/nav.ts",
        "app/brand-vars.css",
        "public/brand-vars.css",
        "public/storefront-flags.json",
        "public/catalog.json",
    ):
        path = root / rel
        if path.is_file():
            files.append(path)
    for folder in ("app", "components"):
        base = root / folder
        if base.is_dir():
            files.extend(path for path in base.rglob("*.tsx") if path.is_file())
    pages = root / "public" / "pages"
    if pages.is_dir():
        files.extend(path for path in pages.glob("*.json") if path.is_file())
    return files[:40]


def patch_selected_text(root: Path, target: str, new: str) -> bool:
    if not target or target == new or len(target) < 2 or len(new) > 80:
        return False
    changed = False
    wrapped = re.compile(rf"<([A-Za-z][\w.]*)([^>]*)>\s*{re.escape(target)}\s*</\1>")
    empty = re.compile(r"<([A-Za-z][\w.]*)([^>]*)>\s*</\1>")
    for path in _copy_files(root):
        text = path.read_text(encoding="utf-8")
        if target not in text:
            continue
        if new == "" and wrapped.search(text):
            next_text = wrapped.sub("", text, count=1)
        else:
            next_text = text.replace(target, new, 1)
        next_text = empty.sub("", next_text)
        if next_text != text:
            path.write_text(next_text, encoding="utf-8")
            changed = True
    return changed


def patch_page_file(build_dir: Path, page: str, replacements: object) -> bool:
    path = _page_file(build_dir, page)
    if path is None or not isinstance(replacements, list):
        return False
    text = path.read_text(encoding="utf-8")
    changed = False
    for item in replacements[:2]:
        if not isinstance(item, dict):
            continue
        find = str(item.get("find") or "")
        repl = str(item.get("replace") or "")
        if not find or len(find) < 2 or len(find) > 80 or len(repl) > 80:
            continue
        if find not in text:
            continue
        text = text.replace(find, repl, 1)
        changed = True
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def build_dir_for(shop: dict) -> Path | None:
    from app.services.shop_service import _read_job_file

    job = _read_job_file(str(shop.get("jobId") or ""))
    raw = str((job or {}).get("buildDir") or "")
    if not raw:
        slug = str(shop.get("slug") or "").strip()
        if slug:
            raw = str(settings.factory_script.resolve().parent.parent / "builds" / slug)
    path = Path(raw)
    return path if path.is_dir() else None


def has_runtime_overlay(root: Path | None) -> bool:
    if root is None or not root.is_dir():
        return False
    return (root / "lib" / "catalog.ts").is_file() or (root / "app" / "api" / "catalog" / "route.ts").is_file()


def has_runtime_chrome(root: Path | None) -> bool:
    if root is None or not root.is_dir():
        return False
    layout = root / "app" / "layout.tsx"
    header = root / "components" / "layout" / "Header.tsx"
    if not layout.is_file() or not header.is_file():
        return False
    try:
        layout_text = layout.read_text(encoding="utf-8")
        header_text = header.read_text(encoding="utf-8")
    except OSError:
        return False
    return "data-hide-prices" in layout_text and "data-nav-href" in header_text


def spawn_rebuild(job_id: str, shop: dict) -> None:
    from app.services.shop_service import _factory_env, _fastpath_root, _read_job_file, _save_shop

    job = _read_job_file(job_id)
    if job:
        job["status"] = "running"
        job["phases"] = list(job.get("phases") or [])
        job["phases"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": "revise"})
        path = _fastpath_root() / "jobs" / f"{job_id}.json"
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shop["status"] = "running"
    shop["error"] = ""
    _save_shop(shop)
    script = settings.factory_script
    log = _fastpath_root() / "logs" / f"{job_id}-edit.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as handle:
        subprocess.Popen(
            [sys.executable, str(script), "revise", "--job-id", job_id, "--rebuild-only"],
            cwd=str(script.parent.parent),
            env=_factory_env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def safe_view_target(raw: str) -> str:
    value = " ".join((raw or "").split())
    if "\n" in value or ".." in value:
        return ""
    return value[:80]


def snapshot_edit_files(root: Path, dest_name: str = PREV_DIR) -> None:
    dest = root / dest_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    skip = {PREV_DIR, FRAME_DIR}
    for path in _copy_files(root):
        rel = path.relative_to(root)
        if rel.parts[0] in skip or str(rel.parts[0]).startswith(".sozan-"):
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(path.read_bytes())


def adopt_edit_frame(root: Path) -> None:
    src = root / FRAME_DIR
    dest = root / PREV_DIR
    if not src.is_dir():
        return
    if dest.exists():
        shutil.rmtree(dest)
    src.rename(dest)


def _restore_frame(root: Path) -> None:
    frame = root / FRAME_DIR
    if not frame.is_dir():
        return
    for path in frame.rglob("*"):
        if not path.is_file():
            continue
        target = root / path.relative_to(frame)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    shutil.rmtree(frame)


def restore_edit_files(root: Path, dest_name: str = PREV_DIR) -> bool:
    dest = root / dest_name
    if not dest.is_dir():
        return False
    changed = False
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        target = root / path.relative_to(dest)
        new = path.read_bytes()
        old = target.read_bytes() if target.is_file() else b""
        if old == new:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new)
        changed = True
    return changed


def named_color_updates(prompt: str) -> dict[str, str]:
    text = prompt or ""
    found = ""
    for name, hex_value in NAMED_COLORS.items():
        if name in text:
            found = hex_value
            break
    if not found:
        return {}
    if "پس‌زمینه" in text or "پس زمینه" in text:
        return {"background": found}
    if "اکسنت" in text or "تاکید" in text:
        return {"accent": found}
    return {"primary": found, "accent": found}


def write_intent(prompt: str) -> str:
    match = WRITE_RE.match((prompt or "").strip())
    if not match:
        return ""
    return match.group(1).strip()


def wants_revert(prompt: str) -> bool:
    return bool(REVERT_RE.search(prompt or ""))


def wants_hero_image(prompt: str) -> bool:
    text = prompt or ""
    colors = named_color_updates(text)
    if colors and "تصویر" not in text and "عکس" not in text:
        return False
    return bool(HERO_IMAGE_RE.search(text))


def wants_delete_selected(prompt: str) -> bool:
    return bool(DELETE_TEXT_RE.search(prompt or ""))


def looks_like_foreign_payload(prompt: str) -> bool:
    return bool(FOREIGN_PAYLOAD_RE.search(prompt or ""))


def hero_scene_prompt(shop: dict, prompt: str) -> str:
    blob = f"{prompt} {shop.get('storeName') or ''} {shop.get('slug') or ''}"
    if any(key in blob for key in ("جواهر", "طلا", "الماس", "joahr", "jewelry")):
        return (
            "cinematic luxury jewelry atelier hero background, gold rings diamonds and pearls "
            "on dark walnut and cream marble, warm copper light, empty boutique, "
            "no people, no hands, no faces, no text, no logos"
        )
    if any(key in blob for key in ("زعفران", "ادویه", "saffron", "قائنات")):
        return (
            "cinematic saffron harvest hero, crimson threads and spice bowls on rustic wood, "
            "warm rural light, empty table, no people, no hands, no text, no logos"
        )
    return (
        "cinematic storefront hero background, product still life on a clean studio surface, "
        "soft directional light, empty shop, no people, no text, no logos"
    )


def fetch_image_png(prompt: str, *, width: int = 1280, height: int = 720) -> bytes:
    from app.services.image_provider_service import generate_still

    return generate_still(prompt, width=width, height=height)


def runtime_shop_page_source(kind: str) -> str:
    return (
        "import { notFound } from 'next/navigation'\n"
        "import { readShopPage } from '@/lib/shop-pages'\n\n"
        "export const dynamic = 'force-dynamic'\n\n"
        "export default function ShopPage() {\n"
        f"  const page = readShopPage('{kind}')\n"
        "  if (!page.enabled) notFound()\n"
        "  return (\n"
        "    <div className=\"container mx-auto px-4 py-10\">\n"
        "      <h1 className=\"mb-4 text-3xl font-bold\">{page.title}</h1>\n"
        "      <p className=\"whitespace-pre-wrap\">{page.body}</p>\n"
        "    </div>\n"
        "  )\n"
        "}\n"
    )


PAGE_TEMPLATES = {kind: runtime_shop_page_source(kind) for kind in PAGE_KINDS}


def _ts_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _product_images_by_title(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for chunk in re.findall(r"\{[^{}]*\}", text or ""):
        title = re.search(r'["\']?title["\']?\s*:\s*["\']([^"\']+)["\']', chunk)
        image = re.search(r'["\']?image["\']?\s*:\s*["\']([^"\']+)["\']', chunk)
        if title and image:
            found[title.group(1)] = image.group(1)
    return found


def replace_exported_ts_array(text: str, decl: str, body: str) -> str | None:
    """Replace `export const X: T[] = [ ... ]` using bracket depth, not the first `]`.

    Factory catalogs put `images: [...]` inside the first product; a non-greedy
    regex stops there and leaves the rest of the array as a syntax error. Removing
    that scan would eat live catalog edits on the next add/remove.
    """
    start = text.find(decl)
    if start < 0:
        return None
    bracket = text.find("[", start + len(decl) - 1)
    if bracket < 0:
        return None
    depth = 0
    quote = ""
    escape = False
    for index in range(bracket, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "`"}:
            quote = char
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                while end < len(text) and text[end].isspace():
                    end += 1
                rest = text[end:]
                # A prior regex splice can leave `, { ... }]` after the first
                # closed array; nothing valid lives between this export and the
                # next one, so drop that junk instead of keeping a syntax error.
                if rest and not rest.startswith("export "):
                    nxt = rest.find("\nexport ")
                    rest = rest[nxt + 1 :] if nxt >= 0 else ""
                return text[:start] + body + rest
    return None


def write_catalog_json(root: Path, products: list[dict]) -> Path:
    prior: dict[str, str] = {}
    catalog_path = root / "public" / "catalog.json"
    if catalog_path.is_file():
        try:
            loaded = json.loads(catalog_path.read_text(encoding="utf-8"))
            rows = loaded.get("products") if isinstance(loaded, dict) else []
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and row.get("title"):
                        prior[str(row.get("title"))] = str(row.get("image") or "")
        except json.JSONDecodeError:
            prior = {}
    ts_path = root / "lib" / "products.ts"
    if ts_path.is_file() and "export const products" in ts_path.read_text(encoding="utf-8"):
        prior.update(_product_images_by_title(ts_path.read_text(encoding="utf-8")))
    items: list[dict] = []
    for index, row in enumerate(products, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        image = str(row.get("image") or "").strip()
        if not image or image == "/images/hero.png":
            image = prior.get(title) or image
        if not image:
            image = "/images/hero.png"
        item = {
            "id": str(row.get("id") or index),
            "title": title,
            "description": str(row.get("description") or title)[:400],
            "price": int(row.get("price") or 0),
            "category": str(row.get("category") or "goods"),
            "categoryFa": str(row.get("categoryFa") or row.get("category") or "کالا"),
            "image": image,
        }
        for key in ("discount", "subcategory", "subcategoryFa", "images", "priceLabel", "specs"):
            value = row.get(key)
            if value not in (None, "", []):
                item[key] = value
        items.append(item)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps({"products": items}, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog_path


def sync_products_ts(root: Path, products: list[dict]) -> bool:
    write_catalog_json(root, products)
    path = root / "lib" / "products.ts"
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8")
    if "readCatalog" in text or "export const products" not in text:
        return True
    decl = "export const products: Product[] ="
    prior = _product_images_by_title(text)
    items: list[str] = []
    for index, row in enumerate(products, start=1):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        image = str(row.get("image") or "").strip()
        if not image or image == "/images/hero.png":
            image = prior.get(title) or image
        if not image:
            image = "/images/hero.png"
        item = {
            "id": str(row.get("id") or index),
            "title": title,
            "description": str(row.get("description") or title)[:400],
            "price": int(row.get("price") or 0),
            "category": str(row.get("category") or "goods"),
            "categoryFa": str(row.get("categoryFa") or "کالا"),
            "image": image,
        }
        items.append("  " + json.dumps(item, ensure_ascii=False, indent=2).replace("\n", "\n  "))
    body = "export const products: Product[] = [\n" + ",\n".join(items) + "\n]\n"
    next_text = replace_exported_ts_array(text, decl, body)
    if next_text is not None:
        path.write_text(next_text, encoding="utf-8")
    return True


def read_nav_file(root: Path) -> dict:
    path = root / "lib" / "nav.ts"
    if not path.is_file():
        return {"logoFa": "", "links": [{"label": "دفتر کالا", "href": "/products"}]}
    text = path.read_text(encoding="utf-8")
    from app.services.shop_edit_verify import nav_links, nav_logo

    links = [{"label": label, "href": href} for label, href in nav_links(text)]
    return {"logoFa": nav_logo(text), "links": links or [{"label": "دفتر کالا", "href": "/products"}]}


def write_nav_file(root: Path, nav: dict) -> bool:
    links = nav.get("links") if isinstance(nav.get("links"), list) else []
    cleaned = []
    seen = set()
    for item in links:
        if not isinstance(item, dict):
            continue
        href = str(item.get("href") or "").strip()
        label = str(item.get("label") or "").strip()[:40]
        if href not in NAV_HREFS:
            continue
        if not label or href in seen:
            continue
        seen.add(href)
        cleaned.append({"label": label, "href": href})
    logo = str(nav.get("logoFa") or "").strip()[:40]
    lines = ["export const nav = {", f"  logoFa: {_ts_str(logo)},", "  links: ["]
    for item in cleaned:
        lines.append(f"    {{ label: {_ts_str(item['label'])}, href: {_ts_str(item['href'])} }},")
    lines.append("  ],")
    lines.append("} as const")
    lines.append("")
    path = root / "lib" / "nav.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _inject_header_links(root, cleaned)
    return True


def _inject_header_links(root: Path, links: list[dict]) -> None:
    header = root / "components" / "layout" / "Header.tsx"
    if not header.is_file():
        return
    text = header.read_text(encoding="utf-8")
    if "extraLinks" in text or "data-nav-href" in text:
        return
    for item in links:
        href = item["href"]
        label = item["label"]
        if href in {"/", "/products", "/cart"}:
            continue
        if href in text:
            continue
        needle = '<Link href="/products">'
        extra = f'<Link href="{href}">{label}</Link>\n          {needle}'
        if needle in text:
            text = text.replace(needle, extra, 1)
    header.write_text(text, encoding="utf-8")


def write_shop_page_json(root: Path, kind: str, *, title: str, body: str, enabled: bool = True) -> Path:
    path = root / "public" / "pages" / f"{kind}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"enabled": enabled, "title": title, "body": body}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def create_shop_page(root: Path, kind: str, *, title: str = "", body: str = "") -> bool:
    template = PAGE_TEMPLATES.get(kind)
    if not template:
        return False
    path = root / "app" / kind / "page.tsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "readShopPage" not in current:
        path.write_text(template, encoding="utf-8")
    from app.services.shop_intent_service import PAGE_LABELS

    label = title or PAGE_LABELS.get(kind) or kind
    write_shop_page_json(root, kind, title=label, body=body or label, enabled=True)
    return True


def patch_page_heading(root: Path, page: str, heading: str) -> bool:
    path = _page_file(root, page)
    if path is None or not heading:
        return False
    text = path.read_text(encoding="utf-8")
    next_text, count = re.subn(
        r"(<h1[^>]*>)([^<]*)(</h1>)",
        rf"\g<1>{heading}\g<3>",
        text,
        count=1,
    )
    if not count:
        return False
    path.write_text(next_text, encoding="utf-8")
    return True


async def fetch_hero_png(prompt: str) -> bytes:
    return fetch_image_png(prompt, width=1280, height=720)


def publish_shop_runtime(shop: dict, root: Path, rels: list[str]) -> None:
    from app.services.shop_service import PROTECTED_SHOP_SLUGS

    slug = str(shop.get("slug") or "").strip()
    if not slug or slug in PROTECTED_SHOP_SLUGS:
        return
    if not has_runtime_overlay(root):
        return
    parents = sorted({str(Path(rel).parent) for rel in rels if rel.startswith("public/") and "/" in rel[7:]})
    for dest in parents:
        subprocess.run(
            ["docker", "exec", f"sozan-{slug}", "mkdir", "-p", f"/app/{dest}"],
            check=False,
            timeout=15,
            capture_output=True,
            text=True,
        )
    for rel in rels:
        if not rel.startswith("public/"):
            continue
        src = root / rel
        if not src.is_file():
            continue
        copied = subprocess.run(
            ["docker", "cp", str(src), f"sozan-{slug}:/app/{rel}"],
            check=False,
            timeout=30,
            capture_output=True,
            text=True,
        )
        if copied.returncode != 0:
            from app.services.observe_client import emit_later

            emit_later(
                kind="edit",
                surface="shop",
                title="docker-cp-failed",
                status="failed",
                payload={"code": copied.returncode, "stderr": (copied.stderr or "")[-400:], "file": rel},
            )


def publish_shop_hero(shop: dict, png: Path) -> None:
    slug = str(shop.get("slug") or "").strip()
    if not slug or not png.is_file():
        return
    from app.services.shop_service import PROTECTED_SHOP_SLUGS

    if slug in PROTECTED_SHOP_SLUGS:
        return
    subprocess.run(
        ["docker", "cp", str(png), f"sozan-{slug}:/app/public/images/hero.png"],
        check=False,
        timeout=30,
        capture_output=True,
    )


async def apply_hero_image(shop: dict, root: Path, prompt: str) -> dict:
    png = fetch_image_png(hero_scene_prompt(shop, prompt), width=1280, height=720)
    if not png:
        return {
            "ok": True,
            "patched": False,
            "reply": "ساخت تصویر الان ممکن نشد. پیام را دوباره بفرست.",
        }
    dest = root / "public" / "images" / "hero.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)
    publish_shop_hero(shop, dest)
    return {
        "ok": True,
        "patched": True,
        "reply": "تصویر پس‌زمینه ساخته شد. در کادر دیده می‌شود.",
        "preview": _preview_payload(reload=True),
    }


def spoken_reply(prompt: str, reply: str, patched: bool, kind: str, detail: str = "") -> str:
    text = (reply or "").strip()
    compact = re.sub(r"\s+", "", text)
    prompt_compact = re.sub(r"\s+", "", prompt or "")
    too_thin = (not text) or len(text) < 12 or compact == prompt_compact or (detail and text == detail)
    if not patched:
        if too_thin or SUCCESS_CLAIM_RE.search(text):
            return "این تغییر روی این صفحه پیدا نشد. المان را در پیش‌نمایش لمس کن یا دقیق‌تر بگو."
        return text
    if kind == "revert":
        return "به ویرایش قبلی برگشت."
    if too_thin:
        if kind == "color":
            return "رنگ‌های اصلی فروشگاه عوض شد."
        if kind == "write" and detail:
            return f"متن به «{detail}» تغییر کرد."
        return "تغییر روی همین صفحه اعمال شد."
    return text


def _reply_for_verify(action: dict, verified: dict, *, frame_only: bool = False) -> str:
    kind = str(action.get("type") or "")
    ok = bool(verified.get("ok"))
    if kind == "set_colors":
        text = "رنگ فروشگاه عوض شد." if ok else "رنگ سایت عوض نشد."
    elif kind == "set_brand":
        fields = action.get("fields") if isinstance(action.get("fields"), dict) else {}
        if "ctaLabelFa" in fields:
            text = f"متن دکمه به «{fields['ctaLabelFa']}» تغییر کرد." if ok else "متن دکمه عوض نشد."
        elif "name" in fields:
            text = f"نام فروشگاه «{fields['name']}» شد." if ok else "نام فروشگاه عوض نشد."
        else:
            text = "متن برند عوض شد." if ok else "متن برند عوض نشد."
    elif kind == "replace_text":
        text = f"متن به «{action.get('replace')}» تغییر کرد." if ok else "تیتر روی این صفحه پیدا نشد."
    elif kind == "delete_text":
        target = action.get("target") or ""
        text = f"متن «{target}» از این صفحه حذف شد." if ok else f"متن «{target}» حذف نشد."
    elif kind == "hero_image":
        text = "تصویر پس‌زمینه ساخته شد. در کادر دیده می‌شود." if ok else "ساخت تصویر الان ممکن نشد. پیام را دوباره بفرست."
    elif kind == "hide_prices":
        text = "قیمت روی سایت نشان داده نمی‌شود." if ok else "پنهان کردن قیمت روی سایت دیده نشد."
    elif kind == "show_prices":
        text = "قیمت روی سایت نشان داده می‌شود." if ok else "نمایش قیمت روی سایت دیده نشد."
    elif kind == "catalog_from_page":
        text = str(action.get("reply") or "")
    elif kind == "add_product":
        title = action.get("title") or "کالا"
        text = f"«{title}» به کاتالوگ اضافه شد." if ok else "کالا به کاتالوگ اضافه نشد."
    elif kind == "remove_product":
        title = action.get("title") or "کالا"
        text = f"«{title}» از کاتالوگ حذف شد." if ok else "کالا از کاتالوگ حذف نشد."
    elif kind == "set_header":
        text = "متن هدر عوض شد." if ok else "هدر روی سایت عوض نشد."
    elif kind == "add_nav_link":
        text = f"لینک «{action.get('label')}» در منو آمد." if ok else "لینک منو ثبت نشد."
    elif kind == "create_page":
        label = action.get("label") or "صفحه"
        text = f"صفحهٔ {label} در سایت باز است." if ok else "صفحه ساخته نشد."
    elif kind == "revert":
        text = "به ویرایش قبلی برگشت." if ok else "ویرایش قبلی برای برگشت ذخیره نشده."
    elif kind == "reject_foreign":
        text = "این پیام ویرایش فروشگاه نیست."
    elif kind == "ask_clarify":
        text = str(action.get("reply") or "دقیق‌تر بگو.")
    elif kind == "greet":
        text = "فروشگاه زنده‌ست. صفحه را همین‌جا ببین و بگو چه عوض شود."
    else:
        text = "تغییر روی همین صفحه اعمال شد." if ok else "این تغییر روی این صفحه پیدا نشد. المان را در پیش‌نمایش لمس کن یا دقیق‌تر بگو."
    if ok and frame_only and "کادر" not in text:
        text = f"{text} تغییر در کادر است؛ وقتی آماده بودی بیلد بزن."
    return text


def _execute_action(shop: dict, root: Path, action: dict, view_path: str) -> dict:
    from app.services import storefront_service
    from app.services.shop_intent_service import PAGE_LABELS
    from app.services.shop_service import _save_shop

    kind = str(action.get("type") or "")
    files: list[str] = []
    preview: dict = {}
    if kind == "set_colors":
        colors = action.get("colors") if isinstance(action.get("colors"), dict) else {}
        brand_path = root / "lib" / "brand.ts"
        patch_brand_file(brand_path, colors)
        write_brand_vars(root, {key: str(value) for key, value in colors.items() if isinstance(value, str)})
        files = ["lib/brand.ts", "app/brand-vars.css", "public/brand-vars.css"]
        preview = _preview_payload(colors=_color_preview(colors), reload=True)
    elif kind == "set_brand":
        fields = action.get("fields") if isinstance(action.get("fields"), dict) else {}
        patch_brand_file(root / "lib" / "brand.ts", fields)
        files = ["lib/brand.ts"]
        if "name" in fields:
            preview = _preview_payload(find=str(shop.get("brand") or ""), replace=str(fields.get("name") or ""))
    elif kind == "replace_text":
        find = str(action.get("find") or "")
        replace = str(action.get("replace") or "")
        if action.get("heading"):
            patched = patch_page_heading(root, view_path or "/products", replace)
            files = [f"app{(view_path or '/products').rstrip('/')}/page.tsx"]
            preview = _preview_payload(reload=True) if patched else {}
        elif find:
            patched = patch_selected_text(root, find, replace)
            if not patched:
                patch_page_file(root, view_path or "/", [{"find": find, "replace": replace}])
            files = ["app/page.tsx", "lib/brand.ts"]
            preview = _preview_payload(find=find, replace=replace)
    elif kind == "delete_text":
        target = str(action.get("target") or "")
        patch_selected_text(root, target, "")
        files = ["app/page.tsx"]
        preview = _preview_payload(reload=True)
    elif kind == "hero_image":
        return {"kind": "hero_image", "files": ["public/images/hero.png"], "preview": _preview_payload(reload=True)}
    elif kind == "hide_prices":
        shop["hidePrices"] = True
        _save_shop(shop)
        write_storefront_flags(root, hide_prices=True)
        files = ["public/storefront-flags.json"]
        preview = _preview_payload(reload=True)
    elif kind == "show_prices":
        shop["hidePrices"] = False
        _save_shop(shop)
        write_storefront_flags(root, hide_prices=False)
        files = ["public/storefront-flags.json"]
        preview = _preview_payload(reload=True)
    elif kind == "catalog_from_page":
        from app.services.shop_service import _catalog_from_page_reply

        action["reply"] = _catalog_from_page_reply()
        files = []
    elif kind == "add_product":
        title = str(action.get("title") or "").strip()
        storefront_service.add_product(
            title=title,
            price=int(action.get("price") or 0),
            stock=1,
            sku="chat",
            source="chat",
            category="کالا",
        )
        from app.services import catalog_sync_service

        catalog_sync_service.sync_live()
        files = ["public/catalog.json"]
        preview = _preview_payload(reload=True)
    elif kind == "remove_product":
        title = str(action.get("title") or "").strip()
        storefront_service.remove_product_by_title(title)
        from app.services import catalog_sync_service

        catalog_sync_service.sync_live()
        files = ["public/catalog.json"]
        preview = _preview_payload(reload=True)
    elif kind == "set_header":
        nav = read_nav_file(root)
        nav["logoFa"] = str(action.get("logoFa") or "")
        write_nav_file(root, nav)
        write_storefront_flags(root, logo_fa=str(nav["logoFa"]))
        files = ["lib/nav.ts", "components/layout/Header.tsx", "public/storefront-flags.json"]
        preview = _preview_payload(reload=True)
    elif kind == "add_nav_link":
        nav = read_nav_file(root)
        links = list(nav.get("links") or [])
        links.append({"label": action.get("label"), "href": action.get("href")})
        nav["links"] = links
        write_nav_file(root, nav)
        write_storefront_flags(root, links=links)
        files = ["lib/nav.ts", "components/layout/Header.tsx", "public/storefront-flags.json"]
        preview = _preview_payload(reload=True)
    elif kind == "create_page":
        page_kind = str(action.get("kind") or "")
        from app.services.shop_intent_service import PAGE_LABELS

        label = str(action.get("label") or PAGE_LABELS.get(page_kind) or page_kind)
        create_shop_page(root, page_kind, title=label, body=label)
        nav = read_nav_file(root)
        links = list(nav.get("links") or [])
        href = f"/{page_kind}"
        if not any(str(item.get("href")) == href for item in links if isinstance(item, dict)):
            links.append({"label": label, "href": href})
        nav["links"] = links
        write_nav_file(root, nav)
        write_storefront_flags(root, logo_fa=str(nav.get("logoFa") or ""), links=links)
        files = [f"public/pages/{page_kind}.json", "public/storefront-flags.json", f"app/{page_kind}/page.tsx"]
        preview = {"viewPath": f"/{page_kind}"}
    elif kind == "revert":
        files = ["lib/brand.ts"]
        preview = _preview_payload(reset=True)
    return {"files": files, "preview": preview}


def _normalize_llm_actions(raw: object, target: str) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if kind not in LLM_ACTION_TYPES:
            continue
        if kind == "create_page" and str(item.get("kind") or "") not in PAGE_KINDS:
            out.append({"type": "ask_clarify", "reply": "کدام صفحه را بسازم: درباره ما، تماس، داستان برند، یا پرسش‌های متداول؟"})
            continue
        if kind == "add_nav_link" and str(item.get("href") or "") not in NAV_HREFS:
            continue
        if kind == "replace_text" and target and not item.get("find"):
            item = {**item, "find": target}
        if kind == "delete_text" and target and not item.get("target"):
            item = {**item, "target": target}
        out.append(item)
    return out


def _trace_hashes(root: Path, files: list[str]) -> list[dict]:
    from app.services.shop_edit_verify import file_hash

    rows: list[dict] = []
    for rel in files[:12]:
        rows.append({"path": rel, "hash": file_hash(root / rel)})
    return rows


async def _run_action_list(
    shop: dict,
    root: Path,
    actions: list[dict],
    *,
    prompt: str,
    page: str,
) -> dict:
    from app.services import shop_workspace_service, storefront_service
    from app.services.shop_edit_verify import RUNTIME_VERIFY_KINDS, fetch_shop_runtime, verify_action
    from app.services.shop_service import _save_shop

    turn_id = str(uuid4())
    expected_rev = int(shop.get("siteRevision") or 0)
    from app.services.shop_service import _shop as _fresh_shop

    fresh = _fresh_shop()
    if int(fresh.get("siteRevision") or 0) > expected_rev:
        return {
            "ok": False,
            "patched": False,
            "rolledBack": True,
            "needsRebuild": False,
            "reply": "سایت تازه ساخته شد. دستور را دوباره بفرست.",
            "preview": {},
        }
    lines: list[str] = []
    previews: dict = {}
    any_ok = False
    any_fail = False
    needs_rebuild = False
    created_ok: set[str] = set()
    pending_before = int(shop.get("pendingBuild") or 0)
    hero = root / "public" / "images" / "hero.png"
    hero_mtime = hero.stat().st_mtime if hero.is_file() else None
    turn_snap = f".sozan-turn-{turn_id[:8]}"
    snapshot_edit_files(root, turn_snap)
    overlay = has_runtime_overlay(root)
    chrome = has_runtime_chrome(root)
    mutating = {
        "set_colors",
        "set_brand",
        "replace_text",
        "delete_text",
        "hero_image",
        "add_product",
        "remove_product",
        "set_header",
        "add_nav_link",
        "create_page",
        "hide_prices",
        "show_prices",
        "catalog_from_page",
    }
    for index, action in enumerate(actions):
        depends = str(action.get("depends_on") or "")
        if depends.startswith("create_page:") and depends.split(":", 1)[-1] not in created_ok:
            continue
        kind = str(action.get("type") or "")
        hide_before = bool(shop.get("hidePrices"))
        files: list[str] = []
        preview: dict = {}
        runtime: dict = {}
        live = overlay if kind not in CHROME_LIVE_KINDS else overlay and chrome
        if kind == "hero_image":
            result = await apply_hero_image(shop, root, prompt)
            files = ["public/images/hero.png"]
            preview = result.get("preview") or {"reload": True}
            verified = verify_action(
                action=action,
                root=root,
                shop=shop,
                files_touched=files,
                hero_mtime_before=hero_mtime,
            )
        elif kind == "revert":
            patched = restore_edit_files(root, PREV_DIR)
            files = ["lib/brand.ts", "public/brand-vars.css", "public/storefront-flags.json", "public/catalog.json"]
            preview = _preview_payload(reset=True)
            publish_shop_runtime(shop, root, files)
            verified = verify_action(action=action, root=root, shop=shop, files_touched=files)
            verified["ok"] = bool(patched)
        else:
            executed = _execute_action(shop, root, action, page)
            files = executed.get("files") or []
            preview = executed.get("preview") or {}
            if kind in RUNTIME_VERIFY_KINDS and live:
                publish_shop_runtime(shop, root, files)
                page_path = f"/{action.get('kind')}" if kind == "create_page" else ""
                runtime = fetch_shop_runtime(shop, page_path=page_path)
            products = storefront_service.list_products().get("products") or []
            verified = verify_action(
                action=action,
                root=root,
                shop=shop,
                products=products,
                files_touched=files,
                pending_before=pending_before,
                pending_after=int(shop.get("pendingBuild") or 0),
                runtime=runtime,
                require_live=live,
            )
            if kind == "catalog_from_page":
                reply_line = str(action.get("reply") or "")
                verified["ok"] = "هنوز پیجی" not in reply_line and bool(reply_line)
        reply_line = (
            str(action.get("reply") or "")
            if kind == "catalog_from_page"
            else _reply_for_verify(action, verified, frame_only=not live)
        )
        shop_workspace_service.record_trace(
            prompt=prompt,
            action=action,
            verify=verified,
            reply=reply_line,
            files=files,
            patched=bool(verified.get("ok")),
            turn_id=turn_id,
            action_index=index,
            hashes=_trace_hashes(root, files),
            route=str(action.get("type") or ""),
        )
        lines.append(reply_line)
        if verified.get("ok"):
            any_ok = True
            if kind in mutating:
                if kind not in RUNTIME_VERIFY_KINDS or not live:
                    needs_rebuild = True
            previews.update(preview)
            if kind == "create_page":
                created_ok.add(str(action.get("kind") or ""))
        else:
            any_fail = True
            restore_edit_files(root, turn_snap)
            shop["hidePrices"] = hide_before
            _save_shop(shop)
            break
    reply = " ".join(line for line in lines if line).strip()
    if any_fail:
        restore_edit_files(root, turn_snap)
        shop["pendingBuild"] = pending_before
        _save_shop(shop)
        return {
            "ok": True,
            "patched": False,
            "reply": reply or "این تغییر کامل اعمال نشد و برگردانده شد.",
            "preview": {},
            "rolledBack": True,
        }
    if any_ok:
        if not any(str(item.get("type") or "") == "revert" for item in actions):
            prev = root / PREV_DIR
            snap = root / turn_snap
            if snap.is_dir():
                if prev.exists():
                    shutil.rmtree(prev)
                shutil.copytree(snap, prev)
        return _finish_edit(
            shop,
            reply,
            True,
            previews,
            prompt=prompt,
            root=root,
            needs_rebuild=needs_rebuild,
        )
    return {
        "ok": True,
        "patched": False,
        "reply": reply or "این تغییر روی این صفحه پیدا نشد. المان را در پیش‌نمایش لمس کن یا دقیق‌تر بگو.",
        "preview": {},
    }


async def apply_live_edit(
    shop: dict,
    prompt: str,
    view_path: str,
    view_target: str = "",
    classified: dict | None = None,
) -> dict:
    from app.services import shop_intent_service, shop_workspace_service
    from app.services.shop_edit_verify import verify_action

    page = safe_view_path(view_path)
    target = safe_view_target(view_target)
    root = build_dir_for(shop)
    if root is None:
        return {"ok": False, "patched": False, "reply": "پوشهٔ سایت پیدا نشد. اگر لازم است بگو دوباره بساز."}
    if classified and classified.get("actions"):
        actions = list(classified.get("actions") or [])
    else:
        actions = shop_intent_service.classify_actions(prompt, target, page)
    if not actions:
        actions = [{"type": "edit_llm"}]
    if actions[0].get("type") == "reject_foreign":
        pending = int(shop.get("pendingBuild") or 0)
        verified = verify_action(
            action=actions[0],
            root=root,
            shop=shop,
            files_touched=[],
            pending_before=pending,
            pending_after=pending,
        )
        reply = _reply_for_verify(actions[0], verified)
        shop_workspace_service.record_trace(
            prompt=prompt,
            action=actions[0],
            verify=verified,
            reply=reply,
            files=[],
            patched=False,
            turn_id=str(uuid4()),
            action_index=0,
        )
        return {"ok": True, "patched": False, "reply": reply, "preview": {}}
    if actions[0].get("type") in {"greet", "ask_clarify"}:
        verified = verify_action(action=actions[0], root=root, shop=shop, files_touched=[])
        reply = _reply_for_verify(actions[0], verified)
        shop_workspace_service.record_trace(
            prompt=prompt,
            action=actions[0],
            verify=verified,
            reply=reply,
            files=[],
            patched=False,
            turn_id=str(uuid4()),
            action_index=0,
        )
        return {"ok": True, "patched": False, "reply": reply, "preview": {}}
    if actions[0].get("type") == "edit_llm":
        return await _apply_llm_edit(shop, prompt, page, target, root)
    return await _run_action_list(shop, root, actions, prompt=prompt, page=page)


async def _apply_llm_edit(shop: dict, prompt: str, page: str, target: str, root: Path) -> dict:
    from app.services import channel_scan_service, shop_workspace_service

    brand_path = root / "lib" / "brand.ts"
    excerpt = brand_path.read_text(encoding="utf-8")[:1800] if brand_path.is_file() else ""
    page_path = _page_file(root, page)
    page_excerpt = page_path.read_text(encoding="utf-8")[:1500] if page_path else ""
    folder = shop_workspace_service.instructions_block()
    parsed = await complete_json(
        EDIT_SYSTEM,
        (
            f"صفحه فعلی: {page}\nمتن اشاره‌شده: {target or '—'}\nدرخواست: {prompt}\n"
            f"{folder}\n"
            f"{channel_scan_service.brief_for_shop()}\nbrand.ts:\n{excerpt}\nصفحه:\n{page_excerpt}"
        ),
        surface="shop-edit",
    )
    llm_actions = _normalize_llm_actions(parsed.get("actions"), target)
    if llm_actions:
        return await _run_action_list(shop, root, llm_actions, prompt=prompt, page=page)
    return {
        "ok": True,
        "patched": False,
        "reply": "این تغییر روی این صفحه پیدا نشد. المان را در پیش‌نمایش لمس کن یا دقیق‌تر بگو.",
        "preview": {},
    }


def _color_preview(updates: object) -> dict[str, str]:
    if not isinstance(updates, dict):
        return {}
    out: dict[str, str] = {}
    for key in COLOR_KEYS:
        raw = updates.get(key)
        if isinstance(raw, str) and re.fullmatch(r"#[0-9A-Fa-f]{3,8}", raw.strip()):
            out[key] = raw.strip()
    return out


def _preview_payload(
    *,
    find: str = "",
    replace: str = "",
    colors: dict | None = None,
    reload: bool = False,
    reset: bool = False,
) -> dict:
    out: dict = {}
    if find and replace:
        out["find"] = find
        out["replace"] = replace
    if colors:
        out["colors"] = colors
    if reload:
        out["reload"] = True
    if reset:
        out["reset"] = True
    return out


def _finish_edit(
    shop: dict,
    reply: str,
    patched: bool,
    preview: dict | None = None,
    *,
    prompt: str = "",
    root: Path | None = None,
    needs_rebuild: bool = True,
) -> dict:
    from app.services.shop_service import _save_shop
    from app.services import shop_workspace_service

    if needs_rebuild:
        shop["pendingBuild"] = int(shop.get("pendingBuild") or 0) + 1
    shop["siteRevision"] = int(shop.get("siteRevision") or 0) + 1
    _save_shop(shop)
    shop_workspace_service.record_edit(prompt=prompt, reply=reply, patched=patched, root=root)
    return {
        "ok": True,
        "patched": True,
        "reply": reply,
        "preview": preview or {},
        "pendingBuild": int(shop.get("pendingBuild") or 0),
        "needsRebuild": needs_rebuild,
    }
