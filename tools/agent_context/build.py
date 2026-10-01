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


NOT_UNIT_TESTS: set[str] = set()


def is_test(path: str) -> bool:
    if path in NOT_UNIT_TESTS:
        return False
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
    NOT_UNIT_TESTS.update(config.get("not_unit_tests", []))
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
            text = text.replace("{SELF}", _k(row["iface"]))
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


GLOBAL_RULES = [
    "Secrets: never print, commit, log or report the contents of `.env`, `*.env`, tokens, API keys, OTP codes or SIP passwords. Never `cat` an env file; check a variable exists with `grep -c '^NAME=' file`.",
    "Real people and money: no real customer message, SMS, call, payment, post or publish from tests, experiments or batteries. Use the test tenant, mocks, the dry gateway (`edge_dry`) or simulators.",
    "Real data: never delete, rewrite or migrate a real seller's files under STATE_DIR on the hub. Tests always run with a temporary `STATE_DIR`.",
    "Scope: edit only files listed under 'Your files'. A change needed in another role's file is a request in that role's report file, never an edit. Only two exceptions: one bullet in `CHANGELOG.md` (§12) and regenerating `docs/agents/` with `tools/agent_context/build.py` (§15).",
    "Contracts: anything under 'Your contract' is called by other roles. Do not rename it or change its parameters or return shape without a request acknowledged in their report file.",
    "Deploy: only X5 deploys to the hub, under `flock /home/ubuntu/.sozan-deploy.lock`. Nobody else SSHes to the hub, restarts its services or edits its files.",
    "Shared machine: never restart llama-swap or the observe service; never touch GPU slots you do not own.",
    "Git: never commit to `main`, never force-push a shared branch, never rewrite someone else's history, never discard uncommitted work you did not write. Run `git status` before any git command that changes files.",
    "Tests: never skip, disable, delete or loosen a test to get green. A failing test is either a real bug or a test that must be fixed for a stated reason.",
    "Product language: everything a seller or customer sees is Persian. Code, identifiers and commit trailers stay as the surrounding code does.",
]


def _code(lines: list[str]) -> list[str]:
    return ["```bash", *[line for line in lines if line], "```"]


def _backend_test_modules(tests: list[str]) -> list[str]:
    mods = []
    for path in tests:
        if path.startswith("backend/") and path.endswith(".py"):
            mods.append(".".join(Path(path[len("backend/"):]).with_suffix("").parts))
    return sorted(mods)


def verify_commands(role: dict, tests: list[str]) -> list[str]:
    rid = role["id"]
    out: list[str] = []
    mods = _backend_test_modules(tests)
    if mods:
        out += [
            "# backend: your modules only (fast loop). Python 3.11; deps: pip install -r backend/requirements.txt",
            "cd backend && STATE_DIR=$(mktemp -d) SOZAN_OBSERVE_OUTBOX=0 PYTHONPATH=. \\",
            "  python3 -m unittest " + " \\\n    ".join(mods) + " 2>&1 | tail -5",
            "",
            "# backend: full suite, once before you open a PR (same command as CI and deploy)",
            "cd backend && STATE_DIR=$(mktemp -d) SOZAN_OBSERVE_OUTBOX=0 PYTHONPATH=. \\",
            "  python3 -m unittest discover -s app -p '*_test.py' -t . 2>&1 | tail -5",
        ]
    tools_tests = [p for p in tests if p.startswith("tools/") and p.endswith("_test.py")]
    for path in tools_tests:
        out += ["", f"# {path}", f"cd {Path(path).parent} && python3 -m unittest {Path(path).stem} 2>&1 | tail -5"]
    if rid == "Z":
        out += ["# voice gateway unit tests (no network, ~1s, expect 'OK')", "cd voice-gateway && python3 -m unittest test_voice 2>&1 | tail -5",
                "", "# simulated call for one persona (home machine only: needs llama-swap and STT; persona ids p01.. in sim_personas.json)", "cd voice-gateway && python3 sim_run.py p01 2>&1 | tail -30"]
    if rid == "Y":
        out += ["", "# sales100 offline structure check (must print: sales100 structure 101/101)", "python3 tools/sales100_battery.py | head -3"]
    if role.get("frontend"):
        out += ["", "# frontend: type-check and build (CI runs it). package-lock.json resolves from registry.npmmirror.com;", "# if your network blocks it, do not edit the lockfile: say so in your report and rely on CI.", "cd frontend && npm ci --no-audit --no-fund >/dev/null && npm run build 2>&1 | tail -15"]
    out += ["", "# ownership and manifests still valid (CI runs this)", "python3 tools/agent_context/build.py --check"]
    return out


def role_doc(role, paths, src, rare, tests, skipped, size, needs, needed_by, endpoints, owner, never, budget, row) -> str:
    rid = role["id"]
    report = role.get("report", "")
    title = role.get("title_en") or role["title"]
    L: list[str] = [
        f"# {rid} — {title}",
        "",
        f"<!-- {role['title']} · generated by tools/agent_context/build.py from roles.json and the code; do not edit by hand -->",
        "",
        f"You are programmer **{rid}** on Sozan (`ariaspring46/sozan-core`). This file is your whole harness: rules, files, the signatures you need from other roles, exact commands. Read it once at session start. Do not read other docs, plans or report files unless a step below or the task tells you to.",
    ]
    if rid == "OWNER":
        L += ["", "## Files", ""] + [f"- `{p}` ({_k(size[p])})" for p in paths if not p.startswith((".zcode/", ".cursor/", "docs/festival/", "docs/ui-audit-live/"))]
        return "\n".join(L) + "\n"

    L += ["", "## 1. Mission", "", role.get("mission", role.get("summary", "")), ""]
    if role.get("plan"):
        L.append("Plan files (owner's, read-only): " + ", ".join(f"`{p}`" for p in role["plan"]) + ". Read only the section a task cites: `grep -n '^## ' <plan>` then `sed -n 'a,bp'`.")
    L += [
        "",
        "## 2. Hard rules (never break; if a task requires breaking one, stop and ask)",
        "",
    ]
    L += [f"{i}. {r}" for i, r in enumerate(GLOBAL_RULES, 1)]
    if role.get("rules"):
        L += ["", f"**{rid}-specific:**", ""]
        L += [f"{i}. {r}" for i, r in enumerate(role["rules"], len(GLOBAL_RULES) + 1)]

    L += [
        "",
        "## 3. Session start (at most 5 tool calls, before touching any file)",
        "",
        *_code([
            "git status --short | head -20          # someone else's uncommitted work? leave it alone",
            "git log --oneline -5",
            "git fetch -q origin main && git log --oneline HEAD..origin/main | head",
            f"tail -n 60 {report}                    # requests addressed to you; never read the whole file" if report else "",
        ]),
        "",
        "Then restate the task in one sentence and list the 1–3 files from §6 you expect to change. If the task needs a file you do not own, go to §13 now instead of starting.",
        "",
        "## 4. Work loop",
        "",
        "1. **Locate** with `grep -n` inside your files only. Read the function you need with `sed -n 'a,bp' file`, not the whole file. Signatures from other roles are in §7; do not open their files.",
        "2. **Plan** in at most 5 lines: what changes, which test proves it.",
        "3. **Reproduce first** for a bug: a failing test (or probe) before the fix.",
        "4. **Edit** the smallest change that does the job. Match the surrounding code: naming, comment density, Persian user-facing text.",
        "5. **Verify** with §11, your modules first, then the full suite once before the PR. Show only the tail of test output.",
        "6. **Review your own diff**: `git diff --stat`, then `git diff -- <file>` per file. Look for a secret, a debug print, a changed contract (§10), a file outside §6.",
        "7. **Commit and report** (§12, §13). Stop when the definition of done (§15) holds. Do not polish beyond the task.",
        "",
        "## 5. Context budget",
        "",
        f"Context window {_k(budget['context'])}; about {_k(budget['reserved_for_agent'])} is used by the agent's own system prompt and tools. This file is ~{{SELF}} tokens. Your core files total {_k(row['core'])}.",
        "",
        "- Never load more than the core plus 2–3 extra files at once. Prefer `grep -n` + `sed -n` ranges over full reads for any file above 5k.",
        "- Cut tool output: `| tail -5`, `| head -40`, `git diff --stat` before `git diff`, `--quiet` flags.",
        "- Do not re-read a file you just edited; do not read a file to 'understand the project'.",
        "- Never read: " + ", ".join(f"`{p}`" for p in never) + ". Report files: only `tail -n 60`, only append.",
        "- If the conversation is getting long, finish the current step, commit, append a short report, and continue in a new session from §3.",
        "",
        "## 6. Your files",
        "",
        "| set | tokens | how to use |",
        "|---|---|---|",
        f"| core | {_k(row['core'])} | the files most tasks touch; read the relevant one first |",
        f"| active | {_k(row['src'])} | yours to edit; read only what the task needs |",
        f"| rare | {_k(row['rare'])} | yours; read only when the task names it |",
        f"| tests | {_k(row['tests'])} | read only the test of the module you change |",
        "",
        "**Core:**",
        "",
    ]
    L += [f"- `{p}` ({_k(size.get(p, 0))})" for p in role.get("core", [])]
    L += ["", "**Active (you may edit):**", ""]
    groups: dict[str, list[str]] = defaultdict(list)
    for p in src:
        groups[str(Path(p).parent)].append(p)
    for folder in sorted(groups):
        items = ", ".join(f"`{Path(p).name}` ({_k(size[p])})" for p in sorted(groups[folder], key=lambda q: -size[q]))
        L.append(f"- `{folder}/`: {items}")
    if rare:
        L += ["", "**Rare (yours; only when the task names it):**", ""]
        rgroups: dict[str, list[str]] = defaultdict(list)
        for p in rare:
            top = p.split("/")[0]
            key = top if top in {"promo-engine", "brand", "campaigns", "deploy", "scripts"} else str(Path(p).parent)
            rgroups[key].append(p)
        for key in sorted(rgroups):
            items = rgroups[key]
            if len(items) > 6:
                L.append(f"- `{key}/` ({len(items)} files, {_k(sum(size[p] for p in items))})")
            else:
                L.append(f"- `{key}/`: " + ", ".join(f"`{Path(p).name}` ({_k(size[p])})" for p in items))
    if tests:
        L += ["", "**Tests:** " + ", ".join(f"`{p}`" for p in tests)]
    if skipped:
        L += ["", "**Yours but never read** (generated or huge; change only through its script): " + ", ".join(f"`{p}` ({_k(size[p])})" for p in skipped)]
    L += ["", "Every other file in the repo belongs to another role (see `docs/agents/README.md`)."]

    L += ["", "## 7. What you use from other roles (do not open their files; signatures are here)", ""]
    if not needs:
        L.append("Nothing.")
    for dep in sorted(needs, key=lambda d: (owner[d], d)):
        names = sorted(n for n in needs[dep] if n)
        L.append(f"**`{dep}`** — owner {owner[dep]}")
        if not names:
            L.append("- module imported; no names used directly")
            continue
        L.append("```")
        for name in names:
            L.append(signature(dep, name) if dep.endswith(".py") else ts_signature(dep, name))
        L.append("```")
    if endpoints:
        L += ["", "**Backend endpoints your pages call** (ask the owner for the response shape; do not read the file):", ""]
        for target in sorted(endpoints):
            L.append(f"- {', '.join(f'`{e}`' for e in sorted(endpoints[target]))} → `{target}` ({owner[target]})")

    L += ["", "## 8. Contracts outside imports (HTTP, files, services)", ""]
    L += [f"- {item}" for item in role.get("external", [])] or ["None."]

    local = role.get("git_mode") == "local"
    L += ["", "## 9. Who reviews and merges", ""]
    if local:
        L.append("Your plan's git rule applies: you rebase on fresh `main` and merge locally only after tests and the stage's acceptance condition pass; nothing is pushed to `origin` until the owner says so. The owner decides product questions and gives every 'go' for live or costly actions.")
    else:
        L.append("A reviewer (ناظر) reviews line by line and is the only one who merges (squash into `main`). You never merge your own PR. The owner decides product questions and gives every 'go' for live or costly actions.")

    L += ["", "## 10. Your contract (others call these; change only after their ack)", ""]
    contract: dict[str, list[str]] = defaultdict(list)
    for key, users in needed_by.items():
        path, name = key.split("::", 1)
        if name != "*":
            contract[path].append(f"`{name}` ← {', '.join(sorted(users))}")
    if not contract:
        L.append("No other role calls your code directly.")
    for path in sorted(contract):
        L.append(f"- `{path}`: " + "; ".join(sorted(contract[path])))

    L += ["", "## 11. Verify (exact commands)", ""] + _code(verify_commands(role, tests))
    if role.get("gates"):
        L += ["", "**Merge gates** (all must hold before you ask for review):", ""] + [f"- {g}" for g in role["gates"]]

    branch = role.get("branch", "")
    L += [
        "",
        "## 12. Git and PR",
        "",
        *_code([
            "git fetch -q origin main",
            (f"git switch -c {branch} origin/main      # new branch per issue" if "<" in branch
             else f"git switch {branch} && git rebase origin/main      # your long-lived branch (create once with: git switch -c {branch} origin/main)") if branch else "",
            "git add <only the files you changed>    # never `git add -A`",
            "git commit -m '<Persian one-line summary>'",
            "" if local else (f"git push -u origin {branch}" if branch else ""),
            "# no push: when tests and the acceptance condition pass, `git rebase origin/main` and tell the owner in your report" if local else "",
        ]),
        "",
        "- One topic per branch and PR. Rebase on fresh `main` before asking for review if `main` moved; resolve conflicts only inside your files.",
        "- Add one bullet for your change under a dated heading at the top of `CHANGELOG.md`: read only `head -20 CHANGELOG.md`, insert with an editor; never rewrite other bullets.",
        ("- No PR unless the owner asks for one; if asked, the body follows `.github/pull_request_template.md` (Persian)." if local else "- PR body follows `.github/pull_request_template.md` (Persian): خلاصه، چرا، فایل‌های اصلی، تست، ریسک، تغییرات این مرحله، ادغام."),
        "- Commit messages and PR text never contain secrets, phone numbers or customer text.",
    ]

    L += ["", "## 13. Reporting and asking other roles", ""]
    if report:
        L += [
            f"Your report file is `{report}`. Append only; never edit earlier text:",
            "",
            *_code([
                f"cat >> {report} <<'EOF'",
                "",
                f"## {rid} — <topic> (<YYYY-MM-DD HH:MM Tehran>)",
                "- done: <what changed, one line per item>",
                "- tests: <command> → <N tests OK / failures>",
                "- branch/PR: <branch or link>",
                "- needs: <request to a role, or 'none'>",
                "EOF",
            ]),
            "",
            "To ask another role, append to **their** report file (see `docs/agents/README.md`) a heading `## " + rid + " → <ROLE>: <topic>` with: the exact file and function, the change you need, why, and how you will test it. Then continue with work that does not depend on it, or stop.",
            "Keep reports short: no pasted code, no full test logs, no secrets, no customer or phone data.",
        ]

    L += [
        "",
        "## 14. Stop and ask (do not guess) when",
        "",
        "- the task needs a file outside §6 or a change to §10;",
        "- a hard rule in §2 would be broken, or something costs real money, contacts real people or touches live data;",
        "- the same test fails twice after a fix you believed in;",
        "- the task is ambiguous in a way that changes what you build;",
        "- you would have to read more than ~40k tokens of files to continue.",
        "",
        f"Write the question in `{report}` (or to the owner in the chat that started you), then stop." if report else "Ask in the chat that started you, then stop.",
        "",
        "## 15. Definition of done",
        "",
        "- The change does what the task says, and only that; every changed file is in §6.",
        "- A test covers the new behaviour or the fixed bug; your module tests and the full suite pass (§11).",
        "- `python3 tools/agent_context/build.py --check` passes. If you changed a signature listed in §10 or an import across roles, you ran `python3 tools/agent_context/build.py` and committed the updated `docs/agents/`.",
        "- Merge gates in §11 hold, or the report says exactly which gate is waiting on whom.",
        "- CHANGELOG bullet, " + ("branch rebased on fresh `main` (not pushed unless the owner said so)" if local else "PR opened from your branch") + ", report appended.",
    ]
    return "\n".join(L) + "\n"


def index_doc(rows, roles, budget, never) -> str:
    reports = {role["id"]: role.get("report", "") for role in roles}
    titles = {role["id"]: role.get("title_en") or role["title"] for role in roles}
    L = [
        "# Sozan — 8 programmers, one harness each",
        "",
        "<!-- generated by tools/agent_context/build.py; do not edit by hand -->",
        "",
        "Every tracked file has exactly one owner (`tools/agent_context/roles.json`). Each agent reads only its own file below: it is the complete harness (rules, files, signatures it needs from others, exact commands).",
        "",
        "| role | area | harness | core | active | rare | tests | report file |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["id"] == "OWNER":
            continue
        L.append(f"| {row['id']} | {titles[row['id']]} | [{row['id']}.md]({row['id']}.md) ({_k(row['iface'])}) | {_k(row['core'])} | {_k(row['src'])} | {_k(row['rare'])} | {_k(row['tests'])} | `{reports[row['id']]}` |")
    L += [
        "",
        f"Token counts are conservative estimates. Context {_k(budget['context'])}; {_k(budget['reserved_for_agent'])} reserved for the agent's own prompt; core kept under {_k(budget['core_max'])}, active source under {_k(budget['owned_source_max'])}.",
        "",
        "## Starting an agent",
        "",
        "First message of every session, nothing more:",
        "",
        "```",
        "You are programmer <ROLE>. Read docs/agents/<ROLE>.md and follow it exactly.",
        "Task: <one sentence>. Likely files: <1-3 paths from its §6>.",
        "```",
        "",
        "If your agent tool loads a project instruction file automatically (CLAUDE.md, AGENTS.md, .cursor rules), point it at the role file instead of copying it, so there is one source.",
        "",
        "## Reports",
        "",
        "- One report file per role (table). `talk.md` (~290k tokens, larger than a whole context) is an archive: no agent reads it.",
        "- Append with `cat >> file <<'EOF'`; read with `tail -n 60`; never rewrite.",
        "- Requests go to the **receiver's** file: `## <FROM> → <TO>: <topic>`.",
        "",
        "## Never read (all roles)",
        "",
        ", ".join(f"`{p}`" for p in never),
        "",
        "## Changing boundaries",
        "",
        "Edit `tools/agent_context/roles.json`, run `python3 tools/agent_context/build.py`, commit `docs/agents/`. CI runs `--check` and fails on an unowned or double-owned file or a core over budget.",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(build(check_only="--check" in sys.argv))
