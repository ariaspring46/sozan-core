#!/usr/bin/env python3
"""Runs the harness eval with real models and the real router code. Outside effects are stubbed and counted.

  python3 tools/harness_eval/run.py lock
  python3 tools/harness_eval/run.py cases --run-id B0 [--repeat 3] [--only ID ...] [--budget 0.4] [--dry] [--dev]
  python3 tools/harness_eval/run.py real-routes --run-id B0 [--repeat 3] [--budget 0.5] [--dry]

Run on the hub with the prod venv, from the clone of the commit being measured: the app imported is that clone's.
Records go to ~/sozan-eval/runs/<run-id>/ (never into git). `cases` refuses to run unless cases.json matches
cases.lock; --dev skips that check and marks the run as not comparable. Score with report.py.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import inspect
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture  # noqa: E402
import score  # noqa: E402

sys.path.insert(0, str(common.TOOLS))  # chat_scenarios.lint lives in tools/

CASE_CAP_S = 240.0
PER_CALL_USD = 0.002  # assumed when the provider does not report a cost
ENV_PINS = {
    "SOZAN_EDGE_DRY": "1",
    "SOZAN_OBSERVE_OUTBOX": "0",
    "LOCAL_LLM_URL": "http://127.0.0.1:1/v1",
    "LLM_LOCAL_FALLBACK": "0",
    "REDIS_URL": "redis://127.0.0.1:1/0",
    "DECIDER_ENABLED": "1",
}
MODEL_KEYS = ("DECIDER_MODEL", "DECIDER_PRO_MODEL", "CLOUD_LLM_MODEL", "STUDIO_CLOUD_MODEL", "CLOUD_LLM_EXTRA_BODY", "DECIDER_TENANTS")
CLAIM_RE = re.compile(
    r"(?<![؀-ۿ])(?:انجام شد|ثبت شد|اعمال شد|منتشر شد|ذخیره شد|تغییر کرد|به‌روز شد|به روز شد|حذف شد|"
    r"اضافه شد|روشن شد|خاموش شد|کردم|گذاشتم|ساختم|فرستادم|نوشتم)(?![؀-ۿ])"
)
EFFECTS: Counter = Counter()
CALLS: list[dict] = []
DECISIONS: list[dict] = []
SPEND = {"usd": 0.0}
RUNTIME: dict = {}


class BudgetStop(Exception):
    pass


def cost_of(usage) -> float | None:
    if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)):
        return float(usage["cost"])
    return None


def boot(state: Path, tenants: str) -> None:
    """Sets the env before the app is imported. Prod settings stay, except the pins: state, edge, observe, local LLM."""
    for key, value in common.load_env(common.PROD_ENV).items():
        os.environ.setdefault(key, value)
    os.environ.update(ENV_PINS)
    os.environ["STATE_DIR"] = str(state)
    os.environ["DECIDER_TENANTS"] = tenants
    sys.path.insert(0, str(common.BACKEND))


def write_json(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def manifest(run_id: str, mode: str, args) -> dict:
    cases_sha = common.sha256(common.CASES) if common.CASES.is_file() else ""
    lock_sha = common.LOCK.read_text(encoding="utf-8").strip() if common.LOCK.is_file() else ""
    real = common.REAL_TURNS / "replay2-input.jsonl"
    return {
        "run_id": run_id,
        "mode": mode,
        "commit": common.git_head(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version.split()[0],
        "cases_sha256": cases_sha,
        "lock_sha256": lock_sha,
        "dev": bool(getattr(args, "dev", False)),
        "repeat": args.repeat,
        "budget_usd": args.budget,
        "pins": {key: os.environ.get(key, "") for key in ENV_PINS},
        "models": {key: os.environ.get(key, "") for key in MODEL_KEYS},
        "real_turns_sha256": common.sha256(real) if real.is_file() else "",
    }


def canary() -> dict:
    tenants_dir = common.PROD_DATA / "tenants"
    tenants = sorted(path.name for path in tenants_dir.iterdir() if path.is_dir() and path.name.isdigit()) if tenants_dir.is_dir() else []
    settings = common.PROD_DATA / "settings.json"
    others = sorted(set(fixture.docker("ps", "-a", "--format", "{{.Names}}").stdout.split()) - {common.CONTAINER})
    builds_dir = common.SITE_BUILDER / "builds"
    builds = sorted(path.name for path in builds_dir.iterdir() if path.name != common.FIXTURE_SLUG) if builds_dir.is_dir() else []
    return {
        "map": common.sha256(common.PROD_MAP) if common.PROD_MAP.is_file() else "",
        "settings": common.sha256(settings) if settings.is_file() else "",
        "tenants": hashlib.sha256("|".join(tenants).encode("utf-8")).hexdigest(),
        "containers": hashlib.sha256("|".join(others).encode("utf-8")).hexdigest(),
        "builds": hashlib.sha256("|".join(builds).encode("utf-8")).hexdigest(),
    }


def classify(reply: str) -> str:
    from app.services import shop_voice_service as voice

    if not reply.strip():
        return "none"
    if voice._FAILED.search(reply):
        return "failure"
    if voice._SUCCESS.search(reply) or CLAIM_RE.search(reply):
        return "success"
    if "؟" in reply or "?" in reply:
        return "question"
    return "none"


def lint_reply(reply: str) -> list[str]:
    from chat_scenarios import lint

    return list(lint(reply, set())) if reply.strip() else []


def write_tools() -> set[str]:
    from app.services import router_tools

    return set(getattr(router_tools, "WRITE_TOOLS", ()) or ())


class FakeCampaigns:
    async def create(self, **kwargs):
        raise RuntimeError("campaigns are not part of the harness eval")


# --------------------------------------------------------------------------- stubs


def _outbound(name: str):
    async def fake(*args, **kwargs):
        EFFECTS[f"outbound:{name}"] += 1
        return {"ok": True, "stub": True}

    return fake


def _outbound_sync(name: str):
    def fake(*args, **kwargs):
        EFFECTS[f"outbound:{name}"] += 1

    return fake


def _build(*args, **kwargs):
    EFFECTS["build_calls"] += 1
    return {"ok": True, "stub": True}


def _docker(args, *rest, **kwargs):
    EFFECTS["docker_calls"] += 1
    return subprocess.CompletedProcess(args, 1, "", "blocked by harness eval")


def _built_run(real_run):
    """subprocess.run while the really built shop is in play: docker exec/cp on the fixture container only."""

    def guarded(args, *rest, **kwargs):
        cmd = [str(part) for part in args] if isinstance(args, (list, tuple)) else [str(args)]
        on_fixture = any(part == common.CONTAINER or part.startswith(common.CONTAINER + ":") for part in cmd)
        if cmd[:2] in (["docker", "exec"], ["docker", "cp"]) and on_fixture:
            EFFECTS["docker_calls"] += 1
            return real_run(args, *rest, **kwargs)
        if any("sozan_factory_fastpath" in part for part in cmd):
            EFFECTS["build_calls"] += 1
        else:
            EFFECTS["docker_calls"] += 1
        return subprocess.CompletedProcess(args, 1, "", "blocked by harness eval")

    return guarded


def _built_spawn(original):
    """A confirmed edit may start the factory's revise step for the fixture job, once; anything else is blocked."""

    def guarded(job_id, shop):
        if str(job_id) != fixture.built_manifest()["jobId"]:
            EFFECTS["build_calls"] += 1
            return None
        EFFECTS["build_calls"] += 1
        return original(job_id, shop)

    return guarded


def _recorded_chat(original):
    async def recorded(**kwargs):
        result = await original(**kwargs)
        calls = result.get("tool_calls") or []
        cost = cost_of(result.get("usage"))
        SPEND["usd"] += cost if cost is not None else PER_CALL_USD
        first = calls[0] if calls and isinstance(calls[0], dict) else {}
        args = first.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        CALLS.append(
            {
                "tools": [str(call.get("name") or "") for call in calls if isinstance(call, dict)],
                "args": args if isinstance(args, dict) else {},
                "text": str(result.get("text") or "")[:400],
                "cost": cost,
            }
        )
        return result

    return recorded


def _recorded_decider(original):
    async def recorded(state, *args, **kwargs):
        decision = await original(state, *args, **kwargs)
        row = decision if isinstance(decision, dict) else {}
        cost = cost_of(row.get("usage"))
        SPEND["usd"] += cost if cost is not None else PER_CALL_USD
        ranked = [[str(key), round(float(value), 3)] for key, value in (row.get("ranked") or [])[:3]]
        DECISIONS.append({"action": str(row.get("action") or ""), "ranked": ranked, "cost": cost})
        return decision

    return recorded


def _counted(original):
    """Voice and other side models: not recorded, but their calls count against the budget."""
    if inspect.iscoroutinefunction(original):

        async def counted(*args, **kwargs):
            SPEND["usd"] += PER_CALL_USD
            return await original(*args, **kwargs)

        return counted

    def counted_sync(*args, **kwargs):
        SPEND["usd"] += PER_CALL_USD
        return original(*args, **kwargs)

    return counted_sync


def stubbed(stack: contextlib.ExitStack, built: bool = False) -> None:
    from unittest.mock import patch

    from app.services import (
        ai_budget_service,
        decider_service,
        inbox_service,
        llm,
        sendbox_service,
        seller_alerts,
        shop_edit_service,
        shop_service,
        shop_voice_service,
        sms_service,
        studio_publish_service,
    )

    pairs: list[tuple] = [
        (inbox_service, "reply", _outbound("inbox.reply")),
        (sendbox_service, "send_message", _outbound("sendbox.send")),
        (sms_service, "send_otp", _outbound("sms.otp")),
        (seller_alerts, "push", _outbound("alert.push")),
        (seller_alerts, "_sms", _outbound("alert.sms")),
        (seller_alerts, "alert", _outbound("alert.alert")),
        (seller_alerts, "alert_soon", _outbound_sync("alert.soon")),
        (studio_publish_service, "publish", _outbound("studio.publish")),
        (ai_budget_service, "cloud_blocked", lambda *a, **k: None),
        (llm, "complete_tools", _recorded_chat(llm.complete_tools)),
        (decider_service, "choose_with_retry", _recorded_decider(decider_service.choose_with_retry)),
    ]
    if built:
        pairs += [
            (subprocess, "run", _built_run(subprocess.run)),
            (shop_edit_service, "spawn_rebuild", _built_spawn(shop_edit_service.spawn_rebuild)),
        ]
    else:
        pairs += [
            (shop_service, "start_build", _build),
            (shop_service, "_refresh_job", lambda row: row),
            (shop_service, "_factory_status", lambda *a, **k: {"status": "ready", "url": f"https://{common.FIXTURE_SLUG}.sozan-core.ir"}),
            (shop_edit_service, "build_dir_for", lambda shop: fixture.SITE),
            (subprocess, "run", _docker),
        ]
    for name in ("complete_json", "complete_json_chat"):
        original = getattr(shop_voice_service, name, None)
        if original is not None:
            pairs.append((shop_voice_service, name, _counted(original)))
    for module, name, fake in pairs:
        stack.enter_context(patch.object(module, name, new=fake))


# --------------------------------------------------------------------------- one turn


async def send(text: str, *, confirm_id: str = "", cancel_id: str = "") -> dict:
    from app.services import router_service

    trace_path = fixture.tenant_dir() / "router-turns.jsonl"
    verify_path = fixture.tenant_dir() / "shop-workspace" / "trace.jsonl"
    trace_before = common.count_lines(trace_path)
    verify_before = common.count_lines(verify_path)
    calls_before, decisions_before = len(CALLS), len(DECISIONS)
    error = ""
    out: dict = {}
    started = time.monotonic()
    try:
        out = await asyncio.wait_for(
            router_service.turn(text, campaigns=FakeCampaigns(), confirm_id=confirm_id, cancel_id=cancel_id),
            timeout=CASE_CAP_S,
        )
    except Exception as exc:  # a crash is recorded as evidence, never hidden
        error = type(exc).__name__
    elapsed = time.monotonic() - started
    if not isinstance(out, dict):
        out = {}
    assistant = [m for m in out.get("messages") or [] if isinstance(m, dict) and m.get("role") == "assistant"]
    reply = str(assistant[-1].get("text") or "") if assistant else ""
    pending = out.get("pendingConfirm")
    card = None
    if isinstance(pending, dict) and pending.get("id"):
        card = {
            "id": str(pending["id"]),
            "tool": str(pending.get("tool") or ""),
            "arguments": pending.get("arguments") if isinstance(pending.get("arguments"), dict) else {},
            "summary": str(pending.get("summary") or ""),
        }
    trace = common.read_jsonl(trace_path)[trace_before:]
    verify = common.read_jsonl(verify_path)[verify_before:]
    last = trace[-1] if trace else {}
    tool = (card or {}).get("tool") or str(last.get("tool") or "")
    args = (card or {}).get("arguments") or (last.get("arguments") if isinstance(last.get("arguments"), dict) else {})
    ask = card is None and ("؟" in reply or "?" in reply)
    writes = write_tools()
    unconfirmed = sorted({str(row.get("tool")) for row in trace if row.get("tool") in writes and not row.get("card") and not confirm_id and not cancel_id})
    return {
        "say": text,
        "card": card,
        "tool": tool,
        "args": args,
        "ask": ask,
        "reply": reply,
        "claim": classify(reply),
        "lint": lint_reply(reply),
        "trace": trace,
        "calls": CALLS[calls_before:],
        "decisions": DECISIONS[decisions_before:],
        "verify": verify,
        "error": error,
        "elapsed": round(elapsed, 2),
        "write_unconfirmed": unconfirmed,
    }


def merge(first: dict, follow: dict) -> dict:
    """The card comes from the first send; the reply, claim and lint come from the final reply (after a confirm)."""
    merged = dict(first)
    final = follow if follow["reply"] else first
    merged["reply"], merged["claim"], merged["lint"] = final["reply"], final["claim"], final["lint"]
    merged["error"] = first["error"] or follow["error"]
    for key in ("trace", "calls", "decisions", "verify"):
        merged[key] = first[key] + follow[key]
    merged["elapsed"] = round(first["elapsed"] + follow["elapsed"], 2)
    merged["write_unconfirmed"] = first["write_unconfirmed"]
    return merged


async def run_step(turn: dict) -> dict:
    action = turn.get("action", "none")
    first = await send(turn["say"])
    result = dict(first)
    result["action"] = action
    if action in ("confirm", "cancel"):
        card = first["card"]
        if card and action == "confirm":
            result = merge(first, await send("", confirm_id=card["id"]))
        elif card:
            result = merge(first, await send("", cancel_id=card["id"]))
        else:
            result["confirm_without_card"] = True
        result["action"] = action
    return result


def _get(url: str) -> tuple[int, str]:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=20) as res:
            return res.status, res.read(400_000).decode("utf-8", "replace")
    except OSError:
        return 0, ""


async def settle_build(max_s: float) -> tuple[dict, dict]:
    """After a confirmed edit on the really built shop: wait for the factory's revise step if one started, then read the
    job state and the live page from the container (its own request, not the app's check)."""
    from app.services import shop_service

    started = time.monotonic()
    while True:
        shop = shop_service._refresh_job(shop_service._shop())
        if str(shop.get("status") or "") not in shop_service.BUILD_BUSY or time.monotonic() - started > max_s:
            break
        await asyncio.sleep(5)
    job_path = common.FACTORY_JOBS / f"{fixture.built_manifest()['jobId']}.json"
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        job = {}
    port = int(shop.get("port") or fixture.built_manifest()["port"])
    code, html = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/")
    _, css = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/brand-vars.css")
    _, flags = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/storefront-flags.json")
    status = str(shop.get("status") or "")
    build = {
        "status": status,
        "jobStatus": str(job.get("status") or ""),
        "buildOk": status == "ready" and str(job.get("status") or "") in {"done", "ready"},
        "urlOk": code == 200,
        "waitedSec": round(time.monotonic() - started, 1),
    }
    return build, {"text": "\n".join((html, css, flags))}


async def run_case(case: dict, rep: int, budget: float) -> dict:
    built = bool(case.get("needs_build"))
    fixture.restore(built=built)
    EFFECTS.clear()
    CALLS.clear()
    DECISIONS.clear()
    spend_before = SPEND["usd"]
    canary_before = canary()
    started = time.monotonic()
    steps = []
    for turn in case["turns"]:
        steps.append(await run_step(turn))
        if SPEND["usd"] > budget:
            raise BudgetStop(f"spent ${SPEND['usd']:.3f} > ${budget:.2f}")
    build, live_page = {}, {}
    if built and case.get("build"):
        build, live_page = await settle_build(float(case.get("max_s", 900)))
    elapsed = time.monotonic() - started
    golden, live = fixture.golden_hashes(), fixture.live_hashes()
    changed = sorted(key for key in set(golden) | set(live) if golden.get(key) != live.get(key))
    files = {}
    for item in case.get("asserts") or []:
        rel = item["file"]
        files[rel] = {"before": fixture.read_value(rel, golden=True), "after": fixture.read_value(rel, golden=False)}
    return {
        "case": case["id"],
        "layer": case.get("layer", ""),
        "rep": rep,
        "steps": steps,
        "changed": changed,
        "files": files,
        "outbound": {key.split(":", 1)[1]: value for key, value in EFFECTS.items() if key.startswith("outbound:")},
        "build_calls": EFFECTS["build_calls"],
        "docker_calls": EFFECTS["docker_calls"],
        "canary_ok": canary() == canary_before,
        "elapsed": round(elapsed, 2),
        "spend": round(SPEND["usd"] - spend_before, 5),
        "build": build,
        "live": live_page,
    }


# --------------------------------------------------------------------------- modes


def print_record(rec: dict, verdict: str) -> None:
    print(f"{rec.get('case', rec.get('i'))} rep{rec.get('rep', '')} {verdict}  {rec.get('elapsed', 0)}s  ${rec.get('spend', 0):.4f}", flush=True)


async def run_cases(args) -> int:
    doc = json.loads(common.CASES.read_text(encoding="utf-8"))
    errors = score.validate(doc)
    if errors:
        print("cases.json is invalid:\n  " + "\n  ".join(errors))
        return 2
    selected = [case for case in doc["cases"] if not args.only or case["id"] in args.only]
    if args.dry:
        for case in selected:
            flag = " needs-build" if case.get("needs_build") else ""
            print(f"{case['id']:6} {case.get('layer', ''):8} turns={len(case['turns'])}{flag}")
        print(f"{len(selected)} cases x {args.repeat} = {len(selected) * args.repeat} runs; budget ${args.budget}")
        return 0
    if not args.dev:
        lock = common.LOCK.read_text(encoding="utf-8").strip() if common.LOCK.is_file() else ""
        if not lock or lock != common.sha256(common.CASES):
            print("cases.json does not match cases.lock (or no lock yet). Run `lock` after the owner approves the cases, or pass --dev.")
            return 2

    run_dir = common.EVAL_HOME / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    boot(fixture.STATE, common.FIXTURE_PHONE)
    fixture.build_golden()
    from app.state_store import tenant_scope

    write_json(run_dir / "manifest.json", manifest(args.run_id, "cases", args))
    out = (run_dir / "records.jsonl").open("w", encoding="utf-8")
    stopped = ""
    built_ready = (common.GOLDEN_BUILT / "manifest.json").is_file() and (common.GOLDEN_BUILT / "job.json").is_file()
    ran_built = False
    with tenant_scope(common.FIXTURE_PHONE):
        try:
            for case in selected:
                if case.get("needs_build") and not built_ready:
                    out.write(json.dumps({"case": case["id"], "layer": case.get("layer", ""), "skipped": "needs a real build of the fixture (not built yet)"}, ensure_ascii=False) + "\n")
                    print(f"{case['id']} skipped: needs a real build of the fixture", flush=True)
                    continue
                for rep in range(1, args.repeat + 1):
                    with contextlib.ExitStack() as stack:
                        stubbed(stack, built=bool(case.get("needs_build")))
                        rec = await run_case(case, rep, args.budget)
                    ran_built = ran_built or bool(case.get("needs_build"))
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    print_record(rec, "done")
        except BudgetStop as exc:
            stopped = str(exc)
        finally:
            if ran_built:
                fixture.restore(built=True)  # leave the container as it was found
    out.close()
    if stopped:
        print(f"STOPPED: {stopped}. Records so far are in {run_dir}.")
        return 3
    print(f"DONE. Records in {run_dir / 'records.jsonl'}")
    return 0


async def run_real(args) -> int:
    rows_path = common.REAL_TURNS / "replay2-input.jsonl"
    labels_path = common.REAL_TURNS / "replay2-labels-all.json"
    if not rows_path.is_file() or not labels_path.is_file():
        print(f"real turns are not on this machine: expected {rows_path} and {labels_path}")
        return 2
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    labelled = [(index, row) for index, row in enumerate(rows, 1) if labels.get(str(index), {}).get("label") not in (None, "", "unclear")]
    if args.dry:
        print(f"{len(rows)} turns, {len(labelled)} labelled (unclear excluded); {args.repeat} repeats; budget ${args.budget}")
        return 0

    state = common.EVAL_HOME / "state-real"
    if state.exists():
        import shutil

        shutil.rmtree(state)
    (state / "tenants").mkdir(parents=True)
    import shutil

    shutil.copytree(common.PROD_DATA / "tenants" / common.OWNER, state / "tenants" / common.OWNER, ignore=shutil.ignore_patterns(".lock-*"))
    for name in ("settings.json", "llm-routing.json", "ai-budget.json", "profiles.json"):
        if (common.PROD_DATA / name).is_file():
            shutil.copy(common.PROD_DATA / name, state / name)
    boot(state, common.OWNER)
    from app.services import decider_service, router_service
    from app.services.llm import complete_tools
    from app.services.shop_service import current_shop
    from app.state_store import tenant_scope

    run_dir = common.EVAL_HOME / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "manifest.json", manifest(args.run_id, "real-routes", args))
    out = (run_dir / "real.jsonl").open("w", encoding="utf-8")
    stopped = ""
    with tenant_scope(common.OWNER):
        try:
            for rep in range(1, args.repeat + 1):
                for index, row in labelled:
                    label = labels[str(index)]["label"]
                    gate = router_service.decide(row["text"], use_decider=True)
                    rec = {"i": index, "rep": rep, "label": label, "gate": gate.get("kind")}
                    if gate.get("kind") != "model":
                        rec["skipped"] = "gate"
                        out.write(json.dumps(rec) + "\n")
                        continue
                    if SPEND["usd"] > args.budget:
                        raise BudgetStop(f"spent ${SPEND['usd']:.3f} > ${args.budget:.2f}")
                    history = [*(row.get("context") or []), {"role": "user", "text": row["text"]}]
                    state_doc = decider_service.state_from(history, shop=current_shop() or {}, card_open=False, last_post=False, media=None)
                    decision = await decider_service.choose(state_doc, timeout=8.0)
                    action = str((decision or {}).get("action") or "")
                    tool = decider_service._ACTIONS.get(action, ("", {}))[0] if action else ""
                    rec["decider"] = {"action": action, "tool": tool, "failed": decision is None}
                    SPEND["usd"] += cost_of((decision or {}).get("usage")) or PER_CALL_USD
                    try:
                        chat = await complete_tools(messages=router_service._chooser_history(row["text"]), tools=router_service.TOOLS, max_tokens=150, timeout=30)
                        calls = chat.get("tool_calls") or []
                        rec["chat"] = {"tool": str(calls[0].get("name") or "") if calls else ""}
                        SPEND["usd"] += cost_of(chat.get("usage")) or PER_CALL_USD
                    except Exception as exc:
                        rec["chat"] = {"failed": type(exc).__name__}
                    rec["spend"] = round(SPEND["usd"], 5)
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                print(f"rep {rep} done, spent ${SPEND['usd']:.4f}", flush=True)
        except BudgetStop as exc:
            stopped = str(exc)
    out.close()
    if stopped:
        print(f"STOPPED: {stopped}")
        return 3
    print(f"DONE. Records in {run_dir / 'real.jsonl'}")
    return 0


def lock() -> int:
    doc = json.loads(common.CASES.read_text(encoding="utf-8"))
    errors = score.validate(doc)
    if errors:
        print("refusing to lock an invalid cases.json:\n  " + "\n  ".join(errors))
        return 2
    common.LOCK.write_text(common.sha256(common.CASES) + "\n", encoding="utf-8")
    print(f"locked {len(doc['cases'])} cases: {common.LOCK.read_text(encoding='utf-8').strip()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("lock")
    for name in ("cases", "real-routes"):
        p = sub.add_parser(name)
        p.add_argument("--run-id", required=True)
        p.add_argument("--repeat", type=int, default=3)
        p.add_argument("--budget", type=float, default=0.4)
        p.add_argument("--dry", action="store_true")
        if name == "cases":
            p.add_argument("--only", nargs="*", default=[])
            p.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    if args.mode == "lock":
        return lock()
    if args.mode == "cases":
        return asyncio.run(run_cases(args))
    return asyncio.run(run_real(args))


if __name__ == "__main__":
    raise SystemExit(main())
