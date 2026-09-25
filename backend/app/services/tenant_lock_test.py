from __future__ import annotations

import ast
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services.tenant_lock import tenant_file_lock
from app.state_store import tenant_scope

_ROOT = Path(__file__).resolve().parents[1]
_SKIP = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _lock_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    if called != "tenant_file_lock":
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return "shop"
    return node.args[0].value


def _shallow(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SKIP):
            continue
        yield child
        yield from _shallow(child)


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def nesting_issues(root: Path) -> list[str]:
    acquirers: dict[tuple[str, str], set[str]] = {}
    trees: dict[Path, ast.AST] = {}
    for path in root.rglob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        trees[path] = tree
        for fn in _functions(tree):
            held: set[str] = set()
            for node in _shallow(fn):
                if isinstance(node, ast.With):
                    for item in node.items:
                        name = _lock_name(item.context_expr)
                        if name:
                            held.add(name)
            if held:
                acquirers[(str(path), fn.name)] = held
    found: list[str] = []
    for path, tree in trees.items():
        for fn in _functions(tree):
            for node in _shallow(fn):
                if not isinstance(node, ast.With):
                    continue
                names = [name for item in node.items if (name := _lock_name(item.context_expr))]
                if not names:
                    continue
                for inner in _shallow(node):
                    if isinstance(inner, ast.Await):
                        found.append(f"{path.name}:{node.lineno} await inside {names[0]}")
                    if isinstance(inner, ast.With):
                        for item in inner.items:
                            again = _lock_name(item.context_expr)
                            if again and again in names:
                                found.append(f"{path.name}:{inner.lineno} nested {again}")
                    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                        callee = acquirers.get((str(path), inner.func.id), set())
                        shared = callee & set(names)
                        if shared:
                            found.append(f"{path.name}:{inner.lineno} reenters {sorted(shared)[0]} via {inner.func.id}")
    return found


class TenantLockTests(unittest.TestCase):
    def test_same_owner_reenters_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(settings, "state_dir", raw), tenant_scope("09120001111"):
            started = time.monotonic()
            with tenant_file_lock("studio"):
                with tenant_file_lock("studio"):
                    value = 1
            self.assertEqual(value, 1)
            self.assertLess(time.monotonic() - started, 1.0)

    def test_source_does_not_nest_locks_or_await_inside_them(self) -> None:
        issues = nesting_issues(_ROOT)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
