#!/usr/bin/env python3
"""Fair comparison of Decisions models on the labelled real turns: per-model request format and per-model thresholds.

  python3 tools/harness_eval/decider_eval.py collect  [--repeat 3] [--models a,b,...]
  python3 tools/harness_eval/decider_eval.py analyze

`collect` stores each model's RAW answer (choice and probabilities) for every labelled turn, once per request format:
  object  our current `state` dict, as the Perplexity decider has always received it
  array   `state` as the guide describes it: a list of plain strings, the seller message last
`analyze` replays the real `accept_action` over those stored answers with a grid of thresholds. Thresholds are chosen
on one half of the turns and scored on the other (2-fold), so a model is never scored on the data that tuned it.
When the decider is not accepted the turn goes to the chat model, so the metric is the end-to-end tool accuracy.
Run with the prod venv; needs ~/sozan-eval/state-real (made by `run.py real-routes`) and the private real turns.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import run  # noqa: E402
import score  # noqa: E402

MODELS = [
    "perplexity/pplx-decider-v1.2",
    "perplexity/pplx-decider-flash-v1.2",
    "typesafe/jev-1.14",
    "cloudflare/clef",
]
FORMATS = ("object", "array")
URL = "https://openrouter.ai/api/alpha/decisions"
OUT = common.EVAL_HOME / "runs" / "calib"
RAW = OUT / "raw.jsonl"


def use_tag(tag: str) -> None:
    """`--tag x` keeps a run of changed code apart: runs/calib-x/raw.jsonl. The calibrated baseline is never touched."""
    global OUT, RAW
    if tag:
        OUT = common.EVAL_HOME / "runs" / f"calib-{tag}"
        RAW = OUT / "raw.jsonl"
CONCURRENCY = 2
GRID_TOOL_PROB = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
GRID_TOOL_MARGIN = (0.0, 0.1, 0.2, 0.3)
GRID_CLARIFY = (0.1, 0.2, 0.3, 0.4)


def array_state(state: dict) -> list[str]:
    """The same facts as the dict, as plain strings (the guide: text items are strings). The seller message is last."""
    parts: list[str] = []
    prior = state.get("previous_turns") or []
    if prior:
        parts.append("Previous turns:\n" + "\n".join(f"{t.get('role')}: {t.get('text')}" for t in prior))
    shop = state.get("shop") or {}
    parts.append("Shop: " + ", ".join(f"{key}={value}" for key, value in shop.items()))
    parts.append(
        f"Screen: card_open={state.get('card_open')}, last_post_exists={state.get('last_post_exists')}, media_kind={state.get('media_kind')}"
    )
    parts.append("Topic: " + json.dumps(state.get("topic") or {}, ensure_ascii=False))
    parts.append("Channels: " + json.dumps(state.get("channels") or [], ensure_ascii=False))
    parts.append("Scanned pages: " + json.dumps(state.get("scanned_pages") or [], ensure_ascii=False))
    parts.append("Seller message: " + str(state.get("utterance") or ""))
    return parts


def labelled_rows() -> list[tuple[int, dict, str]]:
    rows = [json.loads(line) for line in (common.REAL_TURNS / "replay2-input.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = json.loads((common.REAL_TURNS / "replay2-labels-all.json").read_text(encoding="utf-8"))
    return [(i, row, labels[str(i)]["label"]) for i, row in enumerate(rows, 1) if labels.get(str(i), {}).get("label") not in (None, "", "unclear")]


async def collect(args) -> int:
    state_real = common.EVAL_HOME / "state-real"
    if not (state_real / "tenants" / common.OWNER).is_dir():
        print("run `run.py real-routes` once first: it prepares ~/sozan-eval/state-real")
        return 2
    run.boot(state_real, common.OWNER)
    import httpx

    from app.services import decider_service, router_service
    from app.services.shop_service import current_shop
    from app.state_store import tenant_scope

    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if RAW.is_file():
        for row in common.read_jsonl(RAW):
            done.add((row["model"], row["format"], row["rep"], row["i"]))
    token = decider_service._openrouter_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    models = [m for m in args.models.split(",") if m] or MODELS
    sem = asyncio.Semaphore(CONCURRENCY)
    out = RAW.open("a", encoding="utf-8")
    spend = 0.0

    with tenant_scope(common.OWNER):
        jobs = []
        for i, row, label in labelled_rows():
            if router_service.decide(row["text"], use_decider=True).get("kind") != "model":
                continue
            history = [*(row.get("context") or []), {"role": "user", "text": row["text"]}]
            state = decider_service.state_from(history, shop=current_shop() or {}, card_open=False, last_post=False, media=None)
            body = decider_service._body(state)
            formats = [f for f in args.formats.split(",") if f] or FORMATS
            for model, fmt, rep in itertools.product(models, formats, range(1, args.repeat + 1)):
                if (model, fmt, rep, i) in done:
                    continue
                payload = {**body, "model": model, "state": state if fmt == "object" else array_state(state)}
                jobs.append((model, fmt, rep, i, label, payload))

        async with httpx.AsyncClient(timeout=30.0) as client:

            async def one(job):
                nonlocal spend
                model, fmt, rep, i, label, payload = job
                rec = {"model": model, "format": fmt, "rep": rep, "i": i, "label": label}
                async with sem:
                    started = time.monotonic()
                    try:
                        res = await client.post(URL, headers=headers, json=payload)
                        rec["status"] = res.status_code
                        if res.status_code == 200:
                            data = res.json()
                            answers = data.get("answers") if isinstance(data.get("answers"), dict) else {}
                            rec["answer"] = answers.get("action") if isinstance(answers.get("action"), dict) else {}
                            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                            rec["cost"] = usage.get("cost")
                            spend += float(usage.get("cost") or 0)
                        else:
                            rec["error"] = res.text[:160]
                    except Exception as exc:
                        rec["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
                    rec["ms"] = int((time.monotonic() - started) * 1000)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()

            print(f"{len(jobs)} requests to send ({len(done)} already stored)", flush=True)
            await asyncio.gather(*(one(job) for job in jobs))
    out.close()
    print(f"DONE. Real spend ${spend:.4f}. Raw answers in {RAW}")
    return 0


def analyze() -> int:
    run.boot(common.EVAL_HOME / "state-real", common.OWNER)
    from app.services import decider_service as ds

    chat = {}
    base = common.EVAL_HOME / "runs" / "cand-v12" / "real.jsonl"
    for row in common.read_jsonl(base):
        if "chat" in row:
            chat[row["i"]] = (row["chat"] or {}).get("tool", "")
    rows = common.read_jsonl(RAW)
    groups: dict[tuple[str, str], dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        groups[(r["model"], r["format"])][r["i"]].append(r)
    default = (ds.TOOL_MIN_PROB, ds.TOOL_MIN_MARGIN, ds.CLARIFY_SECOND_MIN)

    def correct(rec: dict, params: tuple, *, raw: bool = False) -> bool:
        label = rec["label"]
        answer = rec.get("answer") or {}
        if rec.get("status") != 200 or not answer:
            return score.real_ok(label, chat.get(rec["i"], ""), "")
        ds.TOOL_MIN_PROB, ds.TOOL_MIN_MARGIN, ds.CLARIFY_SECOND_MIN = params
        choice, _prob, _margin, ok = ds.accept_action(answer)
        if raw:
            ok = bool(choice)
        if ok:
            return score.real_ok(label, ds._ACTIONS.get(choice, ("", {}))[0], choice)
        return score.real_ok(label, chat.get(rec["i"], ""), "")

    def accuracy(recs: list[dict], params: tuple, **kw) -> float:
        return sum(correct(r, params, **kw) for r in recs) / len(recs) if recs else 0.0

    grid = list(itertools.product(GRID_TOOL_PROB, GRID_TOOL_MARGIN, GRID_CLARIFY))
    print(f"{'model':36} {'fmt':6} {'n':>4} {'err':>3} {'raw':>6} {'prod':>6} {'CV':>6} {'in-sample':>9}  best (prob, margin, clarify)  $/call")
    for (model, fmt), by_row in sorted(groups.items()):
        recs = [r for lst in by_row.values() for r in lst]
        errors = sum(1 for r in recs if r.get("status") != 200)
        costs = [float(r["cost"]) for r in recs if r.get("cost") is not None]
        folds = {0: [r for r in recs if r["i"] % 2 == 0], 1: [r for r in recs if r["i"] % 2 == 1]}
        hits = total = 0
        for train_key, test_key in ((0, 1), (1, 0)):
            best = max(grid, key=lambda p: (accuracy(folds[train_key], p), -sum(abs(a - b) for a, b in zip(p, default))))
            hits += sum(correct(r, best) for r in folds[test_key])
            total += len(folds[test_key])
        best_all = max(grid, key=lambda p: (accuracy(recs, p), -sum(abs(a - b) for a, b in zip(p, default))))
        per_rep = [accuracy([r for r in recs if r["rep"] == k], default) for k in sorted({r["rep"] for r in recs})]
        spread = f"±{(max(per_rep) - min(per_rep)) / 2:.1%}" if len(per_rep) > 1 else ""
        print(
            f"{model:36} {fmt:6} {len(recs):>4} {errors:>3} {accuracy(recs, default, raw=True):>6.1%} {accuracy(recs, default):>6.1%} "
            f"{hits / total:>6.1%} {accuracy(recs, best_all):>9.1%}  {best_all}  {statistics.mean(costs) if costs else 0:.6f} {spread}"
        )
    ds.TOOL_MIN_PROB, ds.TOOL_MIN_MARGIN, ds.CLARIFY_SECOND_MIN = default
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--repeat", type=int, default=3)
    c.add_argument("--models", default="")
    c.add_argument("--formats", default="")
    c.add_argument("--tag", default="")
    a = sub.add_parser("analyze")
    a.add_argument("--tag", default="")
    args = parser.parse_args()
    use_tag(args.tag)
    return asyncio.run(collect(args)) if args.mode == "collect" else analyze()


if __name__ == "__main__":
    raise SystemExit(main())
