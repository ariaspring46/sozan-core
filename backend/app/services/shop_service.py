from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.services.llm import complete_chat
from app.services.observe_client import emit_later
from app.services.pipeline_release import BEHAVIOR_VERSION, hub_release_id
from app.services.plan_service import allow_new_site, record_site
from app.services.settings_service import get_settings
from app.services.tenant_lock import tenant_file_lock
from app.state_store import current_tenant, read_json, shared_lock, tenant_dir, write_json

log = logging.getLogger("sozan.shop")

DEFAULT_SHOP = {
    "brand": "فروشگاه",
    "slug": "",
    "port": 0,
    "domain": "",
    "jobId": "",
    "status": "idle",
    "url": "",
    "pendingBuild": 0,
    "hidePrices": False,
    "siteRevision": 0,
}

STYLE_Q = "حس فروشگاه را بگو: لوکس و خلوت، خیابانی و شلوغ، یا بوتیک خانوادگی؟"
COLOR_Q = "رنگ‌های اصلی سایت چه باشد؟ مثلاً کرم و مشکی، یا سفید و قهوه‌ای."
FEATURE_Q = "چه چیزهایی روی سایت باشد؟ جستجو، داستان برند، لینک شبکه‌ها، سبد خرید."
READY_Q = "سبک و رنگ ثبت شد. اگر ویژگی دیگری نیست، بگو بساز تا سایت را با کالاهای کانال‌هایت بسازم."

OPENING = "برای ساخت فروشگاه سه قدم است: ۱) حس فروشگاه ۲) کالا و قیمت تومان ۳) بنویس بساز."
LIVE_OPENING = "فروشگاه زنده‌ست. صفحه را همین‌جا ببین و بگو چه عوض شود."
LIVE_OPENING_INCOMPLETE = "سایت بالا آمد؛ قیمت تومان و عکس را کامل کن."
CHECKLIST_ID = "shop-ready-check"
CHECKLIST = "قبل از انتشار: ۱) قیمت تومان ۲) عکس کالا ۳) لینک ویترین را باز کن"
SAFE_BUILD = "مشکل موقت در ساخت؛ دوباره بساز."
SHOP_DENY = re.compile(r"seed phrase|bitcoin|private key|mnemonic|Traceback|FAIL:", re.I)
EDIT_FAIL_ONE = "این تغییر روی صفحه پیدا نشد. المان را در پیش‌نمایش لمس کن یا دقیق‌تر بگو."
EDIT_FAIL_MARKERS = ("صفحه ساخته نشد", "روی این صفحه پیدا نشد", "تیتر روی این صفحه پیدا نشد", "دوباره بفرست")

SHOP_SYSTEM = """تو دستیار فروشگاه سوزان هستی. جواب را JSON بده: {"reply":"متن فارسی کوتاه"}
به سؤال‌های فروشنده جواب بده. نگو پیام ویرایش فروشگاه نیست.
خودت سایت را نساز و نگو ساخته شد مگر دادهٔ بیلد بگوید آماده است.
کار انجام‌نشده را موفق نگو: تصویر، رنگ، برند یا کالا را ساخته‌شده اعلام نکن مگر دادهٔ سیستم همان را تأیید کند.
اگر پرسید کی هستی: بگو دستیار سوزان برای همین برند هستی.
وضعیت بیلد را از دادهٔ سیستم بخوان، حدس نزن."""
SHOP_SETUP_HINT = "هنوز فروشگاه زنده نیست. سبک و رنگ را می‌گیری و فقط وقتی گفت بساز، کارخانه را راه می‌اندازی."
SHOP_LIVE_HINT = """فروشگاه همین الان زنده است. مصاحبهٔ سبک و رنگ را از نو شروع نکن.
سؤال دربارهٔ فروشگاه، ورود مشتری، یا پیشنهاد بهبود را از دادهٔ سیستم و متن فعلی صفحه جواب بده. نگو صفحه را نمی‌بینی اگر متنش آمده.
اگر پیج اسکن‌شده و کالا در داده آمده، همان را استفاده کن. نگو به اینستاگرام یا پیج دسترسی نداری.
کار انجام‌نشده را موفق نگو.
درخواست تغییر متن، رنگ یا تصویر همان صفحهٔ پیش‌نمایش است نه ساخت سایت جدید. تغییر همان لحظه در کادر دیده می‌شود؛ کارخانه را راه نینداز.
سلام را کوتاه جواب بده. دکمهٔ بیلد فقط سایت را با next build تازه می‌کند. کارخانهٔ کامل فقط اگر صریح گفت از نو بساز."""

PRICE_MISSING = "بدون قیمت تومان، ویترین فروش نمی‌شود — فقط استعلام."
BUILD_MSG_ID = "shop-build-live"
BUILD_BUSY = frozenset({"running", "queued"})
JOB_STALE_SECONDS = 30 * 60
EXPLICIT_BUILD = ("بیلد کن", "دوباره بیلد", "دوباره بساز", "rebuild", "فروشگاه را بساز")
FULL_REBUILD = ("از نو بساز", "فروشگاه را از نو بساز", "قالب را از نو")
BUILD_WORD = re.compile(r"(?:^|[\s،,])بساز(?:ش|ید)?(?:$|[\s،.])")
PROGRESS_HINT = ("مرحله", "وضعیت ساخت", "وضعیت بیلد", "چقدر مانده", "در چه مرحله", "پیشرفت", "دوباره ببین", "چه خبر از ساخت", "چه خبر از بیلد")
SKINS = ("atelier", "street", "boutique")
STEP_FA = {
    "archetype": "در حال فهمیدن نوع فروشگاه…",
    "DESIGN_27B": "در حال طراحی ظاهر و چیدن کالاها…",
    "DESIGN_CLOUD": "در حال طراحی ابری ظاهر و کالاها…",
    "DESIGN_SKIPPED": "قالب آماده بود؛ در حال کپی…",
    "COMFY": "در حال ساخت تصویرها…",
    "COPY_TEMPLATE": "در حال ساخت صفحات سایت…",
    "DOCKER": "در حال روشن کردن سایت زنده…",
    "RELEASE_LOGO": "در حال گذاشتن لوگو…",
    "revise": "در حال اصلاح سایت…",
}
STEP_DONE_FA = {
    "archetype": "فهم نوع فروشگاه",
    "DESIGN_27B": "طراحی ظاهر",
    "DESIGN_CLOUD": "طراحی ابری",
    "DESIGN_SKIPPED": "کپی قالب",
    "COMFY": "ساخت تصویرها",
    "COPY_TEMPLATE": "ساخت صفحات",
    "DOCKER": "روشن کردن سایت زنده",
    "RELEASE_LOGO": "گذاشتن لوگو",
    "revise": "اصلاح سایت",
}
LIVE_TRACK = ("archetype", "DESIGN_27B", "COPY_TEMPLATE", "DOCKER")


def _shop() -> dict:
    data = read_json("shop.json", DEFAULT_SHOP)
    if not isinstance(data, dict):
        data = dict(DEFAULT_SHOP)
    merged = dict(DEFAULT_SHOP)
    merged.update(data)
    return merged


def _save_shop(shop: dict) -> dict:
    shop["url"] = live_url(shop)
    with tenant_file_lock("shop"):
        write_json("shop.json", shop)
    return shop


def live_url(shop: dict) -> str:
    custom = str(shop.get("domain") or "").strip().rstrip("/")
    if custom and shop.get("cnameOk"):
        return custom if custom.startswith("http") else f"https://{custom}"
    slug_host = str(shop.get("publicHost") or "").strip()
    if slug_host:
        return f"https://{slug_host}"
    domain = custom
    if domain:
        return domain if domain.startswith("http") else f"https://{domain}"
    port = shop.get("port")
    if port:
        return f"http://127.0.0.1:{int(port)}"
    return str(shop.get("url") or "")


RESERVED_SLUGS = frozenset(
    {"sozan", "app", "api", "www", "admin", "ai", "ai0", "status", "mail", "shop", "pay", "help", "blog"}
)


def _publish_dns(shop: dict) -> dict:
    from app.services import arvan_dns_service

    slug = str(shop.get("slug") or "").strip()
    if not slug:
        return shop
    if slug.lower() in RESERVED_SLUGS:
        # فروشگاه موجودِ رزروشده فقط با تغییر اسلاگ منتشر می‌شود، نه با خطا.
        new_slug = f"{slug}-shop" if f"{slug}-shop" not in RESERVED_SLUGS else f"{slug}1"
        shop["slug"] = new_slug
        slug = new_slug
    result = arvan_dns_service.ensure_shop_record(slug)
    shop["publicHost"] = arvan_dns_service.public_host(slug)
    shop["cnameTarget"] = arvan_dns_service.cname_target(slug)
    shop["dns"] = result
    if result.get("ok") and not shop.get("domain"):
        shop["domain"] = shop["publicHost"]
    _write_shop_upstream(shop)
    return shop


def _shop_map_path() -> Path:
    return Path(__file__).resolve().parents[3] / "deploy" / "shop-upstreams.map"


def _shop_custom_names_path() -> Path:
    return Path(__file__).resolve().parents[3] / "deploy" / "shop-custom-names.conf"


def _map_host(value: str) -> str:
    from app.services import arvan_dns_service

    return arvan_dns_service.hostname(value)


def _shop_upstream_lines(shop: dict) -> list[str]:
    port = shop.get("port")
    if not port:
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for raw in (shop.get("publicHost"), shop.get("domain")):
        host = _map_host(str(raw or ""))
        if not host or host in seen:
            continue
        seen.add(host)
        lines.append(f"{host} 127.0.0.1:{int(port)};")
    return lines


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _write_shop_upstream(shop: dict) -> None:
    from app.services import arvan_dns_service

    if arvan_dns_service.edge_dry():
        return
    from app.state_store import current_tenant, iter_tenants, read_json, tenant_scope

    dest = _shop_map_path()
    names = _shop_custom_names_path()
    collected: list[str] = []
    seen: set[str] = set()

    def add_line(line: str) -> None:
        host = line.split()[0] if line.split() else ""
        if not host or host in seen:
            return
        seen.add(host)
        collected.append(line)

    def add(row: dict) -> None:
        for line in _shop_upstream_lines(row):
            add_line(line)

    with shared_lock():
        dest.parent.mkdir(parents=True, exist_ok=True)
        add(shop)
        me = current_tenant()
        for phone in iter_tenants():
            if phone == me:
                continue
            with tenant_scope(phone):
                row = read_json("shop.json", {})
            if isinstance(row, dict):
                add(row)
        from app.services import arvan_dns_service

        zone = arvan_dns_service.zone()
        if dest.is_file():
            for line in dest.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                host = raw.split()[0]
                if host == zone or host.endswith("." + zone):
                    add_line(raw)
        _atomic_text(dest, "\n".join(collected) + ("\n" if collected else ""))
        custom_hosts = [
            line.split()[0]
            for line in collected
            if line.split() and line.split()[0] != zone and not line.split()[0].endswith("." + zone)
        ]
        if custom_hosts:
            _atomic_text(names, "server_name " + " ".join(custom_hosts) + ";\n")
        else:
            _atomic_text(names, "# no custom shop hosts\n")
    _reload_edge()


def _reload_edge() -> None:
    nginx = Path("/usr/sbin/nginx")
    if not nginx.is_file():
        return
    probe = subprocess.run(
        ["sudo", "-n", str(nginx), "-t"],
        check=False,
        capture_output=True,
        timeout=8,
        text=True,
    )
    if probe.returncode != 0:
        log.warning("nginx -t failed: %s", (probe.stderr or probe.stdout or "")[:400])
        return
    subprocess.run(["sudo", "-n", str(nginx), "-s", "reload"], check=False, capture_output=True, timeout=8)


def _messages() -> list[dict]:
    rows = read_json("shop-messages.json", [])
    return rows if isinstance(rows, list) else []


def _save_messages(rows: list[dict]) -> None:
    write_json("shop-messages.json", rows[-80:])


def _looks_raw_operator(text: str) -> bool:
    blob = str(text or "")
    if not blob:
        return False
    if "FAIL:" in blob or blob.startswith("File ") or "Traceback" in blob:
        return True
    letters = [ch for ch in blob if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii())
    return latin * 10 >= len(letters) * 6


def sanitize_shop_text(text: str) -> str:
    raw = str(text or "")
    if SHOP_DENY.search(raw):
        return "پیام نامعتبر حذف شد"
    return raw


def _is_edit_fail(text: str) -> bool:
    blob = str(text or "")
    if blob == EDIT_FAIL_ONE:
        return True
    return any(marker in blob for marker in EDIT_FAIL_MARKERS)


def _sanitize_row(row: object) -> dict:
    if not isinstance(row, dict):
        return {"id": str(uuid4()), "role": "assistant", "text": "", "at": int(time.time())}
    out = dict(row)
    out["text"] = sanitize_shop_text(str(out.get("text") or ""))
    return out


def _append_assistant(rows: list[dict], assistant: dict) -> dict:
    text = sanitize_shop_text(str(assistant.get("text") or ""))
    if _is_edit_fail(text):
        text = EDIT_FAIL_ONE
    assistant = dict(assistant)
    assistant["text"] = text
    last = rows[-1] if rows else None
    if (
        last
        and last.get("role") == "assistant"
        and str(last.get("id") or "") not in {BUILD_MSG_ID, CHECKLIST_ID}
        and _is_edit_fail(str(last.get("text") or ""))
        and _is_edit_fail(text)
    ):
        last["text"] = EDIT_FAIL_ONE
        last["at"] = int(assistant.get("at") or time.time())
        return last
    rows.append(assistant)
    return assistant


def bump_pending_build() -> None:
    shop = _shop()
    if not shop.get("slug"):
        return
    _bump_pending(shop)


def reset_for_brand(*, name: str, tagline: str) -> dict:
    shop = {
        "brand": name,
        "slug": "",
        "port": 0,
        "domain": "",
        "jobId": "",
        "status": "idle",
        "url": "",
        "tagline": tagline,
    }
    write_json("shop-messages.json", [])
    from app.services import shop_workspace_service

    shop_workspace_service.reset_workspace()
    return _save_shop(shop)


def _shop_is_live(shop: dict) -> bool:
    if str(shop.get("status") or "") == "ready":
        return True
    slug = str(shop.get("slug") or "").strip()
    if not slug:
        return False
    return bool(shop.get("url") or shop.get("publicHost") or shop.get("port"))


def _public_shop(shop: dict) -> dict:
    out = dict(shop)
    out.pop("paySecret", None)
    out["priceBlocked"] = _missing_sellable_price(shop)
    return out


def _opening_text(shop: dict) -> str:
    if not _shop_is_live(shop):
        return OPENING
    if _missing_sellable_price(shop):
        return LIVE_OPENING_INCOMPLETE
    return LIVE_OPENING


def snapshot() -> dict:
    from app.services import channel_scan_service

    shop = _refresh_job(_shop())
    rows = [_sanitize_row(row) for row in _messages()]
    if not rows:
        rows = [{"id": str(uuid4()), "role": "assistant", "text": _opening_text(shop), "at": int(time.time())}]
        _save_messages(rows)
    build = _factory_status(shop)
    rows = _sync_build_note(rows, shop, build)
    _save_messages(rows)
    return {"shop": _public_shop(shop), "messages": rows, "scan": channel_scan_service.scan_status(), "build": build}


def set_domain(domain: str) -> dict:
    from app.services import arvan_dns_service

    shop = _shop()
    host = arvan_dns_service.hostname(domain)
    slug = str(shop.get("slug") or "").strip()
    public = str(shop.get("publicHost") or "").strip()
    shop["domain"] = host or public
    if slug:
        shop = _publish_dns(shop)
        public = str(shop.get("publicHost") or "").strip()
        custom = bool(host and host != public and not arvan_dns_service.is_zone_host(host))
        if custom:
            check = arvan_dns_service.check_cname(host, slug)
            shop["cnameOk"] = bool(check.get("ok"))
            shop["cnameCheck"] = check
            shop["cnameSetup"] = arvan_dns_service.start_cname_setup(host, slug)
        else:
            shop["cnameOk"] = True
            shop["cnameCheck"] = {
                "ok": True,
                "status": "sozan-host",
                "detail": "روی دامنه سوزان است.",
                "target": shop.get("cnameTarget") or "",
            }
            shop["cnameSetup"] = {"ok": True, "skipped": True}
    _save_shop(shop)
    return snapshot()


FACTORY_ENV_ALLOW = (
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
)


def _factory_env() -> dict[str, str]:
    # فقط فهرست سفید؛ رازهای هاب هرگز به زیرپروسهٔ کارخانه نمی‌روند.
    env = {key: value for key, value in os.environ.items() if key.startswith("SOZAN_") or key.startswith("LLAMA_") or key in FACTORY_ENV_ALLOW}
    swap = settings.local_llm_url.rstrip("/")
    if swap.endswith("/v1"):
        swap = swap[:-3].rstrip("/")
    env["SOZAN_SWAP_URL"] = swap
    env["LLAMA_SWAP_URL"] = swap
    gw = settings.gateway_sozan_url.rstrip("/")
    if gw:
        env["SOZAN_GATEWAY_URL"] = gw
        env["SOZAN_PUBLIC_GATEWAY_URL"] = gw
        env["SOZAN_GATEWAY_DOCKER_URL"] = gw
    env["npm_config_registry"] = "https://registry.npmjs.org"
    env["NPM_CONFIG_REGISTRY"] = "https://registry.npmjs.org"
    proxy = (settings.sozan_npm_proxy or os.environ.get("SOZAN_NPM_PROXY") or "").strip()
    if proxy:
        env["SOZAN_NPM_PROXY"] = proxy
        env["npm_config_proxy"] = proxy
        env["npm_config_https_proxy"] = proxy
    env.setdefault("SOZAN_FACTORY_SYSTEMD_RUN", "0")
    shop = _shop()
    env["SOZAN_OBSERVE_SURFACE"] = "factory"
    env["SOZAN_OBSERVE_TENANT"] = current_tenant()
    env["SOZAN_OBSERVE_BRAND"] = str(shop.get("brand") or "")
    env["SOZAN_RELEASE_ID"] = hub_release_id()
    env["SOZAN_BEHAVIOR_VERSION"] = BEHAVIOR_VERSION
    from app.services import pay_service

    env["SOZAN_CORE_API_URL"] = str(settings.public_api_url or "https://api.sozan-core.ir").rstrip("/")
    env["SOZAN_PAY_SECRET"] = pay_service.ensure_pay_secret()
    # توکن همان مسیر LLM هاب: روتر توکن OpenRouter را از open_router_api_token می‌خواند؛
    # کارخانه هم باید همان را بگیرد وگرنه 401 می‌خورد و مسیر به 27B محلی می‌افتد.
    cloud_url = (settings.cloud_llm_url or "").rstrip("/")
    cloud_token = os.environ.get("open_router_api_token", "").strip() or (settings.cloud_llm_token or "").strip()
    cloud_model = str(os.environ.get("SOZAN_ROUTING_MODEL") or settings.cloud_llm_model or "").strip()
    if cloud_url and cloud_token:
        env["SOZAN_CLOUD_LLM_URL"] = cloud_url
        env["SOZAN_CLOUD_LLM_TOKEN"] = cloud_token
        env["SOZAN_CATALOG_MODEL"] = cloud_model or "deepseek/deepseek-v4.1-flash"
        env.setdefault("SOZAN_FACTORY_PYTHON", factory_python)
        proxy = (settings.cloud_llm_proxy or settings.channel_proxy or "").strip()
        if proxy:
            env["SOZAN_CLOUD_LLM_PROXY"] = proxy
            env["CHANNEL_PROXY"] = proxy
    return env


def _run_factory(args: list[str]) -> dict:
    script = settings.factory_script
    if not script.is_file():
        return {"ok": False, "error": "اسکریپت کارخانه پیدا نشد"}
    try:
        # کارخانه httpx می‌خواهد؛ پایتون venv هاب آن را دارد، system python نه.
        factory_python = str(Path(sys.executable).resolve())
        proc = subprocess.run(
            [factory_python, str(script), *args],
            cwd=str(script.parent.parent),
            capture_output=True,
            text=True,
            timeout=40,
            env=_factory_env(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "کارخانه دیر جواب داد؛ دوباره تلاش کن."}
    text = (proc.stdout or "").strip().splitlines()
    payload = {}
    if text:
        try:
            payload = json.loads(text[-1])
        except json.JSONDecodeError:
            payload = {"ok": proc.returncode == 0, "raw": text[-1][:400]}
    if proc.returncode != 0:
        err = _operator_error((proc.stderr or proc.stdout or "بیلد شروع نشد")[-400:]) or "بیلد شروع نشد"
        if not payload.get("status"):
            payload = {"ok": False, "error": err}
        elif not payload.get("error"):
            payload["error"] = err
    elif not payload:
        payload = {"ok": False, "error": "خروجی کارخانه نامعتبر است"}
    if isinstance(payload, dict) and payload.get("error"):
        payload["error"] = _operator_error(str(payload["error"])) or SAFE_BUILD
    return payload if isinstance(payload, dict) else {"ok": False, "error": "خروجی کارخانه نامعتبر است"}


def _fastpath_root() -> Path:
    return settings.factory_script.resolve().parent.parent / "queue" / "fastpath"


def _read_job_file(job_id: str) -> dict | None:
    if not job_id:
        return None
    path = _fastpath_root() / "jobs" / f"{job_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _latest_job_for_slug(slug: str) -> dict | None:
    if not slug:
        return None
    jobs_dir = _fastpath_root() / "jobs"
    if not jobs_dir.is_dir():
        return None
    found: list[dict] = []
    for path in jobs_dir.glob("*.json"):
        data = _read_job_file(path.stem)
        if data and str(data.get("slug") or "") == slug:
            found.append(data)
    if not found:
        return None
    found.sort(key=lambda row: str(row.get("createdAt") or row.get("id") or ""), reverse=True)
    usable = [row for row in found if str(row.get("status") or "") != "cancelled"]
    return usable[0] if usable else None


def _job_is_stale(job: dict | None) -> bool:
    if not job or str(job.get("status") or "") not in BUILD_BUSY:
        return False
    job_id = str(job.get("id") or "")
    path = _fastpath_root() / "jobs" / f"{job_id}.json"
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age > JOB_STALE_SECONDS


def _busy_started_at(shop: dict) -> float:
    try:
        return float(shop.get("buildAt") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fail_stale_job(shop: dict, job: dict) -> dict:
    shop["jobId"] = str(job.get("id") or shop.get("jobId") or "")
    shop["status"] = "failed"
    shop["error"] = _operator_error(str(job.get("error") or "")) or "ساخت قبلی تمام نشد. دوباره بساز."
    return shop


def _mark_build_started(shop: dict) -> dict:
    shop["status"] = "running"
    shop["buildAt"] = int(time.time())
    shop["error"] = ""
    return shop


def _bind_live_job(shop: dict) -> dict:
    # Detached start can mint an id before the worker writes the file. Status then
    # misses the job; bind to the real latest job for this slug instead of a phantom id.
    slug = str(shop.get("slug") or "")
    current = _read_job_file(str(shop.get("jobId") or ""))
    if current and str(current.get("status") or "") in BUILD_BUSY:
        if _job_is_stale(current):
            return _fail_stale_job(shop, current)
        shop["jobId"] = str(current.get("id") or shop.get("jobId") or "")
        shop["status"] = "running"
        return shop
    latest = _latest_job_for_slug(slug)
    if not latest:
        if str(shop.get("status") or "") in BUILD_BUSY:
            started = _busy_started_at(shop)
            if not started:
                shop["buildAt"] = int(time.time())
                return shop
            if time.time() - started > JOB_STALE_SECONDS:
                return _fail_stale_job(shop, {"id": shop.get("jobId") or ""})
        return shop
    if _job_is_stale(latest):
        return _fail_stale_job(shop, latest)
    shop["jobId"] = str(latest.get("id") or "")
    status = str(latest.get("status") or "")
    was_ready = str(shop.get("status") or "") == "ready"
    shop["status"] = "ready" if status == "done" else status or shop.get("status") or "idle"
    if status == "done" and not was_ready:
        # کارخانه تازه تمام شد؛ DNS/upstream تازه نوشته و nginx هم‌گام شود.
        try:
            _publish_dns(shop)
        except Exception:
            pass
    if latest.get("url"):
        shop["url"] = latest["url"]
    if latest.get("port"):
        try:
            shop["port"] = int(latest["port"])
        except (TypeError, ValueError):
            pass
    if latest.get("error"):
        shop["error"] = _operator_error(str(latest["error"]))
    shop["urlOk"] = bool(latest.get("urlOk"))
    return shop


def _operator_error(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "FileNotFoundError" in text or "job not found" in text or "load_job" in text:
        return "شناسه این بیلد در کارخانه پیدا نشد."
    if "Traceback" in text or ".py\", line" in text or '.py", line' in text:
        return SAFE_BUILD
    if "price_missing" in text or "بدون قیمت تومان" in text or "قیمت کالاها ثبت نشده" in text:
        return PRICE_MISSING
    if "readiness failed: catalog" in text:
        return "کاتالوگ سایت خالی رسید؛ اول کالا اضافه کن، بعد دوباره بساز."
    if "readiness failed: http" in text:
        return "سایت ساخته شد اما هنوز پاسخ نمی‌دهد؛ چند لحظه بعد دوباره بساز."
    if "readiness failed: image" in text:
        return "عکس کالاها کم بود؛ عکس بگذار یا بدون عکس بساز."
    if "gpu_busy" in text or "extra GPU1 LLMs still loaded" in text or "could not acquire RESOURCE_LOCK" in text:
        return "پردازندهٔ کارخانه مشغول چت بود؛ چند لحظه بعد دوباره بساز."
    if "header search" in text or "data-sozan-search" in text:
        return "قالب جستجو در سربرگ نداشت."
    if "gateway_down" in text:
        return "گیت‌وی کاتالوگ پاسخ نداد."
    if "402" in text or "Insufficient credit" in text or "npm registry 402" in text:
        return "نصب بسته‌های سایت به رجیستری نرسید."
    if "npm ERR" in text or "npm ci failed" in text or "npm install failed" in text:
        return "نصب بسته‌های فروشگاه شکست خورد."
    if "build incomplete" in text or "URL not serving" in text:
        return "سایت روشن نشد؛ کارخانه در npm یا داکر ماند."
    line = text.splitlines()[-1].strip()
    if len(line) > 180 or line.startswith("File "):
        return SAFE_BUILD
    if _looks_raw_operator(line[:180]):
        return SAFE_BUILD
    return line[:180]


def _normalize_phases(raw: object) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        step = str(item.get("step") or "")
        if not step:
            continue
        rows.append(
            {
                "step": step,
                "label": STEP_FA.get(step) or STEP_DONE_FA.get(step, step),
                "at": str(item.get("at") or ""),
            }
        )
    return rows


def _pipeline_view(*, step: str, status: str, phases: list[dict]) -> list[dict]:
    seen = [str(row.get("step") or "") for row in phases if row.get("step")]
    track = list(LIVE_TRACK)
    if "DESIGN_CLOUD" in seen and "DESIGN_CLOUD" not in track:
        track[track.index("DESIGN_27B") if "DESIGN_27B" in track else 1] = "DESIGN_CLOUD"
    if "DESIGN_SKIPPED" in seen:
        track = ["archetype", "DESIGN_SKIPPED", "COPY_TEMPLATE", "DOCKER"]
    if "COMFY" in seen and "COMFY" not in track:
        track.insert(2, "COMFY")
    if "RELEASE_LOGO" in seen and "RELEASE_LOGO" not in track:
        track.append("RELEASE_LOGO")
    if "revise" in seen and "revise" not in track:
        track.append("revise")
    current = step or (seen[-1] if seen else "")
    cur_i = track.index(current) if current in track else (-1 if not seen else max(len(track) - 1, 0))
    busy = status in BUILD_BUSY
    out: list[dict] = []
    for index, sid in enumerate(track):
        if status == "ready" or (cur_i >= 0 and index < cur_i):
            state = "done"
        elif status == "failed" and cur_i >= 0 and index == cur_i:
            state = "fail"
        elif busy and index == cur_i:
            state = "active"
        else:
            state = "wait"
        out.append({"id": sid, "label": STEP_DONE_FA.get(sid) or STEP_FA.get(sid, sid), "state": state})
    return out


def _live_build(base: dict, *, phases_raw: object = None, started_at: str = "", elapsed: object = None) -> dict:
    phases = _normalize_phases(phases_raw)
    status = str(base.get("status") or "idle")
    step = str(base.get("step") or "")
    if not step and phases:
        step = str(phases[-1].get("step") or "")
        base["step"] = step
        base["stepLabel"] = STEP_FA.get(step, "")
    payload = dict(base)
    payload["phases"] = phases
    payload["pipeline"] = _pipeline_view(step=step, status=status, phases=phases)
    payload["startedAt"] = started_at
    try:
        payload["elapsedSec"] = int(float(elapsed)) if elapsed not in (None, "") else None
    except (TypeError, ValueError):
        payload["elapsedSec"] = None
    return payload


def _factory_status(shop: dict) -> dict:
    job_id = str(shop.get("jobId") or "")
    empty = _live_build(
        {
            "jobId": job_id,
            "status": str(shop.get("status") or "idle"),
            "step": "",
            "stepLabel": "",
            "url": live_url(shop),
            "urlOk": bool(shop.get("urlOk")),
            "error": _operator_error(str(shop.get("error") or "")),
            "errorClass": str(shop.get("errorClass") or ""),
            "releaseId": str(shop.get("releaseId") or hub_release_id()),
            "runAttempt": int(shop.get("runAttempt") or 0),
        }
    )
    if not job_id:
        return empty
    result = _run_factory(["status", "--job-id", job_id])
    if str(result.get("status") or "") in {"", "missing"}:
        local = _read_job_file(job_id) or _latest_job_for_slug(str(shop.get("slug") or ""))
        if local:
            status = str(local.get("status") or "idle")
            if status == "done":
                status = "ready"
            step = ""
            phases = local.get("phases") if isinstance(local.get("phases"), list) else []
            if phases and isinstance(phases[-1], dict):
                step = str(phases[-1].get("step") or "")
            return _live_build(
                {
                    "jobId": str(local.get("id") or job_id),
                    "status": status,
                    "step": step,
                    "stepLabel": STEP_FA.get(step, ""),
                    "url": str(local.get("url") or live_url(shop)),
                    "urlOk": bool(local.get("urlOk")),
                    "error": _operator_error(str(local.get("error") or "")),
                    "errorClass": str(local.get("errorClass") or ""),
                    "releaseId": str(local.get("releaseId") or hub_release_id()),
                    "runAttempt": int(local.get("runAttempt") or 0),
                    "siteRevision": int(local.get("siteRevision") or shop.get("siteRevision") or 0),
                },
                phases_raw=phases,
                started_at=str(local.get("createdAt") or ""),
                elapsed=local.get("elapsedSec"),
            )
        return _live_build(
            {
                **empty,
                "status": "failed" if str(shop.get("status") or "") in BUILD_BUSY else empty["status"],
                "error": _operator_error(str(result.get("error") or "وضعیت بیلد پیدا نشد")),
            }
        )
    status = str(result.get("status") or shop.get("status") or "idle")
    if status == "done":
        status = "ready"
    step = str(result.get("step") or "")
    error = _operator_error(str(result.get("error") or ""))
    return _live_build(
        {
            "jobId": job_id,
            "status": status,
            "step": step,
            "stepLabel": STEP_FA.get(step, ""),
            "url": str(result.get("url") or live_url(shop)),
            "urlOk": bool(result.get("urlOk")),
            "error": error,
            "errorClass": str(result.get("errorClass") or ""),
            "releaseId": str(result.get("releaseId") or hub_release_id()),
            "runAttempt": int(result.get("runAttempt") or 0),
            "siteRevision": int(result.get("siteRevision") or shop.get("siteRevision") or 0),
        },
        phases_raw=result.get("phases"),
        started_at=str(result.get("createdAt") or ""),
        elapsed=result.get("elapsedSec"),
    )


def _persian_build_text(build: dict) -> str:
    status = str(build.get("status") or "")
    if status in BUILD_BUSY:
        label = str(build.get("stepLabel") or "") or "کارخانه در حال ساخت سایت است…"
        return f"در حال ساخت فروشگاه. {label}"
    if status == "ready":
        if _missing_sellable_price(_shop()):
            return LIVE_OPENING_INCOMPLETE
        url = str(build.get("url") or "").strip()
        live = "سایت زنده است." if build.get("urlOk") or url else "ساخت تمام شد."
        return f"{live} {url}".strip()
    if status == "failed":
        hint = _operator_error(str(build.get("error") or "")) or "کارخانه ساخت را تمام نکرد."
        done = STEP_DONE_FA.get(str(build.get("step") or ""), "")
        prefix = f"تا {done} رفت و کامل نشد." if done else "ساخت کامل نشد."
        return f"{prefix} {hint} اگر خواستی بگو دوباره بساز."
    return ""


def _sync_build_note(rows: list[dict], shop: dict, build: dict) -> list[dict]:
    text = _persian_build_text(build)
    if not text:
        return rows
    note = {
        "id": BUILD_MSG_ID,
        "role": "assistant",
        "kind": "build",
        "text": text,
        "at": int(time.time()),
    }
    rest = [row for row in rows if str(row.get("id") or "") != BUILD_MSG_ID]
    if str(build.get("status") or "") in BUILD_BUSY:
        return rest + [note]
    existing = next((row for row in rows if str(row.get("id") or "") == BUILD_MSG_ID), None)
    if existing:
        existing.update(note)
        return _ensure_checklist(rows, build)
    return _ensure_checklist(rest + [note], build)


def _ensure_checklist(rows: list[dict], build: dict) -> list[dict]:
    if str(build.get("status") or "") != "ready":
        return rows
    if any(str(row.get("id") or "") == CHECKLIST_ID for row in rows):
        return rows
    return list(rows) + [
        {
            "id": CHECKLIST_ID,
            "role": "assistant",
            "text": CHECKLIST,
            "at": int(time.time()),
        }
    ]


def _refresh_job(shop: dict) -> dict:
    prev_status = str(shop.get("status") or "")
    shop = _bind_live_job(shop)
    job_id = str(shop.get("jobId") or "")
    if not job_id:
        return _save_shop(shop)
    build = _factory_status(shop)
    status = str(build.get("status") or shop.get("status") or "")
    if build.get("url"):
        shop["url"] = build["url"]
        if "127.0.0.1:" in str(build["url"]):
            try:
                shop["port"] = int(str(build["url"]).rsplit(":", 1)[-1])
            except ValueError:
                pass
    if status:
        shop["status"] = status
    shop["urlOk"] = bool(build.get("urlOk"))
    shop["error"] = str(build.get("error") or "")[:400]
    if build.get("jobId"):
        shop["jobId"] = build["jobId"]
    saved = _save_shop(shop)
    now_status = str(saved.get("status") or "")
    if now_status != prev_status and now_status == "ready":
        _publish_catalog_images(saved)
        if saved.get("urlOk") or saved.get("url") or saved.get("publicHost") or saved.get("port"):
            saved = _publish_dns(saved)
            saved["pendingBuild"] = 0
            saved = _save_shop(saved)
    if now_status != prev_status and now_status in {"ready", "failed"}:
        emit_later(
            kind="factory",
            surface="factory",
            title=f"build-{now_status}",
            status=now_status,
            stage="verified" if now_status == "ready" else "failed",
            job_id=str(saved.get("jobId") or ""),
            payload={
                "slug": saved.get("slug") or "",
                "jobId": saved.get("jobId") or "",
                "url": saved.get("url") or "",
                "error": saved.get("error") or "",
                "releaseId": hub_release_id(),
            },
        )
    return saved


def _catalog_price_line(row: dict, *, hide_prices: bool) -> str:
    from app.services import storefront_service

    if hide_prices:
        return "بدون قیمت"
    note = str(row.get("priceNote") or "")
    label = storefront_service.price_label(int(row.get("price") or 0), note)
    if label:
        return label
    return str(row.get("price")) + " تومان"


_BAG_SUBS = (
    ("دوشی", "doushi"),
    ("مجلسی", "majlesi"),
    ("دستی", "dasti"),
    ("دانشجویی", "student"),
    ("خرگوش", "bunny"),
    ("مدرسه", "school"),
    ("پاییز", "fall"),
    ("پول", "wallet"),
    ("چرم", "leather"),
)
_SPICE_SUBS = (
    ("نگین", "negin"),
    ("پوشال", "pushal"),
    ("دسته", "bunch"),
    ("سرگل", "sargol"),
    ("هل", "cardamom"),
    ("زرشک", "barberry"),
    ("دارچین", "cinnamon"),
)


def _factory_category_slug(category_fa: str) -> str:
    blob = category_fa or ""
    if "کیف" in blob:
        return "bags"
    if "کفش" in blob or "صندل" in blob:
        return "shoes"
    if any(token in blob for token in ("زعفران", "ادویه", "هل", "زرشک")):
        return "saffron"
    if "عسل" in blob:
        return "honey"
    if "چای" in blob:
        return "tea"
    return "goods"


def _factory_item_prompt(title: str, category_fa: str) -> str:
    slug = _factory_category_slug(category_fa)
    if slug == "bags":
        return "studio product photo of a single bag, seamless backdrop, no people, no text"
    if slug == "saffron":
        return (
            f"studio product photo of {title} saffron spice in a glass jar on linen, "
            "warm rural light, no people, no text"
        )
    return f"studio product photo of {title}, seamless backdrop, no people, no text"


def _factory_hero_prompt(category_fa: str) -> str:
    slug = _factory_category_slug(category_fa)
    if slug == "bags":
        return "leather handbags on a quiet studio table, no people, no text"
    if slug == "saffron":
        return "saffron threads and spice bowls on rustic wood, warm rural light, no people, no text"
    return "cinematic storefront hero, product still life, no people, no text"


def _factory_item_sub(title: str, category_fa: str) -> tuple[str, str]:
    slug = _factory_category_slug(category_fa)
    pairs = _BAG_SUBS if slug == "bags" else _SPICE_SUBS if slug == "saffron" else ()
    for label, token in pairs:
        if label in title:
            return token, label
    if slug == "bags":
        return "bag", category_fa or "کیف"
    return slug or "item", category_fa or "کالا"


def _ensure_generated_catalog_photos(payload: dict) -> dict:
    from app.services import channel_scan_service, shop_edit_service

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        return payload
    dest = channel_scan_service._scan_dir()
    for idx, item in enumerate(items[:8], start=1):
        if not isinstance(item, dict):
            continue
        if Path(str(item.get("sourceImage") or "")).is_file():
            continue
        existing = dest / f"gen-{idx:02d}.png"
        if existing.is_file() and existing.stat().st_size >= 2048:
            item["sourceImage"] = str(existing)
    if Path(str(payload.get("sourceHero") or "")).is_file():
        pass
    else:
        hero_existing = dest / "gen-hero.png"
        if hero_existing.is_file() and hero_existing.stat().st_size >= 2048:
            payload["sourceHero"] = str(hero_existing)
    missing = [
        item
        for item in items[:8]
        if isinstance(item, dict) and not Path(str(item.get("sourceImage") or "")).is_file()
    ]
    _ = missing
    return payload


def _factory_catalog_payload() -> dict:
    from app.services import channel_scan_service, storefront_service

    shop = _shop()
    hide_prices = bool(shop.get("hidePrices"))
    products = storefront_service.list_products().get("products") or []
    scan = channel_scan_service._scan_dir()
    items: list[dict] = []
    cats: list[str] = []
    for row in products[:24]:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        category_fa = str(row.get("category") or "").strip() or "کالا"
        if category_fa not in cats:
            cats.append(category_fa)
        sub_slug, sub_fa = _factory_item_sub(title, category_fa)
        note = str(row.get("priceNote") or "").strip()
        price = int(row.get("price") or 0)
        label = "بدون قیمت" if hide_prices else storefront_service.price_label(price, note)
        image_name = Path(str(row.get("image") or "")).name
        src = scan / image_name if image_name else None
        cat_slug = _factory_category_slug(category_fa)
        item = {
            "title": title,
            "description": str(row.get("description") or title)[:400],
            "price": price,
            "category": cat_slug,
            "categoryFa": category_fa,
            "subcategory": sub_slug,
            "subcategoryFa": sub_fa,
            "prompt": _factory_item_prompt(title, category_fa),
            "gender": "women" if cat_slug == "bags" and any(token in title for token in ("زنانه", "دخترانه", "مجلسی")) else "unisex",
        }
        if label:
            item["priceLabel"] = label
        if src is not None and src.is_file():
            item["sourceImage"] = str(src)
        inquiry = _inquiry_url(row)
        if inquiry:
            item["inquiryUrl"] = inquiry
        colors = [str(item_color).strip() for item_color in (row.get("colors") or []) if str(item_color).strip()]
        specs = []
        if colors:
            specs.append({"label": "رنگ", "value": "، ".join(colors)})
        if row.get("sizes"):
            specs.append({"label": "سایز", "value": str(row.get("sizes"))})
        if specs:
            item["specs"] = specs
        items.append(item)
    category_fa = cats[0] if cats else "کالا"
    payload = {
        "categorySlug": _factory_category_slug(category_fa),
        "categoryFa": category_fa,
        "tagline": "",
        "heroPrompt": _factory_hero_prompt(category_fa),
        "logoPrompt": "",
        "lockItems": True,
        "items": items,
    }
    return _ensure_generated_catalog_photos(payload)


def _inquiry_url(row: dict | None = None) -> str:
    handle = str((row or {}).get("sourceHandle") or "").strip().lstrip("@")
    source = str((row or {}).get("source") or "").strip().lower()
    if not handle:
        return ""
    handle = handle.split("/")[-1]
    if source in {"telegram", "tg"}:
        if handle.isdigit():
            return ""
        return f"https://t.me/{handle}"
    return f"https://ig.me/m/{handle}"


def _write_factory_catalog(slug: str) -> Path | None:
    payload = _factory_catalog_payload()
    if not payload.get("items"):
        return None
    dest_dir = tenant_dir() / "factory-incoming"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{(slug or 'shop').strip()}-catalog.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def _factory_prompt(user_text: str) -> str:
    from app.services import channel_scan_service, onboard_service, storefront_service

    shop = _shop()
    hide_prices = bool(shop.get("hidePrices"))
    products = storefront_service.list_products().get("products") or []
    lines = []
    cats: list[str] = []
    for row in products[:24]:
        title = row.get("title")
        price = _catalog_price_line(row, hide_prices=hide_prices)
        desc = row.get("description") or ""
        image = str(row.get("image") or "").strip()
        category = str(row.get("category") or "").strip()
        if category and category not in cats:
            cats.append(category)
        bit = f"- {title} / {price} / {desc}"
        if category:
            bit += f" / دسته: {category}"
        colors = [str(item) for item in (row.get("colors") or []) if str(item).strip()]
        if colors:
            bit += " / رنگ " + "، ".join(colors)
        if row.get("sizes"):
            bit += f" / {row.get('sizes')}"
        if image:
            bit += f" / تصویر کانال: {image} → public/products/{image}"
        lines.append(bit)
    catalog = "\n".join(lines) or "کالایی در کاتالوگ نیست"
    grouped = "، ".join(cats) or "بدون دسته"
    images_dir = str(channel_scan_service._scan_dir())
    extra = "قیمت روی کارت کالا ننویس.\n" if hide_prices else ""
    from app.services import shop_workspace_service

    folder = shop_workspace_service.instructions_block()
    folder_block = f"{folder}\n" if folder.strip() else ""
    return (
        f"{onboard_service.brief_block()}\n"
        f"{channel_scan_service.brief_for_shop()}\n"
        f"{folder_block}"
        f"دسته‌بندی‌های کانال برای منو و صفحهٔ دسته: {grouped}\n"
        f"فقط همین دسته‌ها و همین کالاها را بگذار. کالای ساختگی نساز؛ مانتو و شلوار و شومیز نگذار مگر در همین فهرست باشند.\n"
        f"فایل‌های تصویر کانال در {images_dir} هستند؛ همان فایل را به public/products کپی کن و روی کارت همان کالا بگذار. تصویر ساختگی نساز.\n"
        f"{extra}"
        f"کالاها برای صفحهٔ فروش (همه را در سایت بگذار):\n{catalog}\n"
        f"درخواست فروشنده: {user_text.strip()}"
    )


def _publish_catalog_images(shop: dict) -> None:
    from app.services import channel_scan_service, shop_edit_service, storefront_service

    slug = str(shop.get("slug") or "").strip()
    if not slug or slug in PROTECTED_SHOP_SLUGS:
        return
    source = channel_scan_service._scan_dir()
    root = shop_edit_service.build_dir_for(shop)
    for row in storefront_service.list_products().get("products") or []:
        name = Path(str(row.get("image") or "")).name
        if not name:
            continue
        src = source / name
        if not src.is_file():
            continue
        if root is not None:
            dest = root / "public" / "products" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        copied = subprocess.run(
            ["docker", "cp", str(src), f"sozan-{slug}:/app/public/products/{name}"],
            check=False,
            timeout=30,
            capture_output=True,
            text=True,
        )
        if copied.returncode != 0:
            emit_later(
                kind="factory",
                surface="factory",
                title="docker-cp-failed",
                status="failed",
                job_id=str(shop.get("jobId") or ""),
                payload={"code": copied.returncode, "stderr": (copied.stderr or "")[-400:], "file": name},
            )
    from app.services import shop_workspace_service

    shop_workspace_service.publish_instructions(root)
    if root is not None:
        shop_workspace_service.capture_site(root)


def _emit_build(result: dict, shop: dict, *, rebuild: bool) -> None:
    emit_later(
        kind="factory",
        surface="factory",
        title="build-start" if result.get("ok") else "build-blocked",
        status="started" if result.get("ok") else "blocked",
        stage="requested",
        job_id=str(result.get("jobId") or shop.get("jobId") or ""),
        payload={
            "ok": bool(result.get("ok")),
            "queued": bool(result.get("queued")),
            "jobId": result.get("jobId") or shop.get("jobId") or "",
            "slug": shop.get("slug") or "",
            "error": result.get("error") or "",
            "rebuild": rebuild,
            "releaseId": hub_release_id(),
        },
    )


PROTECTED_SHOP_SLUGS = frozenset({"joahr-froshi", "cahrm-srai-pars"})
PROTECTED_TENANTS = frozenset({"09120007777"})


def _missing_sellable_price(shop: dict) -> bool:
    if bool(shop.get("hidePrices")):
        return False
    from app.services import storefront_service

    products = storefront_service.list_products().get("products") or []
    for row in products:
        if not isinstance(row, dict):
            continue
        try:
            price = int(row.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        note = str(row.get("priceNote") or "").strip()
        if price > 0 and not note:
            return False
    return True


def start_build(*, prompt: str, rebuild: bool, revise_only: bool | None = None) -> dict:
    shop = _shop()
    if current_tenant() in PROTECTED_TENANTS or str(shop.get("slug") or "") in PROTECTED_SHOP_SLUGS:
        result = {"ok": False, "error": "این فروشگاه برای ساخت دوباره قفل است."}
        _emit_build(result, shop, rebuild=rebuild)
        return result
    if str(shop.get("status") or "") in BUILD_BUSY:
        result = {"ok": False, "error": "ساخت قبلی هنوز تمام نشده", "queued": True}
        _emit_build(result, shop, rebuild=rebuild)
        return result
    if _missing_sellable_price(shop):
        shop["error"] = PRICE_MISSING
        _save_shop(shop)
        result = {"ok": False, "code": "price_missing", "error": PRICE_MISSING}
        _emit_build(result, shop, rebuild=rebuild)
        return result
    full_rebuild = _wants_full_rebuild(prompt)
    if shop.get("slug") and rebuild and (revise_only is True or (revise_only is None and not full_rebuild)):
        from app.services import shop_edit_service

        job_id = str(shop.get("jobId") or "")
        if not job_id:
            result = {"ok": False, "error": "بیلد قبلی پیدا نشد. اگر لازم است بگو از نو بساز."}
            _emit_build(result, shop, rebuild=rebuild)
            return result
        shop_edit_service.spawn_rebuild(job_id, shop)
        shop = _shop()
        result = {"ok": True, "jobId": job_id, "status": "running", "slug": shop.get("slug")}
        _emit_build(result, shop, rebuild=rebuild)
        return result
    if not rebuild and not shop.get("slug"):
        blocked = allow_new_site()
        if blocked:
            result = {"ok": False, "error": blocked}
            _emit_build(result, shop, rebuild=rebuild)
            return result
    if shop.get("slug") and not rebuild:
        result = {"ok": False, "error": "فروشگاه از قبل ساخته شده. برای ساخت دوباره باید تأیید کنی."}
        _emit_build(result, shop, rebuild=rebuild)
        return result
    cfg = get_settings()
    brand = str(shop.get("brand") or cfg.get("storeName") or "فروشگاه")
    from app.services import channel_scan_service

    hint = channel_scan_service.site_type_hint()
    args = [
        "start",
        "--brand",
        brand,
        "--prompt",
        _factory_prompt(prompt.strip() or cfg.get("storeTagline") or brand),
        "--site-type-hint",
        hint,
        "--detach",
        "--skip-images",
    ]
    catalog = _write_factory_catalog(str(shop.get("slug") or ""))
    if catalog:
        args.extend(["--catalog", str(catalog)])
    if shop.get("slug"):
        args.extend(["--replace-existing", "--slug", str(shop["slug"])])
        if shop.get("port"):
            args.extend(["--port", str(int(shop["port"]))])
    result = _run_factory(args)
    if result.get("queued") and result.get("activeJobId"):
        shop["jobId"] = str(result.get("activeJobId") or shop.get("jobId") or "")
        _mark_build_started(shop)
        _save_shop(shop)
        _emit_build(result, shop, rebuild=rebuild)
        return result
    if result.get("ok"):
        shop["jobId"] = result.get("jobId") or shop.get("jobId")
        next_status = str(result.get("status") or "running")
        if next_status in BUILD_BUSY:
            _mark_build_started(shop)
        else:
            shop["status"] = next_status
        if result.get("slug"):
            shop["slug"] = result["slug"]
        if result.get("url"):
            shop["url"] = result["url"]
            if "127.0.0.1:" in str(result["url"]):
                try:
                    shop["port"] = int(str(result["url"]).rsplit(":", 1)[-1])
                except ValueError:
                    pass
        shop["brand"] = brand
        shop["urlOk"] = False
        shop["error"] = ""
        _save_shop(shop)
        if shop.get("slug"):
            record_site(str(shop["slug"]))
    if result.get("error"):
        result["error"] = _operator_error(str(result["error"])) or SAFE_BUILD
    _emit_build(result, shop, rebuild=rebuild)
    return result


def rebuild_from_channel_catalog() -> dict | None:
    # Scan writes products into the catalog. A ready shop waits for the seller's Build button.
    return None


def _wants_progress(text: str) -> bool:
    lowered = text.strip()
    return any(token in lowered for token in PROGRESS_HINT)


def _wants_full_rebuild(text: str) -> bool:
    return any(token in (text or "") for token in FULL_REBUILD)


def _explicit_rebuild(text: str) -> bool:
    lowered = text.strip().lower()
    return _wants_full_rebuild(text) or any(
        token in lowered for token in ("دوباره بساز", "دوباره بیلد", "بیلد کن", "rebuild", "فروشگاه را دوباره بساز")
    )


def _explicit_build(text: str) -> bool:
    lowered = text.strip()
    if any(token in lowered for token in ("نکن", "نساز", "بدون بیلد")):
        return False
    if _explicit_rebuild(lowered):
        return True
    if lowered in {"بساز", "بسازش", "بسازید"}:
        return True
    if any(token in lowered for token in EXPLICIT_BUILD):
        return True
    return bool(BUILD_WORD.search(f" {lowered} "))


def _norm_style(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in SKINS:
        return text
    if "street" in text or "خیابان" in text or "کتانی" in text:
        return "street"
    if "boutique" in text or "بوتیک" in text or "classic" in text or "خانواد" in text:
        return "boutique"
    if "atelier" in text or "لوکس" in text or "چرم" in text:
        return "atelier"
    if "روستا" in text or "روستایی" in text:
        return "boutique"
    return ""


_ASIDE_START = (
    "تو ",
    "چرا",
    "چی",
    "کی ",
    "آیا",
    "سلام",
    "درود",
    "که هستی",
    "خوبی",
    "چطوری",
    "چخبر",
    "چه خبر",
    "مرسی",
    "ممنون",
)


def _is_aside(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(("؟", "?")):
        return True
    return stripped.startswith(_ASIDE_START)


_LIVE_GREET = frozenset(
    {
        "سلام",
        "درود",
        "خوبی",
        "چطوری",
        "چخبر",
        "چه خبر",
        "مرسی",
        "ممنون",
        "که هستی",
        "تو کی هستی",
        "سلام خوبی",
        "سلام چطوری",
    }
)


def _is_live_greeting(text: str) -> bool:
    stripped = text.strip().replace("؟", "").replace("?", "").strip()
    return stripped in _LIVE_GREET


_ADVICE = ("پیشنهاد", "توضیح", "چطور", "چگونه", "به چه شکل")
_CONTINUE = frozenset({"خب", "باشه", "باشه خب", "اوکی", "ok", "okay", "ادامه", "ادامه بده", "بیشتر بگو", "بعدی"})
FA_QUOTED = re.compile(r"['\"]([^'\"\n]{1,80}[\u0600-\u06FF][^'\"\n]{0,80})['\"]")
FA_NODE = re.compile(r">\s*([^<>{\n]*[\u0600-\u06FF][^<>{\n]*)\s*<")
COMPONENT_IMPORT = re.compile(r"from ['\"]@/components/([^'\"]+)['\"]")


def _live_edit_intent(text: str, view_target: str = "") -> bool:
    from app.services import shop_edit_service

    if (view_target or "").strip():
        return True
    return bool(
        shop_edit_service.write_intent(text)
        or shop_edit_service.named_color_updates(text)
        or shop_edit_service.wants_hero_image(text)
        or shop_edit_service.wants_revert(text)
    )


PAGE_CATALOG = ("از پیج", "از داخل پیج", "از کانال", "از اینستا")
HIDE_PRICE_RE = re.compile(r"قیمت\s*نزن|بدون قیمت|قیمت\s*نذار|قیمت\s*نگذار|پنهان.{0,12}قیمت|قیمت.{0,12}پنهان")


def _wants_page_catalog(text: str) -> bool:
    return any(token in (text or "") for token in PAGE_CATALOG)


def _wants_hide_prices(text: str) -> bool:
    return bool(HIDE_PRICE_RE.search(text or ""))


def _bump_pending(shop: dict) -> dict:
    shop["pendingBuild"] = int(shop.get("pendingBuild") or 0) + 1
    return _save_shop(shop)


def _catalog_from_page_reply() -> str:
    from app.services import channel_scan_service, storefront_service

    products = [row for row in storefront_service.list_products().get("products") or [] if row.get("source")]
    scan = channel_scan_service.get_scan()
    handle = str(products[0].get("sourceHandle") or "") if products else ""
    if not handle:
        accounts = scan.get("accounts") if isinstance(scan.get("accounts"), list) else []
        if accounts:
            handle = str(accounts[0].get("handle") or "")
    if not products:
        if handle:
            channel_scan_service.start_scan([{"platform": "instagram", "handle": handle}])
            return f"کالاهای {handle} را دوباره از پیج می‌خوانم. بعد بیلد بزن تا روی سایت بیایند."
        return "هنوز پیجی برای اسکن ثبت نشده."
    titles = "، ".join(str(row.get("title") or "") for row in products[:12])
    return f"{len(products)} مدل از پیج {handle} در کاتالوگ است: {titles}. روی سایت نمی‌آیند تا بیلد بزنی."


def _catalog_add_reply(text: str) -> str | None:
    from app.services import storefront_service
    from app.services.shop_intent_service import catalog_add

    parsed = catalog_add(text)
    if parsed is None:
        return None
    title = str(parsed.get("title") or "").strip()
    price = int(parsed.get("price") or 0)
    if len(title) < 2:
        return "نام کالا چیست؟"
    if price <= 0:
        return "قیمت تومان را هم بگو تا در کاتالوگ بنویسم."
    saved = storefront_service.add_product(
        title=title,
        price=price,
        stock=1,
        sku="chat",
        source="chat",
        category="کالا",
    )
    product = saved.get("product") if isinstance(saved, dict) else {}
    stored_title = str((product or {}).get("title") or "")
    stored_price = int((product or {}).get("price") or 0)
    found = any(
        str(row.get("title") or "") == stored_title and int(row.get("price") or 0) == stored_price
        for row in (storefront_service.list_products().get("products") or [])
    )
    if not found or stored_price != price:
        return "کالا در کاتالوگ نوشته نشد. یک بار دیگر بگو."
    return f"«{stored_title}» با قیمت {stored_price} تومان در کاتالوگ است."


def _add_media_product(text: str, media: dict) -> str:
    from app.services import channel_scan_service, chat_media_service, storefront_service

    blob = text or ""
    price, note = channel_scan_service.parse_caption_price(blob)
    title = channel_scan_service.product_title_from_caption(blob) or ""
    if not title:
        cleaned = re.sub(r"قیمت.*", "", blob).strip()
        cleaned = re.sub(r"[\d۰-۹./،,]{3,}", "", cleaned).strip()
        title = cleaned[:36] if len(cleaned) >= 3 else "کالا"
    image = ""
    name = str(media.get("name") or "")
    if name:
        src = chat_media_service.resolve(name)
        dest = channel_scan_service._scan_dir() / Path(name).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        image = dest.name
    storefront_service.add_product(
        title=title,
        price=price,
        stock=1,
        sku="chat",
        image=image,
        source="chat",
        description=blob[:400],
        category=channel_scan_service._category_from_text(blob)
        or next(
            (
                str(row.get("category") or "").strip()
                for row in (storefront_service.list_products().get("products") or [])
                if str(row.get("category") or "").strip()
            ),
            "کالا",
        ),
        priceNote=note,
    )
    amount = f"{price:,} تومان".replace(",", "٬") if price else (note or "بدون قیمت")
    return f"«{title}» با {amount} به کاتالوگ اضافه شد. بیلد بزن تا روی سایت بیاید."


def _visible_fa_bits(blob: str, limit: int = 18) -> list[str]:
    seen: list[str] = []
    for expr in (FA_NODE, FA_QUOTED):
        for match in expr.findall(blob or ""):
            value = re.sub(r"\s+", " ", match).strip()
            if len(value) < 2 or value in seen:
                continue
            seen.append(value)
            if len(seen) >= limit:
                return seen
    return seen


def _page_copy_blobs(root: Path, view_path: str) -> list[str]:
    from app.services.shop_edit_service import _page_file, safe_view_path

    blobs: list[str] = []
    brand = root / "lib" / "brand.ts"
    if brand.is_file():
        blobs.append(brand.read_text(encoding="utf-8")[:2500])
    page_path = _page_file(root, safe_view_path(view_path or "/"))
    if page_path is None:
        return blobs
    page = page_path.read_text(encoding="utf-8")[:4000]
    blobs.append(page)
    for rel in COMPONENT_IMPORT.findall(page)[:4]:
        extra = root / "components" / Path(rel).with_suffix(".tsx")
        if extra.is_file():
            blobs.append(extra.read_text(encoding="utf-8")[:2500])
    return blobs


def _storefront_capability_notes(shop: dict, view_path: str = "") -> str:
    from app.services.shop_edit_service import build_dir_for

    root = build_dir_for(shop)
    if root is None:
        return ""
    notes: list[str] = []
    login = root / "app" / "login" / "page.tsx"
    if not login.is_file():
        notes.append("در فایل‌های این فروشگاه صفحهٔ /login نیست.")
    else:
        source = login.read_text(encoding="utf-8")[:8000]
        dest = "/"
        match = re.search(r"router\.push\(['\"]([^'\"]+)['\"]\)", source)
        if match:
            dest = match.group(1)
        if "/api/sozan/otp/send" in source:
            notes.append(
                "ورود مشتری فروشگاه: صفحه /login با شماره موبایل و کد یک‌بارمصرف "
                f"(/api/sozan/otp/send سپس /api/sozan/otp/verify)؛ بعد از تأیید به {dest} می‌رود."
            )
        else:
            notes.append("ورود مشتری فروشگاه: صفحه /login در فایل‌های سایت هست.")
    bits = _visible_fa_bits("\n".join(_page_copy_blobs(root, view_path)))
    if bits:
        notes.append("متن دیده شده روی همین صفحه: " + "؛ ".join(bits))
    brand = root / "lib" / "brand.ts"
    if brand.is_file():
        from app.services.shop_edit_verify import read_brand_keys

        labels = read_brand_keys(brand.read_text(encoding="utf-8"), ("cartCtaFa", "ctaLabelFa"))
        cart = labels.get("cartCtaFa") or ""
        blob = brand.read_text(encoding="utf-8")
        if cart or "دفتر سفارش" in blob:
            notes.append(
                "سبد سفارش همین الان روی فروشگاه هست. دکمهٔ واقعی: «"
                + (cart or "افزودن به دفتر سفارش")
                + "». نگو سبد در حال توسعه است."
            )
    return "\n".join(notes)


def _interview_turn(text: str, brief: dict) -> str | None:
    from app.services import onboard_service

    if _explicit_build(text) and (onboard_service.brief_ready() or str(brief.get("style") or "").strip()):
        return None
    if _is_aside(text) and not _norm_style(text):
        return None
    if not str(brief.get("style") or "").strip():
        style = _norm_style(text)
        if not style:
            return STYLE_Q
        onboard_service.save_brief({"style": style, "notes": text[:200]})
        return COLOR_Q
    if not str(brief.get("colors") or "").strip():
        if _is_aside(text):
            return None
        if _norm_style(text) and len(text) < 24:
            return COLOR_Q
        onboard_service.save_brief({"colors": text[:80]})
        return FEATURE_Q
    if not str(brief.get("features") or "").strip():
        if _is_aside(text):
            return None
        onboard_service.save_brief({"features": text[:120]})
        return READY_Q
    return None


def _pack(shop: dict, rows: list[dict], assistant: dict | None = None, extra: dict | None = None) -> dict:
    from app.services import channel_scan_service

    build = _factory_status(shop)
    rows = _sync_build_note(rows, shop, build)
    _save_messages(rows)
    payload = {"shop": _public_shop(shop), "messages": rows, "scan": channel_scan_service.scan_status(), "build": build}
    if extra:
        payload.update(extra)
    if assistant is not None:
        payload["assistant"] = assistant
        user = next((row for row in reversed(rows) if row.get("role") == "user"), None)
        if user:
            emit_later(
                kind="chat",
                surface="shop",
                title="shop-user",
                payload={"role": "user", "text": str(user.get("text") or ""), "id": str(user.get("id") or "")},
            )
        emit_later(
            kind="chat",
            surface="shop",
            title="shop-assistant",
            payload={"role": "assistant", "text": str(assistant.get("text") or ""), "id": str(assistant.get("id") or "")},
        )
    return payload


async def chat(text: str, media: dict | None = None, view_path: str = "", view_target: str = "") -> dict:
    from app.services import (
        channel_scan_service,
        chat_media_service,
        onboard_service,
        shop_edit_service,
        shop_workspace_service,
    )

    shop = _refresh_job(_shop())
    raw = text.strip()
    spoken = chat_media_service.spoken_text(raw, media)
    user_msg = {"id": str(uuid4()), "role": "user", "text": spoken, "at": int(time.time())}
    if media:
        user_msg["mediaKind"] = media["kind"]
        user_msg["mediaName"] = media["name"]
    rows = _messages()
    if not rows:
        rows = [{"id": str(uuid4()), "role": "assistant", "text": _opening_text(shop), "at": int(time.time())}]
    rows.append(user_msg)
    brief = onboard_service.get_brief()
    if spoken and not shop_edit_service.looks_like_foreign_payload(spoken):
        shop_workspace_service.record_command(spoken, kind="chat")
    media_only = bool(media) and not raw
    if not media_only and _wants_progress(raw) and not _explicit_build(raw):
        shop = _refresh_job(_shop())
        build = _factory_status(shop)
        reply = _persian_build_text(build) or "هنوز بیلدی شروع نشده. اگر آماده بودی بگو بساز."
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply,
            "at": int(time.time()),
        }
        _append_assistant(rows, assistant)
        return _pack(shop, rows, assistant)
    live = _shop_is_live(shop)
    if not media_only and not live:
        catalog_reply = _catalog_add_reply(raw)
        if catalog_reply is not None:
            assistant = {
                "id": str(uuid4()),
                "role": "assistant",
                "text": catalog_reply,
                "at": int(time.time()),
            }
            _append_assistant(rows, assistant)
            return _pack(shop, rows, assistant)
        guided = _interview_turn(raw, brief)
        if guided is not None:
            assistant = {
                "id": str(uuid4()),
                "role": "assistant",
                "text": guided,
                "at": int(time.time()),
            }
            _append_assistant(rows, assistant)
            return _pack(shop, rows, assistant)
    if not media_only and ((live and _explicit_rebuild(raw)) or (not live and _explicit_build(raw))):
        if not live and not onboard_service.brief_ready():
            missing = []
            if not brief.get("style"):
                missing.append("حس فروشگاه")
            if not brief.get("colors"):
                missing.append("رنگ‌بندی")
            assistant = {
                "id": str(uuid4()),
                "role": "assistant",
                "text": "اول " + " و ".join(missing or ["سبک و رنگ"]) + " را بگو، بعد می‌سازم.",
                "at": int(time.time()),
            }
            _append_assistant(rows, assistant)
            return _pack(shop, rows, assistant)
        result = start_build(
            prompt=raw,
            rebuild=bool(shop.get("slug")),
            revise_only=(False if _wants_full_rebuild(raw) else True) if live else None,
        )
        shop = _refresh_job(_shop())
        if result.get("ok"):
            reply = "ساخت فروشگاه شروع شد. مرحله‌ها را همین‌جا می‌بینی."
        elif result.get("queued"):
            reply = "ساخت قبلی هنوز تمام نشده. مرحله‌ها را همین‌جا می‌بینی."
        else:
            detail = _operator_error(str(result.get("error") or result.get("message") or ""))
            if detail and detail != SAFE_BUILD and "مشکل موقت" not in detail:
                reply = f"ساخت شروع نشد: {detail}"
            else:
                reply = "ساخت الان ممکن نیست، چند دقیقهٔ دیگر."
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply,
            "at": int(time.time()),
        }
        _append_assistant(rows, assistant)
        return _pack(shop, rows, assistant)
    if live and media and str(media.get("kind") or "") == "image" and not shop_edit_service.wants_hero_image(raw):
        reply = _add_media_product(raw, media)
        from app.services import catalog_sync_service

        name = Path(str(media.get("name") or "")).name
        catalog_sync_service.sync_live(changed_images=[name] if name else [])
        shop = _shop()
        assistant = {
            "id": str(uuid4()),
            "role": "assistant",
            "text": reply,
            "at": int(time.time()),
        }
        _append_assistant(rows, assistant)
        return _pack(shop, rows, assistant)
    live = _shop_is_live(shop)
    if live and not media_only:
        from app.services.shop_route_service import classify_turn, shop_state
        from app.services import onboard_service as onboard_mod

        classified = classify_turn(raw, view_target, view_path)
        emit_later(
            kind="intent",
            surface="shop",
            title=f"route-{classified['route']}",
            stage="classified",
            status="ok",
            payload={"route": classified["route"], "evidence": classified["evidence"], "actions": classified["actions"]},
        )
        route = classified["route"]
        evidence = str(classified.get("evidence") or "")
        if route != "answer" or evidence in {"greet", "ask_clarify"}:
            result = {"patched": False, "preview": {}}
            if str(shop.get("status") or "") in BUILD_BUSY:
                reply = "تغییر قبلی هنوز اعمال می‌شود. صبر کن تا پیش‌نمایش تازه شود."
            else:
                result = await shop_edit_service.apply_live_edit(
                    shop, raw, view_path, view_target, classified=classified
                )
                shop = _refresh_job(_shop())
                reply = str(result.get("reply") or "").strip() or "تغییر را روی همین صفحه اعمال می‌کنم."
                if result.get("patched") and result.get("needsRebuild", True) and "بیلد" not in reply:
                    reply = reply.rstrip(". ") + " تغییر در کادر است؛ هر وقت آماده بودی «انتشار تغییرات» را بزن."
            assistant = {
                "id": str(uuid4()),
                "role": "assistant",
                "text": reply,
                "at": int(time.time()),
            }
            _append_assistant(rows, assistant)
            return _pack(
                shop,
                rows,
                assistant,
                extra={
                    "patched": bool(result.get("patched")),
                    "preview": result.get("preview") or {},
                    "turn": {
                        "route": route,
                        "actions": [str(item.get("type") or "") for item in classified["actions"]],
                        "verified": bool(result.get("patched")),
                        "rolledBack": bool(result.get("rolledBack")),
                        "needsRebuild": bool(result.get("needsRebuild")),
                        "state": shop_state(shop, brief_ready=onboard_mod.brief_ready()),
                    },
                },
            )
    build = _factory_status(shop)
    context = (
        f"برند: {shop.get('brand') or 'فروشگاه'}\n"
        f"{onboard_service.brief_block()}\n"
        f"{channel_scan_service.brief_for_shop()}\n"
        f"{shop_workspace_service.instructions_block()}\n"
        f"صفحه پیش‌نمایش: {view_path or '/'}\n"
        f"متن اشاره‌شده: {view_target or '—'}\n"
        f"وضعیت بیلد: {build.get('status') or 'idle'} {build.get('stepLabel') or ''}\n"
        f"نشانی: {build.get('url') or 'هنوز آماده نیست'}\n"
        f"{_storefront_capability_notes(shop, view_path)}\n"
        f"{SHOP_LIVE_HINT if live else SHOP_SETUP_HINT}"
    )
    if media:
        context += f"\nپیوست کاربر: {media['kind']}"
    reply = await complete_chat(
        system=SHOP_SYSTEM + "\n" + context,
        turns=[row for row in rows if str(row.get("id") or "") != BUILD_MSG_ID],
        surface="shop",
    )
    reply = (
        (reply or "").replace("atelier", "لوکس و خلوت").replace("street", "خیابانی").replace("boutique", "بوتیک خانوادگی")
    ).strip()
    if not reply:
        reply = "اینجام. از فروشگاه بپرس یا اگر آماده بودی بگو بساز."
    assistant = {
        "id": str(uuid4()),
        "role": "assistant",
        "text": reply,
        "at": int(time.time()),
    }
    _append_assistant(rows, assistant)
    from app.services.shop_route_service import shop_state
    from app.services import onboard_service as onboard_mod

    return _pack(
        shop,
        rows,
        assistant,
        extra={
            "turn": {
                "route": "answer",
                "actions": ["answer"],
                "verified": True,
                "rolledBack": False,
                "needsRebuild": False,
                "state": shop_state(shop, brief_ready=onboard_mod.brief_ready()),
            }
        },
    )
