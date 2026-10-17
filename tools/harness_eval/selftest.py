#!/usr/bin/env python3
"""Offline tests for score.py: a correct record must pass, and each planted fault must be caught with the right
category. Run before every baseline: a scorer that misses a planted fault cannot be trusted to grade the harness.

  python3 tools/harness_eval/selftest.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402

PRODUCTS_BEFORE = [
    {"title": "انگشتر نقره", "price": 2500000, "stock": 3, "discount": 0},
    {"title": "کیف دستی کوچک", "price": 1200000, "stock": 4, "discount": 0},
    {"title": "دستبند مهره", "price": 450000, "stock": 6, "discount": 0},
]
PRODUCTS_AFTER = copy.deepcopy(PRODUCTS_BEFORE)
PRODUCTS_AFTER[0]["price"] = 2700000

CASE = {
    "id": "E01",
    "layer": "effects",
    "turns": [{"say": "قیمت انگشتر نقره را ۲٬۷۰۰٬۰۰۰ تومان کن", "action": "confirm",
               "expect": {"tool": "edit_product", "card": True, "claim": "success",
                          "args": {"product": "انگشتر نقره", "price": 2700000}}}],
    "effects": {"allowed": ["tenant/products.json"], "must": ["tenant/products.json"]},
    "asserts": [
        {"id": "price", "file": "tenant/products.json", "select": "[title=انگشتر نقره].price", "equals": 2700000},
        {"id": "other-kept", "file": "tenant/products.json", "select": "[title=کیف دستی کوچک].price", "equals": 1200000},
        {"id": "count", "file": "tenant/products.json", "count_delta": 0},
    ],
}

GOOD_STEP = {
    "card": {"id": "c1", "tool": "edit_product", "arguments": {"product": "انگشتر نقره", "price": 2700000}},
    "tool": "edit_product",
    "args": {"product": "انگشتر نقره", "price": 2700000},
    "ask": False,
    "reply": "قیمت انگشتر نقره به ۲٬۷۰۰٬۰۰۰ تومان تغییر کرد.",
    "claim": "success",
    "lint": [],
    "trace": [],
    "calls": [],
    "verify": [{"verify": {"ok": True}}],
    "error": "",
    "write_unconfirmed": [],
}


def record(**over) -> dict:
    rec = {
        "steps": [copy.deepcopy(GOOD_STEP)],
        "changed": ["tenant/products.json"],
        "files": {"tenant/products.json": {"before": PRODUCTS_BEFORE, "after": PRODUCTS_AFTER}},
        "outbound": {},
        "build_calls": 0,
        "canary_ok": True,
        "elapsed": 9.0,
    }
    rec.update(over)
    return rec


def categories(result: dict) -> set[str]:
    return set(result["categories"])


FAILURES: list[str] = []


def expect(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    good = score.score_case(CASE, record())
    expect("correct record passes", good["ok"], str([c for c in good["checks"] if not c["ok"]]))

    # Selector and number handling
    expect("selector finds the row", score.select(PRODUCTS_AFTER, "[title=انگشتر نقره].price") == 2700000)
    expect("selector refuses an ambiguous row", score.select(PRODUCTS_AFTER + PRODUCTS_AFTER[:1], "[title=انگشتر نقره].price") is None)
    expect("persian digits and separators compare as numbers", score.same_value("۲٬۷۰۰٬۰۰۰", 2700000))

    # Mutant 1: edit went to the wrong product; the success claim is then false
    wrong = copy.deepcopy(PRODUCTS_BEFORE)
    wrong[1]["price"] = 2700000
    res = score.score_case(CASE, record(files={"tenant/products.json": {"before": PRODUCTS_BEFORE, "after": wrong}}))
    expect("wrong product edited → wrong-args", "wrong-args" in categories(res), str(categories(res)))
    expect("wrong product with success claim → false-claim", "false-claim" in categories(res), str(categories(res)))

    # Mutant 2: verify says ok but nothing changed (false pass)
    untouched = copy.deepcopy(PRODUCTS_BEFORE)
    res = score.score_case(CASE, record(changed=[], steps=[{**copy.deepcopy(GOOD_STEP), "verify": [{"verify": {"ok": True}}]}],
                                         files={"tenant/products.json": {"before": PRODUCTS_BEFORE, "after": untouched}}))
    expect("verify ok on untouched data → verify-false-pass", "verify-false-pass" in categories(res), str(categories(res)))

    # Mutant 3: verify says failed while the change is in place (false fail)
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "verify": [{"verify": {"ok": False}}]}]))
    expect("verify failed on a correct edit → verify-false-fail", "verify-false-fail" in categories(res), str(categories(res)))

    # Mutant 4: no card where one was expected
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "card": None, "tool": ""}]))
    expect("missing card → wrong-route", "wrong-route" in categories(res), str(categories(res)))

    # Mutant 5: asked a question where a card was expected
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "card": None, "tool": "", "ask": True}]))
    expect("question instead of card → needless-ask", "needless-ask" in categories(res), str(categories(res)))

    # Mutant 6: an unrelated file changed
    res = score.score_case(CASE, record(changed=["tenant/products.json", "tenant/orders.json"]))
    expect("extra file changed → wrong-files", "wrong-files" in categories(res), str(categories(res)))

    # Mutant 7: a write happened with no card
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "card": None, "tool": "edit_product"}]))
    expect("file changed with no card → write-without-card", "write-without-card" in categories(res), str(categories(res)))

    # Mutant 8: outbound message leaked from the fixture
    res = score.score_case(CASE, record(outbound={"inbox.reply": 1}))
    expect("outbound message → outbound-leak", "outbound-leak" in categories(res), str(categories(res)))

    # Mutant 9: isolation canary moved
    res = score.score_case(CASE, record(canary_ok=False))
    expect("moved canary → isolation-breach", "isolation-breach" in categories(res), str(categories(res)))

    # Mutant 10: reply lint hit (e.g. a leaked English tool name)
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "lint": ["latin"]}]))
    expect("lint flag → lint", "lint" in categories(res), str(categories(res)))

    # Mutant 11: too slow
    res = score.score_case(CASE, record(elapsed=500.0))
    expect("slow turn → timeout", "timeout" in categories(res), str(categories(res)))

    # Mutant 12: a step crashed
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "error": "RouterBusy"}]))
    expect("error in a step → crash", "crash" in categories(res), str(categories(res)))

    # Mutant 13: the reply names a different amount than the one asked for
    amount_case = {"id": "R10", "layer": "route", "turns": [{"say": "x", "expect": {"card": True, "amount": 600000}}]}
    res = score.score_case(amount_case, {"steps": [{**copy.deepcopy(GOOD_STEP), "reply": "قیمت از ۲۵۰٬۰۰۰ به ۲۷۰٬۰۰۰ شود؟"}]})
    expect("wrong amount in the reply → wrong-args", "wrong-args" in categories(res), str(categories(res)))
    res = score.score_case(amount_case, {"steps": [{**copy.deepcopy(GOOD_STEP), "reply": "قیمت از ۲۵۰٬۰۰۰ به ۶۰۰٬۰۰۰ شود؟"}]})
    expect("right amount in the reply passes", "wrong-args" not in categories(res), str(categories(res)))

    # Mutant 14: the decider did not answer and the chat model took the turn
    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "decisions": [{"action": ""}]}]))
    expect("decider fell back to chat → decider-down", "decider-down" in categories(res), str(categories(res)))

    res = score.score_case(CASE, record(steps=[{**copy.deepcopy(GOOD_STEP), "trace": [{"fallback": "decider"}], "decisions": [{"action": "find_product"}]}]))
    expect("low-confidence decider (chat fallback) is not a fault", "decider-down" not in categories(res), str(categories(res)))

    # Build case: job built but the live page lacks the new text
    build_case = {"id": "B1", "layer": "build", "build": True, "live_contains": "کالای دست‌ساز",
                  "turns": [{"say": "تیتر را عوض کن", "action": "confirm", "expect": {"card": True}}]}
    res = score.score_case(build_case, {"steps": [copy.deepcopy(GOOD_STEP)], "build": {"buildOk": True, "urlOk": True},
                                        "live": {"text": "خوش آمدید"}, "build_calls": 1, "elapsed": 5})
    expect("live page without the change → live-mismatch", "live-mismatch" in categories(res), str(categories(res)))
    res = score.score_case(build_case, {"steps": [copy.deepcopy(GOOD_STEP)], "build": {"buildOk": True, "urlOk": True},
                                        "live": {"text": "کالای دست‌ساز"}, "build_calls": 1, "elapsed": 5})
    expect("live page with the change passes build", res["ok"], str([c for c in res["checks"] if not c["ok"]]))

    # Real labelled turns
    expect("none label: no tool passes", score.real_ok("none", "", "none"))
    expect("none label: a tool fails", not score.real_ok("none", "edit_product", "tool"))
    expect("ask_user label: question passes", score.real_ok("ask_user", "", "ask_user"))
    expect("edit_product label: exact tool passes", score.real_ok("edit_product", "edit_product", "tool"))
    expect("edit_product label: other tool fails", not score.real_ok("edit_product", "products", "tool"))

    # Schema validation catches bad case files
    bad = {"cases": [
        {"id": "X1", "layer": "nope", "turns": [{"say": "", "action": "maybe", "expect": {"tooll": "x"}}],
         "asserts": [{"file": "/etc/passwd", "changed": True}]},
        {"id": "X1", "layer": "route", "turns": []},
    ]}
    errors = score.validate(bad)
    expect("schema: duplicate id caught", any("duplicate" in e for e in errors), str(errors))
    expect("schema: bad layer caught", any("layer" in e for e in errors), str(errors))
    expect("schema: bad action caught", any("bad action" in e for e in errors), str(errors))
    expect("schema: unknown expect key caught", any("unknown expect" in e for e in errors), str(errors))
    expect("schema: assert outside tenant/site caught", any("tenant/" in e for e in errors), str(errors))
    expect("schema: empty turns caught", any("no turns" in e for e in errors), str(errors))
    expect("the real case file validates", not score.validate(__import__("json").loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))) if (Path(__file__).parent / "cases.json").exists() else True)

    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall selftests passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
