"""Shapes for contracts.json: what a signature line alone cannot show.

Used by build.py. Three kinds of cross-role contract live here:
  * code shape: fields of a class (Pydantic, SQLAlchemy, dataclass) and the full body of a TS type/interface,
  * HTTP routes: every backend route another role calls (panel pages via api(), any file via https://api.sozan-core.ir),
  * state files: runtime JSON files that more than one role reads or writes, with the top-level keys each role touches.

A change in any shape is a contract change: `build.py --check` fails until docs/agents is regenerated,
and the consumer roles are named in an «اعلام قرارداد» line.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

HUB_URL = re.compile(r"https://api\.sozan-core\.ir(/[A-Za-z][\w\-/]*)")
API_CALL = re.compile(r'\b(?:api|apiForm|apiFetch|request|fetch)\s*(?:<[^>]*>)?\(\s*[`"\'](?:\$\{[^}]+\})?(/[a-zA-Z][\w\-/]*)(\$\{)?')
METHODS = {"get", "post", "put", "patch", "delete"}
LOOSE = re.compile(r"\bAny\b|\*\*\w+|(?<![\w\[])dict\b(?!\[)|(?<![\w\[])list\b(?!\[)")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------- code shape ----------

def _func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){ret}"


def class_shape(node: ast.ClassDef) -> str:
    """Fields, then public methods (and __init__), in source order."""
    parts: list[str] = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            parts.append(norm(ast.unparse(item)))
        elif isinstance(item, ast.Assign) and all(isinstance(t, ast.Name) for t in item.targets):
            if not any(t.id.startswith("_") and t.id != "__tablename__" for t in item.targets):
                parts.append(norm(ast.unparse(item)))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not item.name.startswith("_") or item.name == "__init__":
                parts.append(_func_sig(item))
    return "; ".join(parts)


def py_shape(tree_defs: dict, name: str) -> str:
    head, _, attr = name.partition(".")
    node = tree_defs.get(head)
    if isinstance(node, ast.ClassDef) and not attr:
        return class_shape(node)
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and not attr:
        # structure, not copy: string values become "str" so a wording edit is not a contract change
        text = norm(ast.unparse(_Strip().visit(_copy(node))))
        return text if len(text) > 160 or text != norm(ast.unparse(node)) else ""
    return ""


def ts_shape(text: str, name: str) -> str:
    """Full declaration of an exported TS type/interface/function head (not the function body)."""
    m = re.search(rf"^\s*export\s+(default\s+)?(async\s+)?(function|const|type|interface|class|let)\s+{re.escape(name)}\b", text, re.M)
    if not m:
        return ""
    kind = m.group(3)
    i = m.start()
    depth = 0
    seen_paren = False
    out = []
    while i < len(text):
        ch = text[i]
        if ch in "({[<":
            if kind in ("function", "const", "let") and ch == "{" and depth == 0 and seen_paren:
                break  # body starts
            depth += 1
            if ch == "(":
                seen_paren = True
        elif ch in ")}]>":
            if ch == ">" and i > 0 and text[i - 1] == "=":
                out.append(ch)  # arrow
                i += 1
                continue
            depth -= 1
            if depth == 0 and ch == "}" and kind in ("interface", "class"):
                out.append(ch)
                break
        elif depth == 0 and ch == ";":
            break
        elif depth == 0 and ch == "\n" and kind in ("const", "let"):
            break
        elif depth == 0 and ch == "\n" and kind == "type":
            rest = text[i + 1 :].lstrip(" \t")
            if out and out[-1:] != ["="] and not rest.startswith(("|", "&", "{", "(", "[")) and not "".join(out).rstrip().endswith(("=", "|", "&")):
                break
        out.append(ch)
        i += 1
    return norm("".join(out))[:4000]


class _Strip(ast.NodeTransformer):
    def visit_Dict(self, node: ast.Dict) -> ast.Dict:
        node.keys = [k if k is None else k for k in node.keys]
        node.values = [ast.Constant("str") if isinstance(v, ast.Constant) and isinstance(v.value, str) else self.visit(v) for v in node.values]
        return node


def _copy(node: ast.AST) -> ast.AST:
    return ast.parse(ast.unparse(node)).body[0]


def canonical_name(tree_defs: dict, name: str) -> str:
    """`redis_client.get` → `redis_client`: methods of a module-level instance are not separate contracts.
    `settings.x` stays (the instance of a local class: x is a real field)."""
    head, _, attr = name.partition(".")
    if not attr:
        return name
    node = tree_defs.get(head)
    if isinstance(node, ast.Assign):
        value = node.value
        if isinstance(value, ast.Call) and isinstance(tree_defs.get(ast.unparse(value.func)), ast.ClassDef):
            return name
        return head
    return name


def is_loose(signature: str) -> bool:
    return bool(LOOSE.search(signature))


# ---------- HTTP routes ----------

def _route_re(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(path)) + "$")


def _is_depends(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and ast.unparse(node.func) in {"Depends", "Security"}


def backend_routes(root: Path, files: set[str]) -> dict[tuple[str, str], dict]:
    """{(METHOD, full path): {file, signature, shape}} for backend/app/api/*.py and backend/app/main.py."""
    out: dict[tuple[str, str], dict] = {}
    models: dict[str, ast.ClassDef] = {}
    schema = "backend/app/schemas.py"
    if schema in files:
        for node in ast.parse((root / schema).read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                models[node.name] = node
    for path in sorted(files):
        if not (path.endswith(".py") and (path.startswith("backend/app/api/") or path == "backend/app/main.py")) or path.endswith("_test.py"):
            continue
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        local = dict(models)
        prefixes: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                local[node.name] = node
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "APIRouter":
                prefix = next((kw.value.value for kw in node.value.keywords if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)), "")
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        prefixes[target.id] = prefix.rstrip("/")
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in METHODS):
                    continue
                if not (isinstance(dec.func.value, ast.Name) and dec.args and isinstance(dec.args[0], ast.Constant)):
                    continue
                obj = dec.func.value.id
                if obj not in prefixes and obj != "app":
                    continue
                full = (prefixes.get(obj, "") + "/" + str(dec.args[0].value).lstrip("/")).rstrip("/") or "/"
                params = []
                body_models = []
                args = node.args.args + node.args.kwonlyargs
                defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults) + list(node.args.kw_defaults)
                for arg, default in zip(args, defaults):
                    if default is not None and _is_depends(default):
                        continue
                    ann = ast.unparse(arg.annotation) if arg.annotation else ""
                    params.append(f"{arg.arg}: {ann}" if ann else arg.arg)
                    if ann in local:
                        body_models.append(f"{ann} {{{class_shape(local[ann])}}}")
                resp = next((ast.unparse(kw.value) for kw in dec.keywords if kw.arg == "response_model"), "")
                keys: set[str] = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                        keys.update(k.value for k in sub.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
                method = dec.func.attr.upper()
                sig = f"{method} {full}  ({', '.join(params)})" + (f" -> {resp}" if resp else "")
                shape = "; ".join(filter(None, [
                    " ".join(body_models),
                    f"response_model {resp}" if resp else (f"returns keys {{{', '.join(sorted(keys))}}}" if keys else "response untyped"),
                ]))
                out[(method, full)] = {"file": path, "signature": sig, "shape": shape}
    return out


def route_callers(root: Path, owner: dict[str, str], skip) -> dict[str, set[tuple[str, bool]]]:
    """{caller file: {(path, truncated)}} from api('/x') in frontend TS and https://api.sozan-core.ir/x anywhere."""
    out: dict[str, set[tuple[str, bool]]] = defaultdict(set)
    for path in owner:
        if skip(path) or path.startswith("backend/app/api/") or not path.endswith((".py", ".ts", ".tsx", ".js", ".mjs", ".sh")):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if path.startswith("frontend/") and path.endswith((".ts", ".tsx")):
            for m in API_CALL.finditer(text):
                out[path].add((m.group(1).rstrip("/") or "/", bool(m.group(2)) or m.group(1).endswith("/")))
        for m in HUB_URL.finditer(text):
            tail = text[m.end() : m.end() + 2]
            out[path].add((m.group(1).rstrip("/") or "/", tail.startswith(("{", "$"))))
    return out


def match_routes(endpoint: str, truncated: bool, routes: dict) -> list[tuple[str, str]]:
    hits = []
    for key in routes:
        _, full = key
        if _route_re(full).match(endpoint) or (truncated and full.startswith(endpoint.rstrip("/") + "/")):
            hits.append(key)
    if not hits and truncated:  # `/shop/${slug}` with no static tail: the route is `/shop/{slug}`
        hits = [k for k in routes if k[1].startswith(endpoint.rstrip("/") + "/{")]
    return hits


# ---------- state files ----------

def _const_names(tree: ast.Module) -> dict[str, str]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _file_arg(call: ast.Call, consts: dict[str, str]) -> str:
    if not call.args:
        return ""
    a = call.args[0]
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value
    if isinstance(a, ast.Name):
        return consts.get(a.id, "")
    return ""


def _keys_on(func: ast.AST, names: set[str]) -> set[str]:
    keys: set[str] = set()
    for sub in ast.walk(func):
        if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) and sub.value.id in names:
            if isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                keys.add(sub.slice.value)
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and isinstance(sub.func.value, ast.Name):
            if sub.func.value.id in names and sub.func.attr in {"get", "setdefault", "pop"} and sub.args:
                a = sub.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.add(a.value)
        elif isinstance(sub, ast.Dict):
            pass
    return keys


def state_keys(root: Path, path: str) -> dict[str, set[str]]:
    """{state file: top-level keys this module reads or writes}, heuristic:
    names bound to read_json(file), payloads passed to write_json(file, x), and the parameter of the mutate function given to update_json(file, fn)."""
    try:
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
    except SyntaxError:
        return {}
    consts = _const_names(tree)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out: dict[str, set[str]] = defaultdict(set)
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        bound: dict[str, set[str]] = defaultdict(set)  # file -> names
        for sub in ast.walk(func):
            if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call) and ast.unparse(sub.value.func).endswith("read_json"):
                name = _file_arg(sub.value, consts)
                for t in sub.targets:
                    if isinstance(t, ast.Name) and name:
                        bound[name].add(t.id)
            if isinstance(sub, ast.Call) and ast.unparse(sub.func).endswith(("write_json", "update_json")):
                name = _file_arg(sub, consts)
                if not name or len(sub.args) < 2:
                    continue
                payload = sub.args[1]
                if isinstance(payload, ast.Name):
                    if ast.unparse(sub.func).endswith("update_json") and payload.id in funcs:
                        fn = funcs[payload.id]
                        if fn.args.args:
                            out[name] |= _keys_on(fn, {fn.args.args[0].arg})
                    else:
                        bound[name].add(payload.id)
                elif isinstance(payload, ast.Dict):
                    out[name].update(k.value for k in payload.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
        for name, names in bound.items():
            out[name] |= _keys_on(func, names)
    return {k: v for k, v in out.items() if k.endswith((".json", ".jsonl"))}
