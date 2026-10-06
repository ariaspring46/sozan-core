from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from app.state_store import tenant_dir

COMMANDS_KEEP = 80
EDITS_KEEP = 40
INSTRUCTION_CAP = 3500
HIDE_PRICE_RE = re.compile(r"قیمت\s*نزن|بدون قیمت|قیمت\s*نذار|قیمت\s*نگذار|پنهان.{0,12}قیمت|قیمت.{0,12}پنهان")
FROM_PAGE = ("از پیج", "از داخل پیج", "از کانال", "از اینستا")
NO_CLOTHING_RE = re.compile(r"مانتو|شلوار|شومیز")
DELETE_RE = re.compile(r"حذف|نساز|نگذار|نگذار")


def workspace_dir() -> Path:
    path = tenant_dir() / "shop-workspace"
    path.mkdir(parents=True, exist_ok=True)
    (path / "files").mkdir(parents=True, exist_ok=True)
    return path


def reset_workspace() -> None:
    path = tenant_dir() / "shop-workspace"
    if path.is_dir():
        shutil.rmtree(path)


def _read_jsonl(path: Path, keep: int) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-keep:]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def commands() -> list[dict]:
    return _read_jsonl(workspace_dir() / "commands.jsonl", COMMANDS_KEEP)


def record_command(text: str, *, kind: str = "chat") -> None:
    spoken = (text or "").strip()
    if not spoken:
        return
    path = workspace_dir() / "commands.jsonl"
    rows = _read_jsonl(path, COMMANDS_KEEP - 1)
    rows.append({"at": int(time.time()), "kind": kind, "text": spoken[:400]})
    _write_jsonl(path, rows)
    _rewrite_instructions()


def record_edit(*, prompt: str, reply: str, patched: bool, root: Path | None = None) -> None:
    path = workspace_dir() / "edits.jsonl"
    rows = _read_jsonl(path, EDITS_KEEP - 1)
    rows.append(
        {
            "at": int(time.time()),
            "prompt": (prompt or "")[:200],
            "reply": (reply or "")[:200],
            "patched": bool(patched),
        }
    )
    _write_jsonl(path, rows)
    if patched and root is not None:
        capture_site(root)


TRACE_KEEP = 80


def record_trace(
    *,
    prompt: str,
    action: dict,
    verify: dict,
    reply: str,
    files: list[str],
    patched: bool,
    route: str = "",
    turn_id: str = "",
    action_index: int = 0,
    hashes: list | None = None,
) -> None:
    path = workspace_dir() / "trace.jsonl"
    rows = _read_jsonl(path, TRACE_KEEP - 1)
    rows.append(
        {
            "at": int(time.time()),
            "turnId": turn_id,
            "actionIndex": action_index,
            "prompt": (prompt or "")[:200],
            "type": str(action.get("type") or ""),
            "action": {key: action[key] for key in action if key != "reply"},
            "verify": verify,
            "reply": (reply or "")[:240],
            "files": files[:12],
            "hashes": hashes or [],
            "patched": bool(patched),
            "route": route or str(action.get("type") or ""),
        }
    )
    _write_jsonl(path, rows)
    from app.services.observe_client import emit_later

    emit_later(
        kind="edit",
        surface="shop",
        component="shop-edit",
        title=f"edit-{str(action.get('type') or 'action')}",
        status="verified" if patched else "rolled-back",
        stage="action-verified" if patched else "action-failed",
        turn_id=turn_id,
        operation_id=turn_id,
        payload={
            "prompt": (prompt or "")[:200],
            "action": {key: action[key] for key in action if key != "reply"},
            "verify": verify,
            "reply": (reply or "")[:240],
            "files": files[:12],
            "hashes": hashes or [],
            "route": route or str(action.get("type") or ""),
        },
    )


def capture_site(root: Path) -> None:
    dest = workspace_dir() / "files"
    dest.mkdir(parents=True, exist_ok=True)
    rels = ("lib/brand.ts", "lib/products.ts", "app/page.tsx", "lib/design-tokens.ts", "lib/nav.ts", "app/brand-vars.css")
    for rel in rels:
        src = root / rel
        if not src.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)


def publish_instructions(root: Path | None) -> None:
    if root is None or not root.is_dir():
        return
    text = instructions_block().strip()
    if not text:
        return
    (root / "seller-instructions.md").write_text(text + "\n", encoding="utf-8")


def instructions_block() -> str:
    path = workspace_dir() / "instructions.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")[:INSTRUCTION_CAP]


def _rewrite_instructions() -> None:
    rows = commands()
    rules: list[str] = []
    blob = "\n".join(str(row.get("text") or "") for row in rows)

    def add(rule: str) -> None:
        if rule not in rules:
            rules.append(rule)

    add("کالا فقط از کاتالوگ همین فروشگاه. کالای ساختگی نساز.")
    add("نگو به پیج یا اینستاگرام دسترسی نداری اگر کاتالوگ یا دستور پوشه آمده.")
    if HIDE_PRICE_RE.search(blob):
        add("قیمت روی کارت کالا نشان داده نشود.")
    if any(token in blob for token in FROM_PAGE):
        add("مدل‌ها را از پیج/کانال اسکن‌شده بگذار؛ ادیت TSX جای کاتالوگ نیست.")
    if NO_CLOTHING_RE.search(blob) and DELETE_RE.search(blob):
        add("مانتو و شلوار و شومیز نگذار مگر در کاتالوگ همین پوشه باشند.")
    from app.services.shop_edit_service import brand_text_blocked

    recent = [
        str(row.get("text") or "").strip()
        for row in rows[-8:]
        if str(row.get("text") or "").strip() and not brand_text_blocked(str(row.get("text") or ""))
    ]
    lines = ["# دستورهای فروشنده", "", "## پایدار"]
    lines.extend(f"- {rule}" for rule in rules)
    if recent:
        lines.extend(["", "## اخیر"])
        lines.extend(f"- {item[:160]}" for item in recent)
    (workspace_dir() / "instructions.md").write_text("\n".join(lines)[:INSTRUCTION_CAP] + "\n", encoding="utf-8")
