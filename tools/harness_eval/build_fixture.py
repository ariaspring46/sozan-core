#!/usr/bin/env python3
"""Builds the eval shop for real, once, through the same code a seller's build uses.

  python3 tools/harness_eval/build_fixture.py plan     # lists everything a build touches; changes nothing
  python3 tools/harness_eval/build_fixture.py build    # the real build (about 6 minutes, about 1 GB)
  python3 tools/harness_eval/build_fixture.py down     # removes the fixture container, image and build folder

The shop is the fixture tenant (09128880001, slug harness-eval). SOZAN_EDGE_DRY=1 keeps the nginx map and DNS untouched.
The factory has one lock shared by every seller's build, so a seller who starts a build in these minutes is told to wait.
After the build the finished tenant and the site files are frozen in ~/sozan-eval/golden-built; the cases that need a
built shop restore from it. Run with the prod venv.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture  # noqa: E402

SITE_BUILDER = common.SITE_BUILDER
FAST = SITE_BUILDER / "queue" / "fastpath"
BUILD_DIR = common.BUILD_DIR
CONTAINER = common.CONTAINER
GOLDEN_BUILT = common.GOLDEN_BUILT
PORT_BASE, PORT_SPAN = 12370, 80
RESERVED_PORTS = {12383, 12384, 12385, 12386, 12387}
KEEP_OUT = ("node_modules", ".next", ".git")
PROMPT = "فروشگاه آزمون برای سنجش چت: چند کالای ساده با قیمت روشن، بدون عکس و بدون ادعای خاص."
TIMEOUT_S = 25 * 60


def docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def job_ports() -> set[int]:
    ports: set[int] = set()
    for path in (FAST / "jobs").glob("*.json"):
        try:
            ports.add(int(json.loads(path.read_text(encoding="utf-8")).get("port") or 0))
        except (ValueError, OSError):
            continue
    return ports


def bound(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def free_port() -> int:
    used = RESERVED_PORTS | job_ports()
    published = docker("ps", "-a", "--format", "{{.Ports}}").stdout
    for offset in range(PORT_SPAN):
        port = PORT_BASE + offset
        if port not in used and not bound(port) and f":{port}->" not in published:
            return port
    raise RuntimeError("no free storefront port")


def factory_busy() -> bool:
    """The factory's own test: a lock left by a finished or dead run does not block (see cmd_start)."""
    path = FAST / "ACTIVE"
    if not path.is_file():
        return False
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    pid = lock.get("pid")
    return lock.get("status") in {"running", "queued"} and bool(pid) and Path(f"/proc/{int(pid)}").exists()


def preflight() -> list[str]:
    """Reasons not to build. Empty means clear."""
    problems = []
    if factory_busy():
        problems.append("another build holds the factory lock (queue/fastpath/ACTIVE: running, process alive)")
    if docker("ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}").stdout.strip():
        problems.append(f"container {CONTAINER} already exists (run `down` first)")
    if BUILD_DIR.exists():
        problems.append(f"{BUILD_DIR} already exists (run `down` first)")
    if any(json.loads(p.read_text(encoding="utf-8")).get("slug") == common.FIXTURE_SLUG for p in (FAST / "jobs").glob("*.json")):
        problems.append("a job for this slug already exists in queue/fastpath/jobs")
    free = shutil.disk_usage("/").free
    if free < 5 * 2**30:
        problems.append(f"only {free / 2**30:.1f} GB free; the build needs about 1 GB and headroom")
    if not (fixture.GOLDEN / "tenant" / "shop.json").is_file():
        problems.append("no golden fixture yet: run `run.py cases --dev --only R01` once")
    return problems


def plan() -> int:
    port = free_port()
    print("A real build of the fixture shop will touch ONLY these:")
    print(f"  tenant   {fixture.tenant_dir()}            (eval state, not production)")
    print(f"  factory  {FAST}/jobs/fp-<time>.json + ACTIVE lock (shared with every seller's build, about 6 min)")
    print(f"  folder   {BUILD_DIR}   (about 600 MB: node_modules, .next)")
    print(f"  docker   image + container {CONTAINER}, 127.0.0.1:{port}->3000 only")
    print(f"  network  npm registry, the LLM route for the catalog text, nothing else outward")
    print(f"  frozen   {GOLDEN_BUILT}   (tenant + site files, no node_modules)")
    print("It will NOT touch: deploy/shop-upstreams.map, nginx, DNS (SOZAN_EDGE_DRY=1), any other tenant or container.")
    problems = preflight()
    for item in problems:
        print("BLOCKED:", item)
    print("preflight:", "clear" if not problems else "blocked")
    return 1 if problems else 0


def tree_copy(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*KEEP_OUT), symlinks=True)


def build() -> int:
    problems = preflight()
    if problems:
        print("\n".join("BLOCKED: " + item for item in problems))
        return 2
    import run  # noqa: E402  (boot() must come before the app is imported)

    run.boot(fixture.STATE, common.FIXTURE_PHONE)
    port = free_port()
    fixture.restore()
    from app.services import shop_service
    from app.state_store import tenant_scope

    with tenant_scope(common.FIXTURE_PHONE):
        shop = shop_service._shop()
        shop.update({"port": port, "status": "idle"})
        shop_service._save_shop(shop)
        started = time.monotonic()
        result = shop_service.start_build(prompt=PROMPT, rebuild=True, revise_only=False)
        print("start:", json.dumps({k: v for k, v in result.items() if k != "raw"}, ensure_ascii=False)[:300], flush=True)
        job_id = str(result.get("jobId") or "")
        if not result.get("ok") or not job_id:
            print("the factory did not start a build")
            return 3
        job_path = FAST / "jobs" / f"{job_id}.json"
        last = ""
        job: dict = {}
        while time.monotonic() - started < TIMEOUT_S:
            time.sleep(10)
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            phases = job.get("phases") or []
            step = str(phases[-1].get("step") if phases and isinstance(phases[-1], dict) else "")
            if step != last:
                print(f"  {int(time.monotonic() - started):>4}s  {job.get('status')}  {step}", flush=True)
                last = step
            if job.get("status") in {"done", "ready", "failed"}:
                break
        else:
            print("TIMEOUT: the build did not finish; the container is left for inspection (run `down` to remove it)")
            return 4
        if job.get("status") == "failed":
            print("BUILD FAILED:", str(job.get("error"))[:400], "(left for inspection; run `down` to remove)")
            return 5
        shop = shop_service._refresh_job(shop_service._shop())
        print("shop:", json.dumps({k: shop.get(k) for k in ("slug", "status", "url", "port", "urlOk", "jobId")}, ensure_ascii=False))
    elapsed = int(time.monotonic() - started)

    body = ""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=20) as res:
            body = res.read().decode("utf-8", "replace")
            code = res.status
    except OSError as exc:
        code = 0
        print("live check failed:", exc)
    image = docker("inspect", "--format", "{{.Image}}", CONTAINER).stdout.strip()
    GOLDEN_BUILT.mkdir(parents=True, exist_ok=True)
    tree_copy(fixture.tenant_dir(), GOLDEN_BUILT / "tenant")
    tree_copy(BUILD_DIR, GOLDEN_BUILT / "site")
    manifest = {
        "jobId": job_id,
        "port": port,
        "container": CONTAINER,
        "image": image,
        "elapsedSec": elapsed,
        "httpStatus": code,
        "brandOnPage": "آزمون سوزان" in body,
        "siteFiles": sum(1 for p in (GOLDEN_BUILT / "site").rglob("*") if p.is_file()),
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    shutil.copy2(job_path, GOLDEN_BUILT / "job.json")
    (GOLDEN_BUILT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    fixture.mark_clean()
    print("DONE", json.dumps(manifest, ensure_ascii=False))
    return 0 if code == 200 else 6


def down() -> int:
    """Removes only what the build created, by exact name."""
    docker("rm", "-f", CONTAINER)
    docker("rmi", "-f", f"sozan-{common.FIXTURE_SLUG}")
    if BUILD_DIR.exists() and BUILD_DIR.name == common.FIXTURE_SLUG and BUILD_DIR.parent == SITE_BUILDER / "builds":
        shutil.rmtree(BUILD_DIR)
    for path in (FAST / "jobs").glob("*.json"):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("slug") == common.FIXTURE_SLUG:
                path.unlink()
        except (OSError, json.JSONDecodeError):
            continue
    print("removed container, image, build folder and job files of", common.FIXTURE_SLUG)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("plan", "build", "down"))
    args = parser.parse_args()
    return {"plan": plan, "build": build, "down": down}[args.mode]()


if __name__ == "__main__":
    raise SystemExit(main())
