"""The eval fixture: one dedicated tenant and its site folder, frozen as a golden copy and restored before every case.

Only paths under ~/sozan-eval are ever removed or written here. The seed comes from tools/sales_tenant_reset.py, with
the fixture's own phone and slug. Production tenants are never opened.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import common

# The harness patches subprocess.run during a case; the fixture's own docker calls go through the original.
_RUN = subprocess.run

STATE = common.EVAL_HOME / "state"
GOLDEN = common.EVAL_HOME / "golden"
SITE = common.EVAL_HOME / "site"
READ_LIMIT = 2_000_000


def tenant_dir() -> Path:
    return STATE / "tenants" / common.FIXTURE_PHONE


BUILT = False  # True while the cases that need the really built shop run


def use_built(flag: bool) -> None:
    global BUILT
    BUILT = bool(flag)


def live_roots() -> dict[str, Path]:
    return {"tenant": tenant_dir(), "site": common.BUILD_DIR if BUILT else SITE}


def golden_roots() -> dict[str, Path]:
    if BUILT:
        return {"tenant": common.GOLDEN_BUILT / "tenant", "site": common.GOLDEN_BUILT / "site"}
    return {"tenant": GOLDEN / "tenant", "site": GOLDEN / "site"}


def build_golden() -> None:
    """Seeds the fixture once and freezes it. Needs the app importable and STATE_DIR already pointing at STATE."""
    if (GOLDEN / "tenant" / "shop.json").is_file():
        return
    STATE.mkdir(parents=True, exist_ok=True)
    for name in ("settings.json", "llm-routing.json", "ai-budget.json", "profiles.json"):
        source = common.PROD_DATA / name
        if source.is_file():
            shutil.copy(source, STATE / name)
    sys.path.insert(0, str(common.TOOLS))
    import sales_tenant_reset as seeder

    seeder.PHONE = common.FIXTURE_PHONE
    seeder.seed(STATE, apply=True)
    shop = tenant_dir() / "shop.json"
    row = json.loads(shop.read_text(encoding="utf-8"))
    row.update(
        {
            "brand": "آزمون سوزان",
            "tagline": "فقط آزمون",
            "slug": common.FIXTURE_SLUG,
            "status": "idle",
            "url": f"https://{common.FIXTURE_SLUG}.sozan-core.ir",
        }
    )
    shop.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    SITE.mkdir(parents=True, exist_ok=True)
    GOLDEN.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tenant_dir(), GOLDEN / "tenant", ignore=shutil.ignore_patterns(".lock-*"))
    shutil.copytree(SITE, GOLDEN / "site", dirs_exist_ok=True)


def restore(built: bool = False) -> None:
    """Puts the tenant and the site back to the golden copy. Refuses any path outside the eval home (the built site is
    restored file by file, never removed). `built` also puts the running container back."""
    use_built(built)
    home = common.EVAL_HOME.resolve()
    if home not in tenant_dir().resolve().parents:
        raise RuntimeError(f"refusing to reset {tenant_dir()}: outside {home}")
    roots = golden_roots()
    if tenant_dir().exists():
        shutil.rmtree(tenant_dir())
    shutil.copytree(roots["tenant"], tenant_dir())
    if built:
        restore_built_site()
        return
    if home not in SITE.resolve().parents:
        raise RuntimeError(f"refusing to reset {SITE}: outside {home}")
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(roots["site"], SITE)


# --------------------------------------------------------------------------- the really built shop


def docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return _RUN(["docker", *args], capture_output=True, text=True, timeout=timeout)


def container_image() -> str:
    return docker("inspect", "--format", "{{.Image}}", common.CONTAINER).stdout.strip()


def built_hashes(root: Path) -> dict[str, str]:
    return common.tree_hashes(root, "site")


def clean_image() -> str:
    try:
        return json.loads(common.BUILT_STATE.read_text(encoding="utf-8")).get("image", "")
    except (OSError, json.JSONDecodeError):
        return ""


def mark_clean() -> None:
    common.BUILT_STATE.write_text(json.dumps({"image": container_image(), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")


def built_manifest() -> dict:
    return json.loads((common.GOLDEN_BUILT / "manifest.json").read_text(encoding="utf-8"))


def sync_built_files(root: Path, golden: Path) -> tuple[list[str], list[str]]:
    """Golden files back into the build folder; returns (copied, removed) as `site/...` keys."""
    live, want = built_hashes(root), built_hashes(golden)
    changed = [rel for rel in want if live.get(rel) != want[rel]]
    removed = [rel for rel in live if rel not in want]
    for key in removed:
        (root / key.split("/", 1)[1]).unlink(missing_ok=True)
    for key in changed:
        src, dest = golden / key.split("/", 1)[1], root / key.split("/", 1)[1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return changed, removed


def push_to_container(root: Path, changed: list[str], removed: list[str]) -> None:
    for key in changed:
        rel = key.split("/", 1)[1]
        docker("exec", common.CONTAINER, "mkdir", "-p", f"/app/{Path(rel).parent}")
        docker("cp", str(root / rel), f"{common.CONTAINER}:/app/{rel}")
    for key in removed:
        docker("exec", common.CONTAINER, "rm", "-f", f"/app/{key.split('/', 1)[1]}")


def restore_built_site() -> None:
    """Sync the build folder to the golden files, then the running container: copy changed files back and, when the
    container was rebuilt, rebuild it again from the golden files. A rebuild regenerates some files (the hero images,
    the colour sheet), so the files are synced once more after it. Only exact fixture paths are touched."""
    root, golden = common.BUILD_DIR, common.GOLDEN_BUILT / "site"
    if root.name != common.FIXTURE_SLUG or root.parent != common.SITE_BUILDER / "builds":
        raise RuntimeError(f"refusing to restore {root}")
    changed, removed = sync_built_files(root, golden)
    job = common.FACTORY_JOBS / f"{built_manifest()['jobId']}.json"
    shutil.copy2(common.GOLDEN_BUILT / "job.json", job)
    if clean_image() and container_image() != clean_image():
        rebuild_and_wait()
        changed, removed = sync_built_files(root, golden)
        shutil.copy2(common.GOLDEN_BUILT / "job.json", job)
    push_to_container(root, changed, removed)
    mark_clean()


def rebuild_and_wait(timeout_s: int = 900) -> None:
    """The factory's own revise step (the one a confirmed edit starts), run to the end."""
    manifest = built_manifest()
    script = common.SITE_BUILDER / "tools" / "sozan_factory_fastpath.py"
    job_path = common.FACTORY_JOBS / f"{manifest['jobId']}.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["status"] = "running"
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script), "revise", "--job-id", manifest["jobId"], "--rebuild-only"],
        cwd=str(common.SITE_BUILDER), env=factory_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if proc.poll() is not None:
            break
        time.sleep(5)
    else:
        proc.kill()
        raise RuntimeError("the restore rebuild did not finish")
    state = json.loads(job_path.read_text(encoding="utf-8")).get("status")
    if state not in {"done", "ready"}:
        raise RuntimeError(f"the restore rebuild ended as {state!r}")


def factory_env() -> dict[str, str]:
    from app.services import shop_service
    from app.state_store import tenant_scope

    with tenant_scope(common.FIXTURE_PHONE):
        return shop_service._factory_env()


def golden_hashes() -> dict[str, str]:
    roots = golden_roots()
    return {**common.tree_hashes(roots["tenant"], "tenant"), **common.tree_hashes(roots["site"], "site")}


def live_hashes() -> dict[str, str]:
    roots = live_roots()
    return {**common.tree_hashes(roots["tenant"], "tenant"), **common.tree_hashes(roots["site"], "site")}


def read_value(rel: str, *, golden: bool):
    """Parsed JSON, or text, or None when the file is missing. `rel` is `tenant/...` or `site/...`."""
    key, _, inner = rel.partition("/")
    roots = golden_roots() if golden else live_roots()
    path = roots[key] / inner
    if not path.is_file():
        return None
    if path.stat().st_size > READ_LIMIT:
        return "<too large to read>"
    text = path.read_text(encoding="utf-8", errors="replace")
    if rel.endswith(".json"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text
