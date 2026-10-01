#!/usr/bin/env python3
"""Per-programmer context manifests for 128k-context agents.

Reads tools/agent_context/roles.json and the git file list, then:
  * gives every tracked file exactly one owner (longest pattern wins; foo_test.py follows foo.py),
  * estimates tokens per file and per role (conservative: Persian counts heavier than ASCII),
  * finds what each role calls in other roles' files (Python imports, TS imports, API paths)
    and writes those signatures into the role's manifest, so the agent never opens those files,
  * writes docs/agents/README.md and docs/agents/<ROLE>.md.

  python3 tools/agent_context/build.py           # regenerate docs/agents
  python3 tools/agent_context/build.py --check   # CI: fail on unowned or double-owned files
"""

from __future__ import annotations

import ast
import fnmatch
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROLES_FILE = ROOT / "tools" / "agent_context" / "roles.json"
OUT_DIR = ROOT / "docs" / "agents"
TEXT_EXT = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".jsonl", ".md", ".sh", ".css", ".conf",
    ".service", ".timer", ".yml", ".yaml", ".html", ".txt", ".toml", ".example",
}


# ---------- files and tokens ----------

def git_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line and (ROOT / line).is_file()]


def is_text(path: str) -> bool:
    name = Path(path).name
    return Path(path).suffix in TEXT_EXT or name in {".gitignore", ".env.example"}


def tokens(path: str) -> int:
    """Conservative estimate: ~3.2 ASCII chars or ~1.4 Persian chars per token."""
    if not is_text(path):
        return 0
    try:
        text = (ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_count / 3.2 + (len(text) - ascii_count) / 1.4)


def is_test(path: str) -> bool:
    return path.endswith("_test.py") or Path(path).name.startswith("test_") or "/__tests__/" in path


# ---------- ownership ----------

def _score(pattern: str, path: str) -> int:
    """0 = no match; higher = more specific."""
    if pattern == path:
        return 100_000
    if pattern.endswith("/**"):
        prefix = pattern[:-2]
        return len(prefix) if path.startswith(prefix) else 0
    if any(ch in pattern for ch in "*?["):
        return len(pattern.split("*")[0]) + 1 if fnmatch.fnmatch(path, pattern) else 0
    return 0


def owners_of(path: str, roles: list[dict]) -> tuple[list[str], int]:
    best, who = 0, []
    candidates = [path]
    if path.endswith("_test.py"):
        candidates.append(path[: -len("_test.py")] + ".py")  # a module's test follows the module
    for role in roles:
        score = 0
        for pattern in role["owns"]:
            for cand in candidates:
                hit = _score(pattern, cand)
                if hit and cand != path:
                    hit -= 1  # the sibling rule loses to an explicit pattern for the test itself
                score = max(score, hit)
        if score > best:
            best, who = score, [role["id"]]
        elif score and score == best:
            who.append(role["id"])
    return who, best


def never_read(path: str, patterns: list[str]) -> bool:
    return any(_score(pattern, path) for pattern in patterns)


# ---------- Python interfaces ----------

def module_file(module: str) -> str | None:
    rel = Path("backend", *module.split("."))
    for cand in (rel.with_suffix(".py"), rel / "__init__.py"):
        if (ROOT / cand).is_file():
            return cand.as_posix()
    return None


def python_uses(path: str) -> dict[str, set[str]]:
    """{dependency file: {names used}} for one module, including lazy in-function imports."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    uses: dict[str, set[str]] = defaultdict(set)
    alias: dict[str, tuple[str, str]] = {}  # local name -> (file, name or "")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "app":
            for item in node.names:
                sub = module_file(f"{node.module}.{item.name}")
                if sub:  # "from app.services import llm" imports a module
                    alias[item.asname or item.name] = (sub, "")
                    continue
                target = module_file(node.module)
                if target:
                    uses[target].add(item.name)
                    alias[item.asname or item.name] = (target, item.name)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name.split(".")[0] == "app":
                    target = module_file(item.name)
                    if target:
                        alias[item.asname or item.name.split(".")[-1]] = (target, "")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in alias:
            target, name = alias[node.value.id]
            uses[target].add(f"{name}.{node.attr}" if name else node.attr)
    for target, name in alias.values():
        uses.setdefault(target, set())
    uses.pop(path, None)
    return uses


def _first_doc_line(node: ast.AST) -> str:
    doc = ast.get_docstring(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
    return (doc or "").strip().splitlines()[0][:110] if doc else ""


def _func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"


_SIG_CACHE: dict[str, dict] = {}


def _defs(path: str) -> dict:
    if path not in _SIG_CACHE:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        table: dict[str, ast.AST] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                table[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        table[target.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                table[node.target.id] = node
        _SIG_CACHE[path] = table
    return _SIG_CACHE[path]


def _member(cls: ast.ClassDef, attr: str) -> str:
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == attr:
            return _func_sig(node).replace("def ", f"def {cls.name}.", 1)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == attr:
            return f"{cls.name}.{ast.unparse(node)[:140]}"
    return ""


def signature(path: str, name: str) -> str:
    table = _defs(path)
    head, _, attr = name.partition(".")
    node = table.get(head)
    if node is None:
        return f"{name}  # not found at module top level"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        doc = _first_doc_line(node)
        return _func_sig(node) + (f"  # {doc}" if doc else "")
    if isinstance(node, ast.ClassDef):
        if attr:
            return _member(node, attr) or f"{name}"
        init = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        line = f"class {node.name}({bases})" if bases else f"class {node.name}"
        if init:
            line += f"  # __init__({ast.unparse(init.args)})"
        return line
    text = ast.unparse(node)
    if attr and isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
        cls = table.get(ast.unparse(node.value.func))
        if isinstance(cls, ast.ClassDef):
            return _member(cls, attr) or name
    return text if len(text) <= 160 else text[:157] + "..."


# ---------- frontend ----------

TS_IMPORT = re.compile(r'import\s+(type\s+)?(?:\{([^}]*)\}|(\w+))?[^"\']*from\s+["\'](@/[^"\']+|\.{1,2}/[^"\']+)["\']')
API_CALL = re.compile(r'\b(?:api|apiForm|apiFetch|request|fetch)\s*(?:<[^>]*>)?\(\s*[`"\'](?:\$\{[^}]+\})?(/[a-zA-Z][\w\-/]*)')


def resolve_ts(src: str, spec: str, files: set[str]) -> str | None:
    base = Path("frontend") if spec.startswith("@/") else Path(src).parent
    rel = spec[2:] if spec.startswith("@/") else spec
    stem = (base / rel).as_posix()
    stem = str(Path(stem).resolve().relative_to(ROOT.resolve())) if ".." in stem else stem
    for cand in (stem, stem + ".ts", stem + ".tsx", stem + "/index.ts", stem + "/index.tsx"):
        if cand in files:
            return cand
    return None


def ts_uses(path: str, files: set[str]) -> dict[str, set[str]]:
    text = (ROOT / path).read_text(encoding="utf-8")
    uses: dict[str, set[str]] = defaultdict(set)
    for match in TS_IMPORT.finditer(text):
        target = resolve_ts(path, match.group(4), files)
        if not target or target == path:
            continue
        names = match.group(2) or match.group(3) or ""
        for raw in names.split(","):
            name = raw.strip().removeprefix("type ").split(" as ")[0].strip()
            if name:
                uses[target].add(name)
        uses.setdefault(target, set())
    return uses


def ts_signature(path: str, name: str) -> str:
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if re.match(rf"export\s+(default\s+)?(async\s+)?(function|const|type|interface|class|let)\s+{re.escape(name)}\b", stripped):
            return stripped.rstrip("{").strip()[:170]
    return f"{name}"


def api_prefixes(files: set[str]) -> dict[str, str]:
    table: dict[str, str] = {}
    for path in files:
        if path.startswith("backend/app/api/") and path.endswith(".py") and not is_test(path):
            text = (ROOT / path).read_text(encoding="utf-8")
            for prefix in re.findall(r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']+)["\']', text):
                table[prefix.rstrip("/")] = path
            for route in re.findall(r'@router\.\w+\(\s*["\'](/[^"\']*)["\']', text):
                if "APIRouter(prefix" not in text:
                    table.setdefault("/" + route.strip("/").split("/")[0], path)
    return table


def api_paths(path: str) -> set[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    return {m.group(1).rstrip("/") for m in API_CALL.finditer(text)}


def api_file(endpoint: str, prefixes: dict[str, str]) -> str | None:
    best = ""
    for prefix in prefixes:
        if (endpoint == prefix or endpoint.startswith(prefix + "/")) and len(prefix) > len(best):
            best = prefix
    return prefixes.get(best) if best else None


# ---------- build ----------

def build(check_only: bool) -> int:
    config = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
    roles = config["roles"]
    budget = config["budget"]
    never = config["never_read"]
    files = git_files()
    fileset = set(files)

    owner: dict[str, str] = {}
    problems: list[str] = []
    for path in files:
        who, _ = owners_of(path, roles)
        if not who:
            problems.append(f"بی‌صاحب: {path}")
        elif len(who) > 1:
            problems.append(f"دو صاحب ({', '.join(who)}): {path}")
        else:
            owner[path] = who[0]
    for role in roles:
        for path in role.get("core", []):
            if owner.get(path) != role["id"]:
                problems.append(f"{role['id']}: فایل هسته مال خودش نیست یا وجود ندارد: {path}")

    size = {path: tokens(path) for path in files}
    owned: dict[str, list[str]] = defaultdict(list)
    for path, rid in owner.items():
        owned[rid].append(path)

    # what each role reads from others, and what others read from it
    needs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    needed_by: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    endpoints: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    prefixes = api_prefixes(fileset)
    for path, rid in owner.items():
        if is_test(path) or never_read(path, never):
            continue
        uses: dict[str, set[str]] = {}
        if path.startswith("backend/") and path.endswith(".py"):
            try:
                uses = python_uses(path)
            except SyntaxError:
                problems.append(f"پارس نشد: {path}")
        elif path.startswith("frontend/") and path.endswith((".ts", ".tsx")):
            uses = ts_uses(path, fileset)
            for endpoint in api_paths(path):
                target = api_file(endpoint, prefixes)
                if target and owner.get(target) and owner[target] != rid:
                    endpoints[rid][target].add(endpoint)
        for dep, names in uses.items():
            dep_owner = owner.get(dep)
            if dep_owner and dep_owner != rid:
                needs[rid][dep].update(names)
                for name in names or {"*"}:
                    needed_by[dep_owner][f"{dep}::{name}"].add(rid)

    report_rows = []
    for role in roles:
        rid = role["id"]
        paths = sorted(owned[rid])
        rare_patterns = role.get("rare", [])
        rare = [p for p in paths if not is_test(p) and not never_read(p, never) and any(_score(r, p) for r in rare_patterns)]
        src = [p for p in paths if not is_test(p) and not never_read(p, never) and p not in rare]
        tests = [p for p in paths if is_test(p)]
        skipped = [p for p in paths if never_read(p, never)]
        core = role.get("core", [])
        row = {
            "id": rid,
            "title": role["title"],
            "core": sum(size.get(p, 0) for p in core),
            "src": sum(size[p] for p in src),
            "rare": sum(size[p] for p in rare),
            "tests": sum(size[p] for p in tests),
            "skipped": sum(size[p] for p in skipped),
            "iface": 0,
        }
        if rid != "OWNER":
            if row["core"] > budget["core_max"]:
                problems.append(f"{rid}: هستهٔ {row['core']} توکن از سقف {budget['core_max']} بیشتر است")
            if row["src"] > budget["owned_source_max"]:
                print(f"هشدار {rid}: سورس فعال {row['src']} توکن، بیشتر از {budget['owned_source_max']}", file=sys.stderr)
        report_rows.append(row)
        if not check_only:
            text = role_doc(role, paths, src, rare, tests, skipped, size, needs[rid], needed_by[rid], endpoints[rid], owner, never, budget, row)
            row["iface"] = tokens_of_text(text)
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            (OUT_DIR / f"{rid}.md").write_text(text, encoding="utf-8")

    if not check_only:
        (OUT_DIR / "README.md").write_text(index_doc(report_rows, roles, budget, never), encoding="utf-8")

    for line in problems:
        print(line, file=sys.stderr)
    for row in report_rows:
        print(f"{row['id']:>5}  هسته {row['core']:>6}  فعال {row['src']:>6}  کم‌کاربرد {row.get('rare', 0):>6}  تست {row['tests']:>6}  نخوان {row['skipped']:>7}  مانیفست {row['iface']:>5}")
    return 1 if problems else 0


def tokens_of_text(text: str) -> int:
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return int(ascii_count / 3.2 + (len(text) - ascii_count) / 1.4)


def _k(value: int) -> str:
    return f"{value / 1000:.1f}k"


def role_doc(role, paths, src, rare, tests, skipped, size, needs, needed_by, endpoints, owner, never, budget, row) -> str:
    rid = role["id"]
    lines = [
        f"# {rid} — {role['title']}",
        "",
        "<!-- ساخته‌شده با tools/agent_context/build.py؛ دستی ویرایش نکنید. مرزها در tools/agent_context/roles.json -->",
        "",
        role.get("summary", ""),
        "",
    ]
    if role.get("report"):
        lines += [f"**گزارش:** فقط به ته `{role['report']}` اضافه کن (`cat >>`)؛ برای دیدن آخرین پیام‌ها فقط `tail -n 60`."]
    if rid == "OWNER":
        lines += ["", "## فایل‌ها", ""] + [f"- `{p}` ({_k(size[p])})" for p in paths if not p.startswith((".zcode/", ".cursor/", "docs/festival/", "docs/ui-audit-live/"))]
        return "\n".join(lines) + "\n"
    lines += [
        "",
        "## بودجه (توکن تخمینی)",
        "",
        "| بخش | توکن |",
        "|---|---|",
        f"| هسته (اول هر کار بخوان) | {_k(row['core'])} |",
        f"| سورس فعال (بخوان فقط آنچه کار لازم دارد) | {_k(row['src'])} |",
        f"| سورس کم‌کاربرد (rare؛ فقط اگر کار نامش را برد) | {_k(row['rare'])} |",
        f"| تست‌های مالکیت (فقط تست مربوط را بخوان) | {_k(row['tests'])} |",
        f"| مال تو ولی هرگز نخوان | {_k(row['skipped'])} |",
        f"| سقف کانتکست / رزرو عامل | {_k(budget['context'])} / {_k(budget['reserved_for_agent'])} |",
        "",
        "## هسته",
        "",
    ]
    lines += [f"- `{p}` ({_k(size.get(p, 0))})" for p in role.get("core", [])]
    lines += ["", "## مال تو (فقط همین‌ها را ویرایش کن)", ""]
    groups: dict[str, list[str]] = defaultdict(list)
    for p in src:
        groups[str(Path(p).parent)].append(p)
    for folder in sorted(groups):
        items = ", ".join(f"`{Path(p).name}` ({_k(size[p])})" for p in sorted(groups[folder], key=lambda q: -size[q]))
        lines.append(f"- `{folder}/`: {items}")
    if rare:
        lines += ["", "**کم‌کاربرد (rare)** — مال تو، ولی فقط وقتی کار صریحاً به آن اشاره کند بخوان:", ""]
        rgroups: dict[str, list[str]] = defaultdict(list)
        for p in rare:
            top = p.split("/")[0]
            key = top if top in {"promo-engine", "brand", "campaigns", "deploy", "scripts"} else str(Path(p).parent)
            rgroups[key].append(p)
        for key in sorted(rgroups):
            items = rgroups[key]
            if len(items) > 6:
                lines.append(f"- `{key}/` ({len(items)} فایل، {_k(sum(size[p] for p in items))})")
            else:
                lines.append(f"- `{key}/`: " + ", ".join(f"`{Path(p).name}` ({_k(size[p])})" for p in items))
    if tests:
        lines += ["", "**تست‌ها:** " + ", ".join(f"`{Path(p).name}`" for p in tests)]
    if skipped:
        lines += ["", "**مال تو ولی نخوان** (ساختگی/حجیم؛ فقط با اسکریپت عوض کن): " + ", ".join(f"`{p}` ({_k(size[p])})" for p in skipped)]

    if role.get("external"):
        lines += ["", "## قرارداد بیرون از import (HTTP، فایل، سرویس)", ""] + [f"- {item}" for item in role["external"]]
    lines += [
        "",
        "## آنچه از دیگران لازم داری (فایلشان را باز نکن؛ امضا همین‌جاست)",
        "",
    ]
    if not needs:
        lines.append("هیچ.")
    for dep in sorted(needs, key=lambda d: (owner[d], d)):
        names = sorted(n for n in needs[dep] if n)
        lines.append(f"**`{dep}`** — صاحب: {owner[dep]}")
        if not names:
            lines.append("- (کل ماژول import می‌شود؛ فقط نام‌های بالا)")
            continue
        lines.append("```")
        for name in names:
            sig = signature(dep, name) if dep.endswith(".py") else ts_signature(dep, name)
            lines.append(sig)
        lines.append("```")
    if endpoints:
        lines += ["", "**API بک‌اند که صفحه‌هایت صدا می‌زنند** (شکل پاسخ را از صاحبش بپرس، فایل را کامل نخوان):", ""]
        for target in sorted(endpoints):
            lines.append(f"- {', '.join(f'`{e}`' for e in sorted(endpoints[target]))} ← `{target}` ({owner[target]})")

    lines += [
        "",
        "## قرارداد تو با دیگران (بدون هماهنگی امضا را عوض نکن)",
        "",
    ]
    if not needed_by:
        lines.append("هیچ‌کس مستقیم صدا نمی‌زند.")
    contract: dict[str, list[str]] = defaultdict(list)
    for key, users in needed_by.items():
        path, name = key.split("::", 1)
        if name != "*":
            contract[path].append(f"`{name}` ← {', '.join(sorted(users))}")
    for path in sorted(contract):
        lines.append(f"- `{path}`: " + "؛ ".join(sorted(contract[path])))

    lines += [
        "",
        "## قاعدهٔ مصرف توکن",
        "",
        "1. اول هر کار: همین فایل + فقط فایل‌های «هسته» که به کار مربوط است. فایل بزرگ را با `grep -n` پیدا کن و با `sed -n 'a,bp'` فقط بازه را بخوان.",
        "2. فایل دیگران را باز نکن؛ امضای لازم بالاست. اگر امضا کافی نبود، از صاحبش در فایل گزارشش بپرس.",
        "3. تست: فقط ماژول خودت، مثلاً `python -m unittest app.services.<module>_test`؛ سوییت کامل فقط پیش از PR، و فقط خلاصه: `... 2>&1 | tail -5`.",
        "4. هرگز این‌ها را نخوان: " + ", ".join(f"`{p}`" for p in never) + ".",
        "5. خروجی ابزار را کوتاه کن: `| head`، `| tail`، `git diff --stat` پیش از `git diff`.",
    ]
    return "\n".join(lines) + "\n"


def index_doc(rows, roles, budget, never) -> str:
    lines = [
        "# مرز کار ۸ برنامه‌نویس (عامل ۱۲۸k)",
        "",
        "<!-- ساخته‌شده با tools/agent_context/build.py؛ دستی ویرایش نکنید -->",
        "",
        "هر فایل گیت دقیقاً یک صاحب دارد (`roles.json`). هر عامل فقط فایل نقش خودش در این پوشه را می‌خواند؛ امضای فایل‌های دیگران داخل همان فایل است.",
        "",
        "| نقش | عنوان | هسته | سورس فعال | کم‌کاربرد | تست | مانیفست | گزارش |",
        "|---|---|---|---|---|---|---|---|",
    ]
    reports = {role["id"]: role.get("report", "") for role in roles}
    for row in rows:
        if row["id"] == "OWNER":
            continue
        lines.append(
            f"| [{row['id']}]({row['id']}.md) | {row['title']} | {_k(row['core'])} | {_k(row['src'])} | {_k(row['rare'])} | {_k(row['tests'])} | {_k(row['iface'])} | `{reports[row['id']]}` |"
        )
    lines += [
        "",
        f"اعداد توکن تخمینی و محافظه‌کارانه‌اند. سقف کانتکست {_k(budget['context'])}؛ {_k(budget['reserved_for_agent'])} برای پرامپت سیستم و ابزار عامل کنار گذاشته شده؛ هستهٔ هر نقش زیر {_k(budget['core_max'])} است.",
        "",
        "**هیچ عاملی نخواند:** " + ", ".join(f"`{p}`" for p in never),
        "",
        "تغییر مرز: `roles.json` را عوض کن، `python3 tools/agent_context/build.py` بزن. CI با `--check` فایل بی‌صاحب یا دوصاحبه را رد می‌کند.",
        "",
        "## شروع هر عامل (کم‌مصرف)",
        "",
        "پیام اول هر نشست، فقط همین (به‌جای «پروژه را بررسی کن»):",
        "",
        "```",
        "تو برنامه‌نویس <ID> هستی. فقط docs/agents/<ID>.md را بخوان و طبق آن کار کن.",
        "کار: <یک جمله>. فایل‌های مربوط: <۱ تا ۳ مسیر از بخش «مال تو»>.",
        "بیرون از «مال تو» چیزی را ویرایش نکن؛ اگر لازم شد در فایل گزارشت بنویس.",
        "```",
        "",
        "## قاعدهٔ گزارش",
        "",
        "- هر نقش فایل گزارش خودش را دارد (ستون «گزارش»). `talk.md` (حدود ۲۹۰k توکن، بیشتر از کل کانتکست) بایگانی است و هیچ عاملی آن را نمی‌خواند.",
        "- افزودن فقط با `cat >> <file> <<'EOF'`؛ خواندن فقط `tail -n 60`. هرگز کل فایل گزارش را نخوان یا بازنویسی نکن.",
        "- درخواست از نقش دیگر: یک بند `## <ID من> → <ID او>: …` ته فایل گزارش **او**.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(build(check_only="--check" in sys.argv))
