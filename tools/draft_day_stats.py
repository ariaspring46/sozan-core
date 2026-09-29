#!/usr/bin/env python3
"""Day-1 draft-pilot stats for azmaish-panl. Counts only; never customer text.

Reads the home raw store for the pilot tenant's hashed rows (per-path reply mix,
labels) and, when the hub is reachable, the inbound/draft counts from the app's
own services. Output is a JSON blob ready to paste into sales-agent-talk.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

PILOT_SLUG = "azmaish-panl"
PILOT_HASH = "36cdab7edc18903b"
RAW = Path.home() / "local-ai/sozan-train/raw"
HUB_SNIPPET = """
import json
import sys
sys.path.insert(0, "/home/ubuntu/sozan-core/backend")
from app.state_store import iter_tenants, tenant_scope, read_json
from app.services import inbox_service, plan_service
for phone in iter_tenants():
    with tenant_scope(phone):
        shop = read_json("shop.json", {})
        if str(shop.get("slug") or "") != "azmaish-panl":
            continue
        data = inbox_service._state()
        threads = data.get("threads") or []
        inbound = sum(1 for t in threads for m in (t.get("messages") or []) if m.get("role") == "inbound")
        drafts = sum(1 for t in threads for m in (t.get("messages") or []) if m.get("role") == "outbound" and str(m.get("kind") or "") == "draft")
        sent = sum(1 for t in threads for m in (t.get("messages") or []) if m.get("role") == "outbound" and str(m.get("kind") or "") == "outbound")
        handoff = sum(1 for t in threads for m in (t.get("messages") or []) if m.get("handoffReason"))
        print(json.dumps({
            "threads": len(threads),
            "inbound": inbound,
            "drafts": drafts,
            "sellerSent": sent,
            "handoffThreads": handoff,
            "autoReplyMode": inbox_service.effective_auto_reply(),
        }, ensure_ascii=False))
""".strip()


def hub_stats() -> dict:
    try:
        raw = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "ubuntu@hub",
             "cd /home/ubuntu/sozan-core/backend && .venv/bin/python3 -"],
            input=HUB_SNIPPET, capture_output=True, text=True, timeout=45, check=True,
        )
        line = [line for line in raw.stdout.splitlines() if line.strip().startswith("{")]
        return json.loads(line[-1]) if line else {}
    except Exception as exc:
        return {"hubError": str(exc)[:120]}


def train_stats(day_dirs: list[Path]) -> dict:
    paths: Counter = Counter()
    labels: Counter = Counter()
    total = 0
    for day_dir in day_dirs:
        labels_file = day_dir / "_labels.jsonl"
        by_id: dict[str, dict] = {}
        if labels_file.is_file():
            for line in labels_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    by_id[str(row.get("exampleId") or "")] = row.get("labels") or {}
        for path in day_dir.glob("*.jsonl"):
            if path.name == "_labels.jsonl":
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("tenant") != PILOT_HASH or row.get("source") != "real":
                    continue
                total += 1
                paths[str((row.get("output") or {}).get("path") or "?")] += 1
                lab = by_id.get(str(row.get("id") or ""))
                if not lab:
                    labels["unlabeled"] += 1
                    continue
                if lab.get("vote") == "up":
                    labels["thumbUp"] += 1
                elif lab.get("vote") == "down":
                    labels["thumbDown"] += 1
                elif lab.get("editedText"):
                    labels["editedSend"] += 1
                elif lab.get("sent"):
                    labels["sentUnchanged"] += 1
                else:
                    labels["other"] += 1
    return {"examples": total, "paths": dict(paths), "labels": dict(labels)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2, help="how many recent day folders to include")
    args = parser.parse_args()
    day_dirs = sorted((p for p in RAW.iterdir() if p.is_dir()), reverse=True)[: args.days]
    stats = {
        "at": time.strftime("%Y-%m-%d %H:%M"),
        "train": train_stats(day_dirs),
        "hub": hub_stats(),
    }
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
