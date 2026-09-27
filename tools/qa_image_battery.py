#!/usr/bin/env python3
"""Ten image checks. Writes png files and qa_image_result.json next to --out."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from PIL import Image


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("cases must be a list")
    return data


def size_of(name: str) -> tuple[int, int]:
    if name == "story":
        return 1080, 1920
    return 1080, 1080


def run_revise(text: str) -> tuple[bool, str]:
    from app.services import studio_chat_service

    campaigns = type("C", (), {})()

    async def update_copy(self, campaign_id, **kwargs):
        return None

    campaigns.update_copy = update_copy.__get__(campaigns)
    prior = [
        {
            "id": "old",
            "role": "assistant",
            "text": "پست آماده شد.",
            "campaignId": str(uuid4()),
            "captions": {"instagram": "کپشن", "telegram": "کپشن", "whatsapp": "کپشن"},
        }
    ]
    stored = {"rows": list(prior)}

    def reader(name, default=None):
        return list(stored["rows"])

    def writer(name, payload):
        stored["rows"] = list(payload)

    with tempfile.TemporaryDirectory() as raw, patch(
        "app.services.studio_chat_service.read_json", side_effect=reader
    ), patch("app.services.studio_chat_service.write_json", side_effect=writer), patch(
        "app.services.studio_chat_service.emit_later"
    ), patch("app.services.studio_chat_service.tenant_file_lock", lambda *_a, **_k: _null()), patch(
        "app.state_store.tenant_dir", return_value=Path(raw)
    ), patch(
        "app.services.studio_chat_service.complete_json",
        new=AsyncMock(return_value={"reply": "کپشن رسمی شد.", "instagram": "رسمی", "telegram": "رسمی", "whatsapp": "رسمی"}),
    ), patch("app.services.studio_compose_service.start") as started, patch(
        "app.services.image_provider_service.generate_still"
    ) as still:
        asyncio.run(studio_chat_service.chat(text, campaigns))
    if started.called or still.called:
        return False, "image-started"
    return True, "no-image"


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tools/qa_image_battery.json")
    parser.add_argument("--fixtures", default="/home/ubuntu/sozan-bench-images")
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-kind", action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "backend"))
    load_env(root / ".env")
    os.environ["IMAGE_OR_URL"] = "https://openrouter.ai/api/v1"
    os.environ["IMAGE_OR_MODEL"] = "black-forest-labs/flux.2-klein-4b"
    os.environ["IMAGE_OR_EDIT_MODEL"] = "bytedance-seed/seedream-4.5"
    os.environ["STUDIO_CLOUD_MODEL"] = "deepseek/deepseek-v4.1-flash"
    os.environ["IMAGE_FALLBACK"] = "none"
    os.environ.pop("OPENROUTER_PROXY", None)
    os.environ.pop("IMAGE_LOCAL", None)
    os.environ.pop("CHANNEL_PROXY", None)
    from app.services import image_provider_service

    cases = [case for case in load_cases(Path(args.cases)) if case.get("kind") not in set(args.skip_kind)]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fixtures = Path(args.fixtures)
    rows = []
    passed = 0
    for case in cases:
        kind = case["kind"]
        row = {"id": case["id"], "kind": kind, "pass": False, "note": ""}
        started = time.perf_counter()
        if kind == "revise":
            ok, note = run_revise(str(case.get("text") or "رسمی‌تر کن"))
            row["pass"] = ok
            row["note"] = note
        else:
            width, height = size_of(str(case.get("size") or "post"))
            source = b""
            if case.get("file"):
                source = (fixtures / str(case["file"])).read_bytes()
            result = image_provider_service.generate_image(
                str(case.get("prompt") or ""),
                width=width,
                height=height,
                edit=kind == "edit" and case.get("edit_kind") != "background",
                edit_kind=str(case.get("edit_kind") or ""),
                plan=str(case.get("plan") or ""),
                source=source or None,
                force_primary_error=case.get("mode") == "retry",
                force_both_errors=case.get("mode") == "fail",
                subject=str(case.get("subject") or ""),
            )
            png = result.get("png") or b""
            dest = out / f"{case['id']}.png"
            if len(png) >= 2048:
                dest.write_bytes(png)
            row.update(
                {
                    "model": result.get("model") or "",
                    "provider": result.get("provider") or "",
                    "cost": result.get("cost"),
                    "fallback": bool(result.get("fallback")),
                    "preserved": bool(result.get("preserved")),
                    "guard": result.get("guard"),
                    "guard_cost": result.get("guard_cost"),
                    "bytes": len(png),
                    "charged": bool(result.get("charged")),
                    "failed": bool(result.get("failed")),
                    "message": result.get("message") or "",
                    "retried": bool(result.get("retried")),
                    "view": result.get("view") or "",
                    "closeup": bool(result.get("closeup")),
                }
            )
            ok, note = judge(case, result, dest)
            row["pass"] = ok
            row["note"] = note
        row["seconds"] = round(time.perf_counter() - started, 1)
        if row["pass"]:
            passed += 1
        rows.append(row)
        print(json.dumps({"id": row["id"], "pass": row["pass"], "note": row["note"]}, ensure_ascii=False), flush=True)
    summary = {"n": len(cases), "passed": passed, "out": str(out)}
    payload = json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2)
    dest = out / "qa_image_result.json"
    if dest.exists():
        dest = out / f"qa_image_result-{time.strftime('%Y%m%d-%H%M%S')}.json"
    dest.write_text(payload, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if passed == len(cases) else 1


def judge(case: dict, result: dict, dest: Path) -> tuple[bool, str]:
    png = result.get("png") or b""
    if case.get("mode") == "fail":
        from app.services.image_provider_service import FAIL_TEXT

        if len(png) >= 2048 or result.get("charged") or not result.get("failed"):
            return False, "charged" if result.get("charged") else "not-failed"
        if result.get("message") != FAIL_TEXT:
            return False, "message"
        return True, "ok"
    if len(png) < 2048 or not dest.is_file():
        return False, "no-image"
    with Image.open(dest) as img:
        size = img.size
    if case.get("size", "post") == "story" and size != (1080, 1920):
        return False, f"size-{size[0]}x{size[1]}"
    if case.get("size", "post") != "story" and size != (1080, 1080):
        return False, f"size-{size[0]}x{size[1]}"
    model = str(result.get("model") or "")
    if case["kind"] == "fresh" and "klein" not in model:
        return False, model or "model"
    if case["kind"] == "product":
        if "klein" not in model or not result.get("preserved"):
            return False, model or "product"
    if case["kind"] == "edit":
        if case.get("edit_kind") == "background":
            if "klein" not in model or not result.get("preserved"):
                return False, model or "background"
        elif "seedream" not in model:
            return False, model or "edit"
    if case["kind"] == "fallback":
        if "klein" not in model or not result.get("retried") or result.get("fallback"):
            return False, model or "fallback"
    if case["kind"] in {"fresh", "product", "edit"} and not isinstance(result.get("cost"), float):
        return False, "no-cost"
    if case.get("subject") and result.get("guard") is not True:
        return False, "guard"
    return True, "ok"


if __name__ == "__main__":
    sys.exit(main())
