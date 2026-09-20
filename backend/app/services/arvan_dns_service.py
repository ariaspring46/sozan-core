from __future__ import annotations

import json
import subprocess
from urllib.parse import urlparse

import httpx

from app.config import settings

API = "https://napi.arvancloud.ir/cdn/4.0"
CNAME_PLAN_LEVEL = 2


def zone() -> str:
    return (settings.arvan_zone or "sozan-core.ir").strip().lower()


def _headers() -> dict[str, str]:
    key = (settings.arvan_api_key or "").strip()
    if not key:
        return {}
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Apikey {key}",
    }


def enabled() -> bool:
    return bool((settings.arvan_api_key or "").strip() and zone())


def public_host(slug: str) -> str:
    name = _label(slug)
    if name == "@":
        return zone()
    if name == "*":
        return f"*.{zone()}"
    return f"{name}.{zone()}" if name else ""


def cname_target(slug: str) -> str:
    host = public_host(slug)
    return f"{host}." if host else ""


def hostname(domain: str) -> str:
    raw = (domain or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").strip().rstrip(".")
    if not host or "." not in host:
        return ""
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for ch in host):
        return ""
    if host.startswith("-") or host.endswith("-") or ".." in host:
        return ""
    if host.endswith(".invalid") or host.endswith(".localhost") or host.endswith(".local"):
        return ""
    return host[:200]


def is_zone_host(host: str) -> bool:
    z = zone()
    value = (host or "").strip().lower().rstrip(".")
    return bool(value) and (value == z or value.endswith("." + z))


def _label(slug: str) -> str:
    raw = (slug or "").strip().lower()
    if raw in {"*", "@"}:
        return raw
    raw = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in raw)
    raw = "-".join(part for part in raw.split("-") if part)
    return raw[:63]


def _origin_ip() -> str:
    return (settings.arvan_origin_ip or "").strip()


def _origin_port() -> int:
    port = int(settings.arvan_origin_port or 80)
    if port <= 0 or port > 65535:
        return 80
    return port


def _client() -> httpx.Client:
    return httpx.Client(timeout=20.0, trust_env=False, headers=_headers())


def _raise(res: httpx.Response) -> None:
    if res.status_code < 400:
        return
    detail = res.text[:240]
    try:
        payload = res.json()
        detail = json.dumps(payload, ensure_ascii=False)[:240]
    except Exception:
        pass
    raise RuntimeError(f"ابرآروان {res.status_code}: {detail}")


def _json(res: httpx.Response) -> dict:
    if res.status_code >= 400 or not res.content:
        return {}
    try:
        payload = res.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def list_records(domain: str | None = None) -> list[dict]:
    if not enabled():
        return []
    target = (domain or zone()).strip().lower()
    if not target:
        return []
    with _client() as client:
        res = client.get(f"{API}/domains/{target}/dns-records")
        _raise(res)
        data = res.json()
    rows = data.get("data") if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else []


def find_record(name: str, typ: str = "a", domain: str | None = None) -> dict | None:
    want = _label(name)
    kind = typ.lower()
    for row in list_records(domain):
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().lower() == want and str(row.get("type") or "").lower() == kind:
            return row
    return None


def _origin_body(name: str) -> dict:
    ip = _origin_ip()
    return {
        "type": "a",
        "name": name,
        "cloud": True,
        "upstream_https": "http",
        "ttl": 120,
        "value": [{"ip": ip, "port": _origin_port(), "weight": 100, "country": ""}],
    }


def _put_or_post_record(client: httpx.Client, domain: str, existing: dict | None, body: dict) -> httpx.Response:
    if existing and existing.get("id"):
        return client.put(f"{API}/domains/{domain}/dns-records/{existing['id']}", json=body)
    return client.post(f"{API}/domains/{domain}/dns-records", json=body)


def ensure_origin_record(domain: str, name: str = "@") -> dict:
    host = hostname(domain) or (domain or "").strip().lower().rstrip(".")
    label = _label(name) or "@"
    ip = _origin_ip()
    if not enabled():
        return {"ok": False, "error": "کلید ابرآروان روی سرور نیست."}
    if not host:
        return {"ok": False, "error": "دامنه نامعتبر است."}
    if not ip:
        return {"ok": False, "error": "IP مبدأ ابرآروان خالی است."}
    existing = find_record(label, "a", domain=host)
    body = _origin_body(label)
    with _client() as client:
        res = _put_or_post_record(client, host, existing, body)
        if res.status_code >= 400:
            slim = dict(body)
            slim["value"] = [{"ip": ip, "port": _origin_port()}]
            res = _put_or_post_record(client, host, existing, slim)
        _raise(res)
        payload = _json(res)
    record = payload.get("data") if isinstance(payload, dict) else {}
    record_id = record.get("id") if isinstance(record, dict) else ""
    return {"ok": True, "host": host, "id": record_id, "name": label}


def ensure_shop_record(slug: str) -> dict:
    name = _label(slug)
    ip = _origin_ip()
    if not enabled():
        return {"ok": False, "error": "کلید ابرآروان روی سرور نیست."}
    if not name:
        return {"ok": False, "error": "اسلاگ دامنه خالی است."}
    if not ip:
        return {"ok": False, "error": "IP مبدأ ابرآروان خالی است."}
    existing = find_record(name, "a")
    body = _origin_body(name)
    with _client() as client:
        res = _put_or_post_record(client, zone(), existing, body)
        if res.status_code >= 400:
            slim = dict(body)
            slim["value"] = [{"ip": ip, "port": _origin_port()}]
            res = _put_or_post_record(client, zone(), existing, slim)
        _raise(res)
        payload = _json(res)
    record = payload.get("data") if isinstance(payload, dict) else {}
    record_id = record.get("id") if isinstance(record, dict) else ""
    return {"ok": True, "host": public_host(name), "id": record_id}


def ensure_app_records() -> dict:
    return {name: ensure_shop_record(name) for name in ("@", "www", "app", "api")}


def start_cname_setup(domain: str, slug: str = "") -> dict:
    host = hostname(domain)
    target = public_host(slug).rstrip(".")
    if not enabled():
        return {"ok": False, "error": "کلید ابرآروان روی سرور نیست."}
    if not host:
        return {"ok": False, "error": "دامنه نامعتبر است."}
    if is_zone_host(host):
        return {"ok": True, "host": host, "skipped": True}
    created = False
    with _client() as client:
        res = client.post(
            f"{API}/domains/dns-service",
            json={
                "domain": host,
                "domain_type": "partial",
                "plan_level": CNAME_PLAN_LEVEL,
                "import_dns_records": False,
            },
        )
        created = res.status_code < 400
        if not created:
            shown = client.get(f"{API}/domains/{host}")
            if shown.status_code >= 400:
                return {"ok": False, "error": _brief(res), "host": host}
        origin = _write_origin(client, host)
        if not origin.get("ok"):
            return {"ok": False, "error": origin.get("error") or "مبدأ ابرآروان ثبت نشد.", "host": host, "created": created}
        if target:
            custom = client.put(
                f"{API}/domains/{host}/cname-setup/custom",
                json={"address": target},
            )
            if custom.status_code >= 400:
                return {"ok": False, "error": _brief(custom), "host": host, "created": created, "origin": origin}
        check = client.get(f"{API}/domains/{host}/cname-setup/check")
        info = _json(check)
        data = info.get("data") if isinstance(info.get("data"), dict) else info
    return {
        "ok": True,
        "host": host,
        "created": created,
        "target": target,
        "origin": origin,
        "status": str((data or {}).get("status") or ""),
        "setup": info,
    }


def _write_origin(client: httpx.Client, host: str) -> dict:
    ip = _origin_ip()
    if not ip:
        return {"ok": False, "error": "IP مبدأ ابرآروان خالی است."}
    listed = client.get(f"{API}/domains/{host}/dns-records")
    rows = []
    if listed.status_code < 400:
        payload = _json(listed)
        raw = payload.get("data") if isinstance(payload, dict) else []
        rows = raw if isinstance(raw, list) else []
    existing = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().lower() in {"@", host} and str(row.get("type") or "").lower() == "a":
            existing = row
            break
    body = _origin_body("@")
    res = _put_or_post_record(client, host, existing, body)
    if res.status_code >= 400:
        slim = dict(body)
        slim["value"] = [{"ip": ip, "port": _origin_port()}]
        res = _put_or_post_record(client, host, existing, slim)
    if res.status_code >= 400:
        return {"ok": False, "error": _brief(res), "host": host}
    payload = _json(res)
    record = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {"ok": True, "host": host, "id": record.get("id") or ""}


def check_cname(domain: str, slug: str) -> dict:
    host = hostname(domain)
    target = public_host(slug).lower().rstrip(".")
    if not host:
        return {"ok": False, "status": "invalid", "detail": "دامنه نامعتبر است."}
    if not target:
        return {"ok": False, "status": "missing-shop", "detail": "اول فروشگاه باید اسلاگ داشته باشد."}
    if is_zone_host(host):
        return {"ok": True, "status": "sozan-host", "detail": "روی دامنه سوزان است.", "host": host, "target": target}
    try:
        answers = _cname_answers(host)
    except Exception as exc:
        return {"ok": False, "status": "lookup-failed", "detail": str(exc)[:160], "host": host, "target": target}
    matched = any(_cname_matches(item, target) for item in answers)
    return {
        "ok": matched,
        "status": "ok" if matched else "waiting",
        "host": host,
        "target": target,
        "seen": answers,
        "detail": "CNAME درست است." if matched else f"در DNS این دامنه CNAME به {target} نیست.",
    }


def _cname_matches(answer: str, target: str) -> bool:
    value = (answer or "").rstrip(".").lower()
    want = (target or "").rstrip(".").lower()
    if not value:
        return False
    if want and value == want:
        return True
    return value.endswith(".cdn.arvancloud.ir")


def _cname_answers(host: str) -> list[str]:
    try:
        import dns.resolver  # type: ignore

        rows = dns.resolver.resolve(host, "CNAME")
        return [str(item.target).rstrip(".") for item in rows]
    except Exception:
        pass
    proc = subprocess.run(["host", "-t", "CNAME", host], capture_output=True, text=True, timeout=8)
    found = []
    for line in (proc.stdout or "").splitlines():
        if "canonical name" in line.lower():
            found.append(line.split()[-1].rstrip("."))
    return found


def _brief(res: httpx.Response) -> str:
    try:
        payload = res.json()
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("errors") or payload)[:200]
    except Exception:
        pass
    return res.text[:200]
