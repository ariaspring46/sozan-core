"""Shared paths, env parsing and file hashing for the harness eval. Nothing here imports the app."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
REPO = TOOLS.parent
BACKEND = REPO / "backend"

FIXTURE_PHONE = "09128880001"
FIXTURE_SLUG = "harness-eval"
OWNER = "09135409482"
PROTECTED_PHONES = {"09120007777", "09135409482", "09120000000", "09120000991"}
PROTECTED_SLUGS = {"joahr-froshi", "cahrm-srai-pars", "sozan", "azmaish-panl", "firozeh-sra", "sales-battery"}

PROD_ENV = Path("/home/ubuntu/sozan-core/.env")
PROD_DATA = Path("/home/ubuntu/sozan-core/backend/data")
PROD_MAP = Path("/home/ubuntu/sozan-core/deploy/shop-upstreams.map")
EVAL_HOME = Path.home() / "sozan-eval"
REAL_TURNS = EVAL_HOME / "real-turns"
CASES = HERE / "cases.json"
LOCK = HERE / "cases.lock"

# Files the chat writes on every turn, plus the pending card (a card is checked through the turn's output, not the
# file). A file effect means something else changed.
NOISE_NAMES = {"router-turns.jsonl", "router-turns.1.jsonl", "observe-outbox.jsonl", "router-usage.json", "router-threads.json"}
NOISE_RE = re.compile(r"^router-.*-(messages|busy|pending)\.json$|^router-last-.*\.json$|^shop-messages\.json$|^\.lock-|^\.sozan-undo/|^\.sozan-turn-|\.log$")
NOISE_DIRS = ("shop-workspace/",)


def is_noise(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name in NOISE_NAMES or bool(NOISE_RE.search(rel)) or rel.startswith(NOISE_DIRS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path, prefix: str) -> dict[str, str]:
    """Hashes of every real file under root, keyed `prefix/relative/path`. Noise is left out."""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not is_noise(rel):
            out[f"{prefix}/{rel}"] = sha256(path)
    return out


def load_env(path: Path) -> dict[str, str]:
    """Parses a systemd-style env file: KEY=value lines, optional quotes, no shell expansion."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def git_head() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"_unparsed": True})
    return rows


def count_lines(path: Path) -> int:
    return len(read_jsonl(path))
