#!/usr/bin/env python3
"""Standalone test for tools/train_nightly.py. Run: python3 tools/train_nightly_test.py"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


def _tool():
    path = Path(__file__).resolve().parent / "train_nightly.py"
    spec = importlib.util.spec_from_file_location("train_nightly", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


train_nightly = _tool()
DAY = "2026-09-28"


def _example(eid, text, *, task="inbox_reply", source="real", path="template", messages=None):
    return {
        "id": eid,
        "ts": 1.0,
        "task": task,
        "tenant": "a" * 16,
        "source": source,
        "messages": messages or [{"role": "user", "content": "قیمت چند است؟"}],
        "output": {"text": text, "path": path},
        "labels": {},
    }


class TrainNightlyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.raw = self.root / "raw"
        self.out = self.root / "out"
        day = self.raw / DAY
        day.mkdir(parents=True)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def _write(self, name, rows):
        path = self.raw / DAY / name
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def test_full_build_pipeline(self) -> None:
        self._write(
            "inbox_reply.jsonl",
            [
                _example("e1", "قیمت ۱۰۰ تومان است."),  # labeled accept → SFT
                _example("e2", "قیمت ۲۰۰ تومان است."),  # seller-edited → SFT + DPO
                _example("e2", "قیمت ۲۰۰ تومان است."),  # duplicate id → dropped
                _example("e3", "قیمت ۱۰۰ تومان است."),  # near-duplicate of e1 → dropped
                _example("e4", "شماره‌ام ۰۹۱۲۳۴۵۶۷۸۹ است."),  # PII leak → dropped
                _example("e5", "همکارم به‌زودی جواب می‌دهد", path="handoff"),  # set aside
                _example("e6", "پیشنهاد من این است", source="battery"),  # counted, not trained
                _example("e7", "بدون برچسب"),  # unlabeled → pending
                _example("e8", "رد شده"),  # accept False → out of SFT/DPO
            ],
        )
        self._write(
            "_labels.jsonl",
            [
                {"exampleId": "e1", "labels": {"accept": True}},
                {"exampleId": "e2", "labels": {"editedText": "قیمت ۲۵۰ تومان است."}},
                {"exampleId": "e8", "labels": {"accept": False}},
            ],
        )
        stats = train_nightly.build(raw=self.raw, out=self.out, day=DAY)
        self.assertEqual(stats["raw"], 9)
        self.assertEqual(stats["piiDropped"], 1)
        self.assertEqual(stats["dupesDropped"], 2)
        self.assertEqual(stats["labelsJoined"], 3)
        task = stats["tasks"]["inbox_reply"]
        self.assertEqual(task["examples"], 6)  # 9 - pii - 2 dupes
        self.assertEqual(task["handoff"], 1)
        self.assertEqual(task["labeled"], 3)  # e1, e2, e8
        self.assertEqual(task["sft"], 2)  # e1, e2 (battery e6 and unlabeled e7 stay out)
        self.assertEqual(task["dpo"], 1)  # e2 pair
        self.assertEqual(stats["sources"], {"real": 5, "battery": 1})
        self.assertEqual(oct(self.out.stat().st_mode & 0o777), "0o700")

        sft = [json.loads(line) for line in (self.out / "sft" / DAY / "inbox_reply.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(sft), 2)
        by_id = {row["id"]: row for row in sft}
        self.assertEqual(by_id["e2"]["messages"][-1]["role"], "assistant")
        self.assertEqual(by_id["e2"]["messages"][-1]["content"], "قیمت ۲۵۰ تومان است.")
        dpo = [json.loads(line) for line in (self.out / "dpo" / DAY / "inbox_reply.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(dpo), 1)
        self.assertEqual(dpo[0]["chosen"], "قیمت ۲۵۰ تومان است.")
        self.assertEqual(dpo[0]["rejected"], "قیمت ۲۰۰ تومان است.")
        self.assertTrue((self.out / f"stats-{DAY}.json").is_file())

    def test_battery_override_flag(self) -> None:
        self._write("inbox_reply.jsonl", [_example("b1", "جواب باتری", source="battery")])
        self._write("_labels.jsonl", [{"exampleId": "b1", "labels": {"accept": True}}])
        stats = train_nightly.build(raw=self.raw, out=self.out, day=DAY, allow_sources={"real", "battery"})
        self.assertEqual(stats["tasks"]["inbox_reply"]["sft"], 1)

    def test_empty_day_is_quiet(self) -> None:
        stats = train_nightly.build(raw=self.raw, out=self.out, day="2000-01-01")
        self.assertEqual(stats["raw"], 0)
        self.assertEqual(stats["sft"], 0)

    def test_sft_answers_keep_persian_digits_but_links_stay_latin(self) -> None:
        self._write("inbox_reply.jsonl", [_example("f1", "قیمت 250000 تومان است. لینک: https://shop.example/p/x-2")])
        self._write("_labels.jsonl", [{"exampleId": "f1", "labels": {"accept": True}}])
        train_nightly.build(raw=self.raw, out=self.out, day=DAY)
        sft = [json.loads(line) for line in (self.out / "sft" / DAY / "inbox_reply.jsonl").read_text(encoding="utf-8").splitlines()]
        answer = sft[0]["messages"][-1]["content"]
        self.assertEqual(answer, "قیمت ۲۵۰۰۰۰ تومان است. لینک: https://shop.example/p/x-2")
        self.assertEqual(train_nightly.fa_digits("سفارش 12 در https://s.ir/p/a-3 تمام"), "سفارش ۱۲ در https://s.ir/p/a-3 تمام")

    def test_synthetic_enters_sft_only_with_accept_label(self) -> None:
        self._write(
            "inbox_reply.jsonl",
            [
                _example("s1", "جواب تأییدشده", source="synthetic"),
                _example("s2", "بدون برچسب مصنوعی", source="synthetic"),
                _example("s3", "ردشده", source="synthetic"),
            ],
        )
        self._write(
            "_labels.jsonl",
            [
                {"exampleId": "s1", "labels": {"accept": True, "autoCheck": "price"}},
                {"exampleId": "s3", "labels": {"accept": False}},
            ],
        )
        stats = train_nightly.build(raw=self.raw, out=self.out, day=DAY)
        self.assertEqual(stats["tasks"]["inbox_reply"]["sft"], 1)

    def test_other_tasks_are_split_apart(self) -> None:
        self._write(
            "caption.jsonl",
            [_example("c1", "کپشن آماده است", task="caption"), {"exampleId": "c1", "labels": {"accept": True}}],
        )
        self._write("_labels.jsonl", [{"exampleId": "c1", "labels": {"accept": True}}])
        stats = train_nightly.build(raw=self.raw, out=self.out, day=DAY)
        self.assertIn("caption", stats["tasks"])
        self.assertTrue((self.out / "sft" / DAY / "caption.jsonl").is_file())
        self.assertFalse((self.out / "sft" / DAY / "inbox_reply.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
