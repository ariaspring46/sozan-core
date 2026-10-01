"""Read each contact's Instagram bio once, before the campaign, and keep a few spoken-safe facts.

    python3 enrich_campaign.py                 # enrich ~/local-ai/config/sozan-campaign.json in place
    python3 enrich_campaign.py --dry --max 3   # print what would be saved, write nothing
    python3 enrich_campaign.py --refresh-days 0 --max 50

Each contact gets a "profile" object that sales.load_campaign reads:
    {"ok": true, "name": "...", "city": "...", "bio": "...", "signals": ["dm_orders", ...], "fetchedAt": "..."}

Facts are pulled with fixed rules, never by a model, so the call can only say what the bio says.
Phone numbers, links, e-mails and emoji are removed before anything is saved. Numbers on the
do-not-call file are skipped. Requests are spaced and the run stops on the first rate-limit answer.

Network: Instagram needs the home machine's proxy. Set SOZAN_IG_PROXY to an http(s):// proxy, or to
socks5h://host:port (then curl is used). The endpoints and the app user-agent are the same ones the
hub's page scan uses (backend/app/services/channel_scan_service.py, owner X3); if Instagram changes
them, both places change together.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sales import CAMPAIGN_PATH, DNC_PATH, PROFILE_SIGNALS
from sip import normalize_dial

IG_APP_UA = "Instagram 192.168.2.4.75 Android (33/13; 420dpi; 1080x2400; Google; Pixel 7; panther; panther; en_US; 458229237)"
IG_APP_ID = "936619743392459"
PROFILE_URL = "https://i.instagram.com/api/v1/users/web_profile_info/?username={name}"
FEED_URL = "https://i.instagram.com/api/v1/feed/user/{name}/username/?count=3"
BIO_MAX = 240

_HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_URL = re.compile(r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:ir|com|net|org|shop|store|me)\b\S*)", re.I)
_EMAIL = re.compile(r"\S+@\S+\.\S+")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PHONE = re.compile(r"(?:\+?98|0)?\s*9\d(?:[\s\-]?\d){8}|0\d{2,3}[\s\-]?\d{3,4}[\s\-]?\d{4}|\d{7,}")
_KEEP = re.compile(r"[^\u0600-\u06FF\u200cA-Za-z0-9\s،,.:\-]")
CITIES = (
    "تهران", "مشهد", "اصفهان", "شیراز", "تبریز", "کرج", "قم", "اهواز", "رشت", "کرمانشاه", "کرمان", "یزد",
    "ارومیه", "همدان", "ساری", "قزوین", "زنجان", "اراک", "بندرعباس", "گرگان", "سنندج", "کیش", "بوشهر",
    "اردبیل", "خرم‌آباد", "بابل", "آمل", "کاشان", "سبزوار", "نیشابور", "بیرجند", "زاهدان", "سمنان",
)
LINK_HOSTS_NOT_SITES = ("linktr.ee", "wa.me", "t.me", "instagram.com", "bit.ly", "zil.ink", "linkin.bio")


def clean_bio(text: str) -> str:
    """Bio without phone numbers, links, e-mails or emoji; safe to store and to give the model."""
    raw = str(text or "").translate(_DIGITS)
    raw = _URL.sub(" ", raw)
    raw = _EMAIL.sub(" ", raw)
    raw = _PHONE.sub(" ", raw)
    raw = _KEEP.sub(" ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" -،,.:")
    return raw[:BIO_MAX]


def find_city(*texts: str) -> str:
    blob = " ".join(texts)
    pin = re.search(r"📍\s*([\u0600-\u06FF\u200c]+)", blob)
    if pin and pin.group(1) in CITIES:
        return pin.group(1)
    for city in CITIES:
        if city in blob:
            return city
    return ""


def bio_signals(bio: str, *, external_url: str = "", has_address: bool = False) -> list[str]:
    text = str(bio or "").translate(_DIGITS)
    found: list[str] = []
    if re.search(r"(سفارش|خرید|ثبت|قیمت|استعلام)[^\n]{0,20}(دایرکت|دیرکت|direct|dm)\b", text, re.I) or re.search(
        r"(دایرکت|دیرکت)[^\n]{0,15}(سفارش|خرید)", text
    ):
        found.append("dm_orders")
    if re.search(r"(واتساپ|واتس‌اپ|واتس اپ|whatsapp)", text, re.I):
        found.append("whatsapp_orders")
    if re.search(r"ارسال\s*(به|در)?\s*(سراسر|تمام|کل|همه)|ارسال رایگان|پست پیشتاز|ارسال به همه", text):
        found.append("ships")
    if has_address or re.search(r"(آدرس|حضوری|شعبه|مغازه|پاساژ|بازار|خیابان)", text):
        found.append("physical")
    host = re.sub(r"^https?://", "", external_url or "").split("/")[0].lower()
    if host and not any(host.endswith(bad) for bad in LINK_HOSTS_NOT_SITES):
        found.append("has_site")
    if re.search(r"(عمده|تولیدی|پخش)", text):
        found.append("wholesale")
    if re.search(r"(دست‌ساز|دستساز|دست ساز|هندمید|handmade)", text, re.I):
        found.append("handmade")
    return [item for item in found if item in PROFILE_SIGNALS]


def profile_from_user(user: dict) -> dict:
    """Instagram user object → the stored profile. Pure; no network."""
    raw_bio = str(user.get("biography") or "")
    address = user.get("business_address_json")
    has_address = bool(address and str(address).strip() not in {"", "null", "{}"})
    name = re.sub(r"\s+", " ", _KEEP.sub(" ", str(user.get("full_name") or "").translate(_DIGITS))).strip()
    if _PHONE.search(name.translate(_DIGITS)):
        name = ""
    return {
        "ok": True,
        "name": name[:60],
        "city": find_city(raw_bio, str(user.get("city_name") or ""), str(address or "")),
        "bio": clean_bio(raw_bio),
        "signals": bio_signals(raw_bio, external_url=str(user.get("external_url") or ""), has_address=has_address),
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


class RateLimited(RuntimeError):
    pass


def _get(url: str, proxy: str) -> tuple[int, bytes]:
    headers = {"User-Agent": IG_APP_UA, "Accept": "*/*", "X-IG-App-ID": IG_APP_ID}
    if proxy.startswith("socks"):
        cmd = ["curl", "-s", "--max-time", "20", "-x", proxy, "-w", "\n%{http_code}", url]
        for key, value in headers.items():
            cmd += ["-H", f"{key}: {value}"]
        out = subprocess.run(cmd, capture_output=True, timeout=30).stdout
        body, _, code = out.rpartition(b"\n")
        return int(code or 0), body
    handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy} if proxy else {})]
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def fetch_user(handle: str, proxy: str = "", get=_get) -> dict | None:
    """The Instagram user object for a public handle, or None. Raises RateLimited on 429/401."""
    if not _HANDLE.match(handle or ""):
        return None
    for url, pick in (
        (PROFILE_URL.format(name=handle), lambda p: ((p.get("data") or {}).get("user"))),
        (FEED_URL.format(name=handle), lambda p: p.get("user") or next((i.get("user") for i in p.get("items") or [] if isinstance(i, dict)), None)),
    ):
        status, body = get(url, proxy)
        if status in {401, 429}:
            raise RateLimited(str(status))
        if status >= 400 or not body:
            continue
        try:
            payload = json.loads(body.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            continue
        user = pick(payload) if isinstance(payload, dict) else None
        if isinstance(user, dict) and (user.get("biography") is not None or user.get("full_name")):
            return user
    return None


def _fresh(profile: dict, days: int) -> bool:
    try:
        when = datetime.fromisoformat(str(profile.get("fetchedAt") or ""))
    except ValueError:
        return False
    return days > 0 and datetime.now(timezone.utc) - when < timedelta(days=days)


def _blocked() -> set[str]:
    if not DNC_PATH.is_file():
        return set()
    return {normalize_dial(line) for line in DNC_PATH.read_text(encoding="utf-8").splitlines() if normalize_dial(line)}


def enrich(spec: dict, *, max_fetch: int, refresh_days: int, proxy: str, get=_get, sleep=time.sleep) -> dict:
    """Adds/refreshes "profile" on contacts in place. Returns counts."""
    counts = {"fetched": 0, "ok": 0, "missing": 0, "skipped": 0, "rateLimited": 0}
    blocked = _blocked()
    rows = spec.get("contacts") or spec.get("targets") or []
    for row in rows:
        if counts["fetched"] >= max_fetch:
            break
        if not isinstance(row, dict):
            continue
        handle = str(row.get("instagram") or "").strip().lstrip("@")
        phone = normalize_dial(str(row.get("phone") or ""))
        old = row.get("profile") if isinstance(row.get("profile"), dict) else {}
        if not handle or phone in blocked or _fresh(old, refresh_days):
            counts["skipped"] += 1
            continue
        if counts["fetched"]:
            sleep(random.uniform(4.0, 8.0))
        counts["fetched"] += 1
        try:
            user = fetch_user(handle, proxy, get)
        except RateLimited:
            counts["rateLimited"] += 1
            break
        if user is None:
            row["profile"] = {"ok": False, "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            counts["missing"] += 1
            continue
        row["profile"] = profile_from_user(user)
        counts["ok"] += 1
    return counts


def _write(path: Path, spec: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(CAMPAIGN_PATH))
    parser.add_argument("--max", type=int, default=40, help="pages to fetch this run")
    parser.add_argument("--refresh-days", type=int, default=14)
    parser.add_argument("--dry", action="store_true", help="print, do not write")
    args = parser.parse_args()
    path = Path(args.file)
    if not path.is_file():
        print(f"campaign file not found: {path}")
        return 2
    spec = json.loads(path.read_text(encoding="utf-8"))
    counts = enrich(spec, max_fetch=args.max, refresh_days=args.refresh_days, proxy=os.environ.get("SOZAN_IG_PROXY", "").strip())
    print(json.dumps(counts))
    if args.dry:
        for row in (spec.get("contacts") or [])[:5]:
            profile = row.get("profile") or {}
            print(row.get("instagram"), json.dumps({k: profile.get(k) for k in ("ok", "name", "city", "signals")}, ensure_ascii=False))
        return 0
    _write(path, spec)
    return 1 if counts["rateLimited"] else 0


if __name__ == "__main__":
    sys.exit(main())
