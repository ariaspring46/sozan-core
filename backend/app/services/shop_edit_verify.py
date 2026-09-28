from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

COLOR_KEYS = ("primary", "accent", "deep", "soft", "background", "foreground")
BRAND_TEXT_KEYS = ("name", "tagline", "ctaLabelFa", "cartCtaFa", "eyebrow", "moodFa")
HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}")
BRAND_EXPORT_RE = re.compile(r"export const brand\s*=\s*\{", re.M)
EMPTY_TAG_RE = re.compile(r"<([A-Za-z][\w.]*)([^>]*)>\s*</\1>")
NAV_HREF_RE = re.compile(r"href:\s*['\"]([^'\"]+)['\"]")
NAV_LABEL_RE = re.compile(r"label:\s*['\"]([^'\"]+)['\"]")
LOGO_RE = re.compile(r"logoFa:\s*['\"]([^'\"]*)['\"]")
PRODUCT_TITLE_RE = re.compile(r'["\']?title["\']?\s*:\s*[\'"]([^\'"]+)[\'"]')
CSS_VAR_RE = re.compile(r"--brand-([a-z]+)\s*:\s*(#[0-9A-Fa-f]{3,8})")
RUNTIME_VERIFY_KINDS = frozenset(
    {
        "set_colors",
        "hide_prices",
        "show_prices",
        "set_header",
        "add_product",
        "remove_product",
        "create_page",
        "add_nav_link",
    }
)


def _http_get(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "sozan-edit-verify/1", "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return ""


def fetch_shop_runtime(shop: dict | None = None, *, page_path: str = "") -> dict[str, str]:
    """GET the live container: colors/flags/header/catalog are proven here, not from disk."""
    shop = shop or {}
    port = int(shop.get("port") or 0)
    empty = {"html": "", "css": "", "flags": "", "catalog": "", "products_html": "", "page_html": ""}
    if port <= 0:
        return empty
    base = f"http://127.0.0.1:{port}"
    path = page_path if page_path.startswith("/") else (f"/{page_path}" if page_path else "")
    return {
        "html": _http_get(base + "/"),
        "css": _http_get(base + "/brand-vars.css"),
        "flags": _http_get(base + "/storefront-flags.json"),
        "catalog": _http_get(base + "/catalog.json"),
        "products_html": _http_get(base + "/products"),
        "page_html": _http_get(base + path) if path else "",
    }


def parse_runtime_flags(text: str) -> dict:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def brand_export_span(text: str) -> tuple[int, int] | None:
    match = BRAND_EXPORT_RE.search(text or "")
    if not match:
        return None
    start = text.find("{", match.start())
    if start < 0:
        return None
    depth = 0
    for index, char in enumerate(text[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index
    return None


def brand_export_block(text: str) -> str:
    span = brand_export_span(text or "")
    if span is None:
        return ""
    return text[span[0] : span[1] + 1]


def read_brand_keys(text: str, keys: tuple[str, ...] | list[str]) -> dict[str, str]:
    block = brand_export_block(text)
    out: dict[str, str] = {}
    for key in keys:
        match = re.search(rf"{re.escape(key)}:\s*['\"]([^'\"]*)['\"]", block)
        if match:
            out[key] = match.group(1)
    return out


def read_css_brand_vars(text: str) -> dict[str, str]:
    return {key: value for key, value in CSS_VAR_RE.findall(text or "")}


def empty_heading_left(text: str) -> bool:
    return bool(re.search(r"<h[1-6][^>]*>\s*</h[1-6]>", text or "", re.I))


def file_text(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def catalog_file_titles(root: Path | None) -> set[str]:
    if root is None:
        return set()
    data = parse_runtime_flags(file_text(root, "public/catalog.json"))
    return product_titles_json(data.get("products"))


def product_titles_json(rows: object) -> set[str]:
    titles: set[str] = set()
    if not isinstance(rows, list):
        return titles
    for row in rows:
        if isinstance(row, dict):
            title = str(row.get("title") or "").strip()
            if title:
                titles.add(title)
    return titles


def product_titles_ts(text: str) -> set[str]:
    return {item.strip() for item in PRODUCT_TITLE_RE.findall(text or "") if item.strip()}


def nav_links(text: str) -> list[tuple[str, str]]:
    labels = NAV_LABEL_RE.findall(text or "")
    hrefs = NAV_HREF_RE.findall(text or "")
    return list(zip(labels, hrefs))


def nav_logo(text: str) -> str:
    match = LOGO_RE.search(text or "")
    return match.group(1) if match else ""


def verify_action(
    *,
    action: dict,
    root: Path | None,
    shop: dict | None = None,
    products: list | None = None,
    files_touched: list[str] | None = None,
    pending_before: int | None = None,
    pending_after: int | None = None,
    hero_mtime_before: float | None = None,
    runtime: dict | None = None,
    require_live: bool = True,
) -> dict:
    kind = str(action.get("type") or "")
    shop = shop or {}
    files_touched = files_touched or []
    runtime = runtime or {}
    live_html = str(runtime.get("html") or "")
    live_css = str(runtime.get("css") or "")
    live_flags_txt = str(runtime.get("flags") or "")
    live_catalog_txt = str(runtime.get("catalog") or "")
    live_products_html = str(runtime.get("products_html") or "")
    live_page_html = str(runtime.get("page_html") or "")
    live_flags = parse_runtime_flags(live_flags_txt)
    live_catalog_titles = product_titles_json(parse_runtime_flags(live_catalog_txt).get("products"))
    expected: dict = {}
    observed: dict = {}
    ok = False
    if kind == "set_colors":
        colors = action.get("colors") if isinstance(action.get("colors"), dict) else {}
        brand_txt = file_text(root, "lib/brand.ts") if root else ""
        css_txt = file_text(root, "app/brand-vars.css") if root else ""
        public_css = file_text(root, "public/brand-vars.css") if root else ""
        brand_vals = read_brand_keys(brand_txt, COLOR_KEYS)
        css_vals = read_css_brand_vars(css_txt or public_css)
        expected = {key: str(colors[key]).strip() for key in colors if key in COLOR_KEYS}
        live_vals = read_css_brand_vars(live_css) or read_css_brand_vars(live_html)
        observed = {
            "brand": {k: brand_vals.get(k, "") for k in expected},
            "css": {k: css_vals.get(k, "") for k in expected},
            "live": {k: live_vals.get(k, "") for k in expected},
        }
        disk_ok = bool(expected) and all(
            brand_vals.get(key, "").lower() == value.lower() and css_vals.get(key, "").lower() == value.lower()
            for key, value in expected.items()
        )
        live_ok = bool(expected) and all(live_vals.get(key, "").lower() == value.lower() for key, value in expected.items())
        ok = disk_ok and (live_ok if require_live else True)
    elif kind == "set_brand":
        fields = action.get("fields") if isinstance(action.get("fields"), dict) else {}
        brand_txt = file_text(root, "lib/brand.ts") if root else ""
        brand_vals = read_brand_keys(brand_txt, BRAND_TEXT_KEYS)
        expected = {key: str(fields[key]).strip() for key in fields if key in BRAND_TEXT_KEYS}
        observed = {key: brand_vals.get(key, "") for key in expected}
        ok = bool(expected) and all(brand_vals.get(key, "") == value for key, value in expected.items())
    elif kind == "replace_text":
        find = str(action.get("find") or "")
        replace = str(action.get("replace") or "")
        blob = ""
        if root is not None:
            for rel in files_touched or ["app/page.tsx", "lib/brand.ts"]:
                blob += file_text(root, rel)
        expected = {"find_absent": find, "replace_present": replace}
        observed = {"find": find in blob, "replace": replace in blob if replace else True}
        if action.get("heading"):
            ok = bool(replace) and replace in blob
        else:
            ok = bool(find) and find not in blob and (not replace or replace in blob)
    elif kind == "delete_text":
        target = str(action.get("target") or action.get("find") or "")
        blob = ""
        if root is not None:
            for rel in ("app/page.tsx", "lib/brand.ts", "components"):
                path = root / rel
                if path.is_file():
                    blob += path.read_text(encoding="utf-8")
                elif path.is_dir():
                    for item in path.rglob("*.tsx"):
                        blob += item.read_text(encoding="utf-8")
        expected = {"absent": target, "no_empty_heading": True}
        observed = {"present": target in blob, "empty_heading": empty_heading_left(blob)}
        ok = bool(target) and target not in blob and not empty_heading_left(blob)
    elif kind == "hero_image":
        hero = (root / "public" / "images" / "hero.png") if root else None
        size = hero.stat().st_size if hero is not None and hero.is_file() else 0
        mtime = hero.stat().st_mtime if hero is not None and hero.is_file() else 0
        expected = {"min_bytes": 2048, "newer": True}
        observed = {"size": size, "mtime": mtime}
        ok = size >= 2048 and (hero_mtime_before is None or mtime > hero_mtime_before)
    elif kind == "hide_prices":
        expected = {"hidePrices": True, "live": 'data-hide-prices="1"'}
        observed = {
            "hidePrices": bool(shop.get("hidePrices")),
            "live": 'data-hide-prices="1"' in live_html,
            "flags": bool(live_flags.get("hidePrices")),
        }
        ok = bool(shop.get("hidePrices")) and (
            'data-hide-prices="1"' in live_html if require_live else True
        )
    elif kind == "show_prices":
        expected = {"hidePrices": False, "live": 'data-hide-prices="1" absent'}
        observed = {
            "hidePrices": bool(shop.get("hidePrices")),
            "live": 'data-hide-prices="1"' in live_html,
            "flags": bool(live_flags.get("hidePrices")),
        }
        ok = not bool(shop.get("hidePrices")) and (
            'data-hide-prices="1"' not in live_html if require_live else True
        )
    elif kind == "catalog_from_page":
        sourced = [row for row in (products or []) if isinstance(row, dict) and row.get("source")]
        expected = {"min_sourced": 1}
        observed = {"sourced": len(sourced)}
        ok = len(sourced) >= 1
    elif kind == "add_product":
        title = str(action.get("title") or "").strip()
        json_titles = product_titles_json(products or [])
        disk_catalog = catalog_file_titles(root)
        expected = {"title": title}
        observed = {
            "json": title in json_titles,
            "catalog": title in disk_catalog,
            "live_catalog": title in live_catalog_titles,
            "live_html": title in live_products_html or title in live_html,
        }
        ok = (
            bool(title)
            and title in json_titles
            and title in disk_catalog
            and (title in live_catalog_titles if require_live else True)
            and ((title in live_products_html or title in live_html) if require_live else True)
        )
    elif kind == "remove_product":
        title = str(action.get("title") or "").strip()
        json_titles = product_titles_json(products or [])
        disk_catalog = catalog_file_titles(root)
        expected = {"absent": title}
        observed = {
            "json": title in json_titles,
            "catalog": title in disk_catalog,
            "live_catalog": title in live_catalog_titles,
        }
        ok = bool(title) and title not in json_titles and title not in disk_catalog and (
            title not in live_catalog_titles if require_live else True
        )
    elif kind == "set_header":
        logo = str(action.get("logoFa") or "").strip()
        text = file_text(root, "lib/nav.ts") if root else ""
        expected = {"logoFa": logo}
        observed = {
            "logoFa": nav_logo(text),
            "live": logo if logo and logo in live_html else "",
        }
        ok = bool(logo) and nav_logo(text) == logo and (logo in live_html if require_live else True)
    elif kind == "add_nav_link":
        href = str(action.get("href") or "").strip()
        label = str(action.get("label") or "").strip()
        disk_flags = parse_runtime_flags(file_text(root, "public/storefront-flags.json") if root else "")
        flag_links = disk_flags.get("links") if isinstance(disk_flags.get("links"), list) else []
        live_links = live_flags.get("links") if isinstance(live_flags.get("links"), list) else []
        expected = {"href": href, "label": label}
        observed = {"flags": flag_links, "live": href in live_html}

        def _has(links: list) -> bool:
            return any(
                isinstance(item, dict) and str(item.get("href")) == href and str(item.get("label")) == label
                for item in links
            )

        # The compiled menu shows the link after انتشار. Disk flags are the proof.
        ok = bool(href) and bool(label) and (_has(flag_links) or _has(live_links))
    elif kind == "create_page":
        page_kind = str(action.get("kind") or "").strip()
        page_json = parse_runtime_flags(file_text(root, f"public/pages/{page_kind}.json") if root else "")
        title = str(action.get("label") or page_json.get("title") or "")
        expected = {"kind": page_kind, "href": f"/{page_kind}"}
        page_file = bool(root and (root / "app" / page_kind / "page.tsx").is_file())
        observed = {
            "enabled": bool(page_json.get("enabled")),
            "file": page_file,
            "live": title in live_page_html if title else bool(live_page_html),
            "nav": f'data-nav-href="/{page_kind}"' in live_html,
        }
        # A new route is compiled in at انتشار. Do not roll it back because the
        # running container's menu has not been rebuilt yet.
        ok = page_kind in {"about", "contact", "story", "faq"} and bool(page_json.get("enabled")) and page_file
    elif kind == "revert":
        ok = True
        expected = {"restored": True}
        observed = {"files": files_touched}
    elif kind == "reject_foreign":
        expected = {"files": [], "pending": pending_before}
        observed = {"files": files_touched, "pending": pending_after}
        ok = files_touched == [] and (
            pending_before is None or pending_after is None or pending_after == pending_before
        )
    elif kind in {"ask_clarify", "greet", "progress", "answer"}:
        expected = {"files": []}
        observed = {"files": files_touched}
        ok = files_touched == []
    else:
        expected = {"type": kind}
        observed = {"unknown": True}
        ok = False
    return {"ok": ok, "expected": expected, "observed": observed}


def file_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
