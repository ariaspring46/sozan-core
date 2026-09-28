#!/usr/bin/env python3
"""Nightly finetune-data build (finetune-data-plan.md §3). Runs on the home machine.

Reads the observe raw store (raw/<day>/<task>.jsonl and _labels.jsonl), joins
labels by exampleId, drops any row that still carries a PII pattern (the second,
independent scan on top of the app-side mask), removes exact and normalized
near-duplicates, and writes per-task SFT (confirmed or seller-edited answers
only) and preference pairs (original → edited) plus a stats report. Battery and
synthetic rows are counted but never trained on; handoffs stay aside; nothing
leaves this machine.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

HOME_RAW = Path.home() / "local-ai/sozan-train/raw"
HOME_OUT = Path.home() / "local-ai/sozan-train"
LABELS_FILE = "_labels.jsonl"
TRAIN_TASKS = ("router", "shop_edit", "caption", "inbox_reply", "site_design")

_ZWNJ = {"\u200c", "\u200d"}
_NOISE = re.compile(r"[\s\u200c\u200d\.,،؛:!؟?\(\)\[\]{}«»\"'ـ-]+")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# The mask always folds Persian digits, so a changed string is not a leak.
# A row leaks only when masking inserts one of these placeholders.
_PII_MARKS = ("[تلفن]", "[کارت]", "[شبا]", "[کد]", "[نشانی]")


def load_mask():
    """The same mask the app uses, loaded by path so this script stays standalone."""
    path = Path(__file__).resolve().parents[1] / "backend/app/services/pii_mask.py"
    spec = importlib.util.spec_from_file_location("sozan_pii_mask", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _texts(row: dict) -> list[str]:
    parts = [str((row.get("output") or {}).get("text") or "")]
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    parts.append(str(labels.get("editedText") or ""))
    for msg in row.get("messages") or []:
        if isinstance(msg, dict):
            parts.append(str(msg.get("content") or ""))
    return parts


def carries_pii(mask, row: dict) -> bool:
    return any(any(mark in mask.mask_pii(text) for mark in _PII_MARKS) for text in _texts(row))


def normalize(text: str) -> str:
    folded = str(text or "").translate(_DIGITS).lower()
    for mark in _ZWNJ:
        folded = folded.replace(mark, "")
    return _NOISE.sub("", folded)


def fingerprint(row: dict) -> str:
    payload = {
        "m": [normalize(str(msg.get("content") or "")) for msg in row.get("messages") or []],
        "o": normalize(str((row.get("output") or {}).get("text") or "")),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def load_day(raw: Path, day: str) -> tuple[list[dict], list[dict], int]:
    examples: list[dict] = []
    labels: list[dict] = []
    bad = 0
    day_dir = raw / day
    if not day_dir.is_dir():
        return examples, labels, bad
    for path in sorted(day_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if not isinstance(row, dict):
                bad += 1
                continue
            if path.name == LABELS_FILE:
                labels.append(row)
            else:
                examples.append(row)
    return examples, labels, bad


def join_labels(examples: list[dict], labels: list[dict]) -> int:
    by_id: dict[str, dict] = {}
    for row in examples:
        key = str(row.get("id") or "")
        if key:
            by_id[key] = row
    joined = 0
    for row in labels:
        target = by_id.get(str(row.get("exampleId") or ""))
        fresh = row.get("labels") if isinstance(row.get("labels"), dict) else {}
        if target is None or not fresh:
            continue
        merged = target.get("labels") if isinstance(target.get("labels"), dict) else {}
        merged.update(fresh)
        target["labels"] = merged
        joined += 1
    return joined


def dedupe(examples: list[dict]) -> tuple[list[dict], int]:
    seen_ids: set[str] = set()
    seen_pairs: set[str] = set()
    kept: list[dict] = []
    dropped = 0
    for row in examples:
        key = str(row.get("id") or "")
        pair = fingerprint(row)
        if (key and key in seen_ids) or pair in seen_pairs:
            dropped += 1
            continue
        if key:
            seen_ids.add(key)
        seen_pairs.add(pair)
        kept.append(row)
    return kept, dropped


def trainable(row: dict, allow_sources: set[str]) -> bool:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    return str(row.get("source") or "real") in allow_sources and labels.get("accept") is not False


def to_sft(row: dict) -> dict:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    messages = [msg for msg in row.get("messages") or [] if isinstance(msg, dict)]
    return {
        "messages": messages + [{"role": "assistant", "content": str(labels.get("editedText") or (row.get("output") or {}).get("text") or "")}],
        "task": row.get("task") or "",
        "teacher": row.get("teacher") or "",
        "id": row.get("id") or "",
    }


def to_dpo(row: dict) -> dict | None:
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    edited = str(labels.get("editedText") or "").strip()
    original = str((row.get("output") or {}).get("text") or "").strip()
    if not edited or edited == original:
        return None
    return {
        "prompt": [msg for msg in row.get("messages") or [] if isinstance(msg, dict)],
        "chosen": edited,
        "rejected": original,
        "task": row.get("task") or "",
        "id": row.get("id") or "",
    }


def build(*, raw: Path = HOME_RAW, out: Path = HOME_OUT, day: str = "", allow_sources: set[str] | None = None) -> dict:
    day = day or time.strftime("%Y-%m-%d")
    allow = allow_sources or {"real"}
    mask = load_mask()
    examples, labels, bad = load_day(raw, day)
    raw_count = len(examples)
    pii_dropped = sum(1 for row in examples if carries_pii(mask, row))
    examples = [row for row in examples if not carries_pii(mask, row)]
    examples, dupes = dedupe(examples)
    joined = join_labels(examples, labels)

    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    stats: dict = {
        "day": day,
        "raw": raw_count,
        "badJson": bad,
        "labelsJoined": joined,
        "piiDropped": pii_dropped,
        "dupesDropped": dupes,
        "sources": {},
        "tasks": {},
        "sft": 0,
        "dpo": 0,
    }
    per_task: dict[str, list[dict]] = {}
    for row in examples:
        task = str(row.get("task") or "unknown")
        per_task.setdefault(task, []).append(row)
        source = str(row.get("source") or "real")
        stats["sources"][source] = stats["sources"].get(source, 0) + 1
    for task, rows in sorted(per_task.items()):
        task_stats = {"examples": len(rows), "labeled": 0, "handoff": 0, "sft": 0, "dpo": 0}
        sft_rows: list[dict] = []
        dpo_rows: list[dict] = []
        for row in rows:
            labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
            if labels:
                task_stats["labeled"] += 1
            is_handoff = str((row.get("output") or {}).get("path") or "") == "handoff"
            if is_handoff:
                task_stats["handoff"] += 1
            if not trainable(row, allow) or is_handoff:
                continue
            if labels.get("accept") is True or str(labels.get("editedText") or "").strip():
                sft_rows.append(to_sft(row))
                task_stats["sft"] += 1
            pair = to_dpo(row)
            if pair is not None:
                dpo_rows.append(pair)
                task_stats["dpo"] += 1
        if sft_rows:
            path = out / "sft" / day / f"{task}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sft_rows), encoding="utf-8")
        if dpo_rows:
            path = out / "dpo" / day / f"{task}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in dpo_rows), encoding="utf-8")
        stats["tasks"][task] = task_stats
        stats["sft"] += task_stats["sft"]
        stats["dpo"] += task_stats["dpo"]
    stats_path = out / f"stats-{day}.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the daily finetune sets from the observe raw store.")
    parser.add_argument("--day", default="", help="YYYY-MM-DD; default is today")
    parser.add_argument("--raw", default=str(HOME_RAW), help="raw store directory")
    parser.add_argument("--out", default=str(HOME_OUT), help="output directory")
    parser.add_argument("--allow-battery", action="store_true", help="also train on battery rows (off by default)")
    args = parser.parse_args()
    allow = {"real", "battery"} if args.allow_battery else {"real"}
    stats = build(raw=Path(args.raw), out=Path(args.out), day=args.day, allow_sources=allow)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
