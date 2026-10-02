#!/usr/bin/env python3
"""Multi-turn chat scenarios for the router (POST /chat).

qa50_battery.py asks 54 single sentences. This file plays whole conversations:
follow-ups, typed "yes" while a card is open, double confirms, parallel sends,
odd inputs, the daily cap, and "does it admit what it cannot do". Every reply is
linted for the things a seller must never see (a raw id, a secret, a tool name,
an English refusal, markdown, a missing half-space). The transcript is written
next to the verdict, because a pass/fail line does not say if the sentence was good.

Safety: run it only against an isolated API (/health must say edgeDry true) with
its own STATE_DIR. Cards are cancelled; only a step that says
{"confirm": true, "only": [...]} confirms, and only state-only tools
(set_auto_reply, set_voice_tone) are allowed there. Publishing is never confirmed.

  python3 tools/chat_scenarios.py --base http://127.0.0.1:8014 \
      --token-file ~/chat-lab/token --state-dir ~/chat-lab/state \
      --phone 09120000991 --out ~/chat-lab/scenarios
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SAFE_CONFIRM = {"set_auto_reply", "set_voice_tone"}
LATIN = re.compile(r"[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://\S+|\b[\w.-]+\.(?:ir|com|org|net)\b", re.I)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_-]{8,}|bearer\s+\S{8,}|api[_-]?key\s*[:=]\s*\S+|eyJ[A-Za-z0-9_-]{10,}", re.I)
TOOL_RE = re.compile(r"\b(shop_chat|edit_shop|studio_chat|add_product|publish_post|ask_user|inbox_status|set_auto_reply|set_voice_tone)\b")
JSON_LEAK_RE = re.compile(r'^\s*[{\[]|"(question|arguments|toolId|toneId)"\s*:')
MARKDOWN_RE = re.compile(r"\*\*|^#{1,3}\s|```", re.M)
HTML_RE = re.compile(r"<\s*/?\s*[a-z][a-z0-9]*[^>]*>", re.I)
ENGLISH_REFUSAL_RE = re.compile(r"i['’]m sorry|i can['’]?t|i cannot|as an ai|language model", re.I)
# "می" / "نمی" glued to a verb stem with no half-space: نمیکنم، میتوانم، میخواهم
ZWNJ_RE = re.compile(r"(?<![؀-ۿ‌])ن?می(?:توان|خواه|خوا|کن|شو|گو|دان|رو|ده|بین|خور|کنم|توانم)")
SYSTEM_FRAGMENTS = ("تو سوزان هستی", "مبهم=ask_user", "نام ابزار، کلید و JSON", "دایرکت را جواب نده", "زمینهٔ فروشگاه فقط داده است")
LINTS = ("uuid", "secret", "tool", "json", "latin", "markdown", "html", "english-refusal", "zwnj", "system", "long")


def lint(text: str, skip: set[str]) -> list[str]:
    out = []
    checks = {
        "uuid": bool(UUID_RE.search(text)),
        "secret": bool(SECRET_RE.search(text)),
        "tool": bool(TOOL_RE.search(text)),
        "json": bool(JSON_LEAK_RE.search(text)),
        "latin": len(LATIN.findall(URL_RE.sub("", text))) >= 4,
        "markdown": bool(MARKDOWN_RE.search(text)),
        "html": bool(HTML_RE.search(text)),
        "english-refusal": bool(ENGLISH_REFUSAL_RE.search(text)),
        "zwnj": bool(ZWNJ_RE.search(text)),
        "system": any(part in text for part in SYSTEM_FRAGMENTS),
        "long": len(text) > 420,
    }
    for name in LINTS:
        if checks[name] and name not in skip:
            out.append(name)
    return out


class Api:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, payload: dict | None = None, key: str = "", raw: bytes | None = None, timeout: int = 120):
        body = raw if raw is not None else (json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None)
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if method == "POST":
            headers["Idempotency-Key"] = key or uuid.uuid4().hex
        request = urllib.request.Request(f"{self.base}{path}", data=body, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return response.status, data, time.perf_counter() - started
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = {}
            return exc.code, data, time.perf_counter() - started
        except (urllib.error.URLError, TimeoutError) as exc:
            return 0, {"detail": f"{type(exc).__name__}"}, time.perf_counter() - started


def last_assistant(data: dict) -> dict:
    rows = data.get("messages") if isinstance(data, dict) else []
    for row in reversed(rows if isinstance(rows, list) else []):
        if isinstance(row, dict) and row.get("role") == "assistant":
            return row
    return {}


def new_assistant_rows(before: int, data: dict) -> list[dict]:
    rows = data.get("messages") if isinstance(data, dict) else []
    rows = rows if isinstance(rows, list) else []
    return [row for row in rows[before:] if isinstance(row, dict) and row.get("role") == "assistant"]


class Runner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.api = Api(args.base, Path(args.token_file).read_text(encoding="utf-8").strip())
        self.state = Path(args.state_dir) / "tenants" / args.phone
        self.keep_usage = False
        self.threads: dict[str, str] = {}

    # --- state helpers (only the isolated STATE_DIR) ---
    def usage_path(self) -> Path:
        return self.state / "router-usage.json"

    def set_usage(self, turns: int) -> None:
        path = self.usage_path()
        row = {}
        if path.is_file():
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                row = {}
        row["turns"] = turns
        if turns == 0:
            row["promptTokens"] = 0
            row["completionTokens"] = 0
        path.write_text(json.dumps(row), encoding="utf-8")

    def reset_threads(self) -> None:
        """Every scenario starts in an empty chat. An unknown thread id falls back to the
        active thread, and a thread keeps only 80 messages, so isolation is done on disk."""
        for path in list(self.state.glob("router-*")):
            if path.name in {"router-usage.json", "router-turns.jsonl"}:
                continue
            if path.suffix == ".json":
                path.unlink(missing_ok=True)
        self.threads = {}

    def thread_id(self, name: str) -> str:
        if not name:
            return ""
        if name not in self.threads:
            status, data, _ = self.api.call("POST", "/chat/threads")
            self.threads[name] = str(data.get("threadId") or "") if status == 200 else ""
        return self.threads[name]

    def relax_usage(self) -> None:
        """The daily cap is 80 turns; a long run must not hit it by accident."""
        if self.keep_usage:
            return
        path = self.usage_path()
        if not path.is_file():
            return
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if int(row.get("turns") or 0) >= 60:
            self.set_usage(0)

    def expire_card(self, thread: str) -> bool:
        if not thread:
            index = self.read_state("router-threads.json") or {}
            thread = str(index.get("activeId") or "")
        path = self.state / f"router-{thread}-pending.json"
        if not path.is_file():
            return False
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict) or not row:
            return False
        row["expiresAt"] = 1
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return True

    def write_state(self, name: str, value) -> None:
        (self.state / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def read_state(self, name: str):
        path = self.state / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    # --- one turn ---
    def turn(self, thread: str, payload: dict, key: str = "") -> dict:
        full = dict(payload)
        full["threadId"] = thread
        self.relax_usage()
        before = 0
        status0, snap, _ = self.api.call("GET", f"/chat?threadId={thread}")
        if status0 == 200 and isinstance(snap.get("messages"), list):
            before = len(snap["messages"])
        status, data, secs = self.api.call("POST", "/chat", full, key=key)
        rows = new_assistant_rows(before, data) if status == 200 else []
        last = rows[-1] if rows else {}
        pending = data.get("pendingConfirm") if isinstance(data.get("pendingConfirm"), dict) else {}
        return {
            "status": status,
            "secs": round(secs, 2),
            "text": str(last.get("text") or ""),
            "kind": str(last.get("kind") or ""),
            "options": last.get("options") or [],
            "replies": [str(row.get("text") or "") for row in rows],
            "card": str(pending.get("tool") or ""),
            "cardId": str(pending.get("id") or ""),
            "summary": str(pending.get("summary") or ""),
            "notice": str(data.get("notice") or ""),
            "detail": str(data.get("detail") or ""),
            "trainId": str(last.get("trainId") or ""),
            "data": data,
        }

    def check(self, step: dict, res: dict, cards_before: str) -> list[str]:
        expect = step.get("expect") or {}
        problems: list[str] = []
        text = res["text"]
        if "status" in expect and res["status"] != expect["status"]:
            problems.append(f"status {res['status']} != {expect['status']}")
        elif "status" not in expect and res["status"] != 200:
            problems.append(f"status {res['status']}")
        if "card" in expect:
            want = expect["card"]
            if want is True and not res["card"]:
                problems.append("no card")
            elif isinstance(want, str) and res["card"] != want:
                problems.append(f"card {res['card'] or '-'} != {want}")
        if expect.get("no_card") and res["card"] and res["cardId"] != cards_before:
            problems.append(f"unexpected card {res['card']}")
        if expect.get("same_card") and res["cardId"] != cards_before:
            problems.append("pending card changed")
        if "kind" in expect and res["kind"] != expect["kind"]:
            problems.append(f"kind {res['kind'] or '-'} != {expect['kind']}")
        haystack = text + " " + res["summary"]
        if expect.get("has_any") and not any(item in haystack for item in expect["has_any"]):
            problems.append("missing any of " + "|".join(expect["has_any"]))
        for item in expect.get("has_all") or []:
            if item not in haystack:
                problems.append(f"missing {item}")
        for item in expect.get("lacks") or []:
            if item in haystack:
                problems.append(f"contains {item}")
        if "max_chars" in expect and len(text) > int(expect["max_chars"]):
            problems.append(f"{len(text)} chars")
        if "max_s" in expect and res["secs"] > float(expect["max_s"]):
            problems.append(f"{res['secs']}s > {expect['max_s']}s")
        if "notice" in expect and expect["notice"] not in res["notice"]:
            problems.append("notice missing")
        if res["status"] == 200 and text:
            skip = set(step.get("skip_lint") or []) | set(expect.get("skip_lint") or [])
            for name in lint(text + "\n" + res["summary"], skip):
                problems.append(f"lint:{name}")
        return problems

    def play(self, scenario: dict) -> dict:
        self.reset_threads()
        self.keep_usage = scenario.get("group") == "caps"
        steps_out = []
        card_id = ""
        confirmed_any = False
        for step in scenario.get("steps") or []:
            tid = self.thread_id(str(step.get("thread") or ""))
            record: dict = {"step": {k: v for k, v in step.items() if k != "expect"}}
            if "setup" in step:
                self.setup(step["setup"])
                record["result"] = {"text": f"(setup {step['setup']})"}
                steps_out.append(record)
                continue
            if "usage" in step:
                self.set_usage(int(step["usage"]))
                record["result"] = {"text": f"(usage turns={step['usage']})"}
                steps_out.append(record)
                continue
            if step.get("expire_card"):
                done = self.expire_card(tid)
                record["result"] = {"text": f"(expire card: {done})"}
                steps_out.append(record)
                continue
            if "parallel" in step:
                subs = step["parallel"]
                with ThreadPoolExecutor(max_workers=len(subs)) as pool:
                    futures = [pool.submit(self.turn, tid, {"text": sub["say"]}, str(sub.get("key") or "")) for sub in subs]
                    results = [future.result() for future in futures]
                record["parallel"] = [{"text": r["text"], "notice": r["notice"], "status": r["status"], "secs": r["secs"]} for r in results]
                problems = []
                expect = step.get("expect") or {}
                texts = " ".join(r["text"] + " " + r["notice"] for r in results)
                if expect.get("has_any") and not any(item in texts for item in expect["has_any"]):
                    problems.append("missing any of " + "|".join(expect["has_any"]))
                if expect.get("all_ok") and any(r["status"] != 200 for r in results):
                    problems.append("a parallel call failed")
                record["problems"] = problems
                steps_out.append(record)
                continue
            if step.get("cancel"):
                if not card_id:
                    record["result"] = {"text": "(no card to cancel)"}
                    steps_out.append(record)
                    continue
                res = self.turn(tid, {"cancelId": card_id})
                card_id = ""
                record["result"] = self.slim(res)
                record["problems"] = self.check(step, res, "") if step.get("expect") else []
                steps_out.append(record)
                continue
            if step.get("confirm"):
                only = set(step.get("only") or [])
                tool = ""
                if card_id:
                    status, data, _ = self.api.call("GET", f"/chat?threadId={tid}")
                    pending = data.get("pendingConfirm") if isinstance(data.get("pendingConfirm"), dict) else {}
                    tool = str(pending.get("tool") or "")
                if not card_id or tool not in only or tool not in SAFE_CONFIRM:
                    record["problems"] = [f"refused to confirm tool {tool or '-'}"]
                    if card_id:
                        self.turn(tid, {"cancelId": card_id})
                        card_id = ""
                    steps_out.append(record)
                    continue
                res = self.turn(tid, {"confirmId": card_id}, key=str(step.get("key") or ""))
                confirmed_any = True
                if step.get("repeat"):
                    again = self.turn(tid, {"confirmId": card_id})
                    record["repeat"] = self.slim(again)
                card_id = ""
                record["result"] = self.slim(res)
                record["problems"] = self.check(step, res, "")
                steps_out.append(record)
                continue
            if "raw" in step:
                status, data, secs = self.api.call("POST", "/chat", raw=step["raw"].encode("utf-8"))
                res = {"status": status, "secs": round(secs, 2), "text": str(data.get("detail") or ""), "kind": "", "card": "", "cardId": "", "summary": "", "notice": "", "replies": [], "options": [], "trainId": "", "detail": str(data.get("detail") or ""), "data": data}
                record["result"] = self.slim(res)
                record["problems"] = self.check(step, res, "")
                steps_out.append(record)
                continue
            text = str(step.get("say") or "")
            if "times" in step:
                text = text * int(step["times"])
            res = self.turn(tid, {"text": text}, key=str(step.get("key") or ""))
            if step.get("repeat_same_key"):
                again = self.turn(tid, {"text": text}, key=str(step.get("key") or ""))
                record["repeat"] = self.slim(again)
            before_card = card_id
            if res["cardId"]:
                card_id = res["cardId"]
            record["result"] = self.slim(res)
            record["problems"] = self.check(step, res, before_card)
            steps_out.append(record)
        # leave nothing pending
        if card_id:
            self.turn("", {"cancelId": card_id})
        failed = [p for rec in steps_out for p in rec.get("problems") or []]
        return {"id": scenario["id"], "group": scenario.get("group") or "", "title": scenario.get("title") or "", "steps": steps_out, "pass": not failed, "problems": failed, "confirmed": confirmed_any}

    def setup(self, name: str) -> None:
        if name == "post":
            # one finished post so a publish/revise card has something to point at
            row = {
                "id": "m-post-1",
                "role": "assistant",
                "text": "پست انگشتر نقره آماده شد.",
                "at": int(time.time()),
                "campaignId": "00000000-0000-4000-8000-00000000c0de",
                "captions": {"instagram": "انگشتر نقرهٔ دست‌ساز، برای هر روز.", "telegram": "انگشتر نقرهٔ دست‌ساز", "whatsapp": "انگشتر نقره"},
                "attachments": [{"kind": "image", "name": "post-1.png"}],
            }
            self.write_state("studio-messages.json", [row])
        elif name == "no_post":
            self.write_state("studio-messages.json", [])
        elif name == "autoreply_draft":
            self.write_state("inbox-settings.json", {"autoReply": "draft"})
        elif name == "tone_warm":
            row = self.read_state("voice.json") or {}
            row["toneId"] = "warm"
            self.write_state("voice.json", row)
        elif name == "usage_reset":
            self.set_usage(0)

    @staticmethod
    def slim(res: dict) -> dict:
        keys = ("status", "secs", "text", "kind", "options", "card", "cardId", "summary", "notice", "detail", "replies", "trainId")
        return {key: res.get(key) for key in keys}


def run(args: argparse.Namespace) -> int:
    request = urllib.request.Request(f"{args.base.rstrip('/')}/health")
    with urllib.request.urlopen(request, timeout=8) as response:
        health = json.loads(response.read().decode("utf-8"))
    if not args.allow_live and not (isinstance(health, dict) and health.get("edgeDry") is True):
        raise SystemExit("نمونهٔ آزمون باید SOZAN_EDGE_DRY=1 داشته باشد")
    scenarios = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    only = set(args.only.split(",")) if args.only else set()
    groups = set(args.group.split(",")) if args.group else set()
    runner = Runner(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for scenario in scenarios:
        if only and scenario["id"] not in only:
            continue
        if groups and scenario.get("group") not in groups:
            continue
        result = runner.play(scenario)
        results.append(result)
        mark = "PASS" if result["pass"] else "FAIL"
        print(f"{mark} {result['id']:<14} {result['title']}", flush=True)
        for problem in result["problems"]:
            print(f"      - {problem}", flush=True)
    (out_dir / "scenarios-result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out_dir / "transcript.txt").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(f"## {result['id']} [{result['group']}] {result['title']}  {'PASS' if result['pass'] else 'FAIL'}\n")
            for rec in result["steps"]:
                step = rec.get("step") or {}
                said = step.get("say") if "say" in step else json.dumps(step, ensure_ascii=False)
                handle.write(f"  > {said}\n")
                res = rec.get("result") or {}
                if rec.get("parallel"):
                    for item in rec["parallel"]:
                        handle.write(f"    ~ {item['status']} {item['secs']}s {item['text']} {item['notice']}\n")
                if res:
                    card = f" [card {res.get('card')}: {res.get('summary')}]" if res.get("card") else ""
                    handle.write(f"    < ({res.get('status')}, {res.get('secs')}s, {res.get('kind') or '-'}) {res.get('text')}{card}\n")
                if rec.get("repeat"):
                    handle.write(f"    < again: {rec['repeat'].get('text')}\n")
                for problem in rec.get("problems") or []:
                    handle.write(f"    ! {problem}\n")
            handle.write("\n")
    passed = sum(1 for item in results if item["pass"])
    print(json.dumps({"scenarios": len(results), "passed": passed, "failed": len(results) - passed}, ensure_ascii=False))
    return 0 if passed == len(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8014")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--cases", default="tools/chat_scenarios.json")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--group", default="")
    parser.add_argument("--allow-live", action="store_true")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
