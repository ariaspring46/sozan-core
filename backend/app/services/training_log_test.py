import contextvars
import unittest
from unittest.mock import patch

from app.services import training_log
from app.state_store import tenant_scope


def _settings(patch_key: str | None, value=...):
    rows = {}
    if patch_key is not None:
        rows[patch_key] = value
    return patch("app.services.settings_service.get_settings", lambda: rows)


class TrainingLogTest(unittest.TestCase):
    def test_contract_shape_and_double_mask(self):
        with _settings(None), tenant_scope("09120001111"):
            example = training_log.build_example(
                task="inbox_reply",
                messages=[
                    {"role": "system", "content": "تو فروشنده هستی"},
                    {"role": "user", "content": "قیمت چنده؟ ۰۹۱۲۳۴۵۶۷۸۹ تماس بگیر"},
                ],
                output={"text": "هزار تومان", "path": "model"},
                tools=["stock"],
                teacher="openrouter/anthropic/claude-haiku-4.5",
                latency_ms=1234,
            )
        self.assertIsNotNone(example)
        for key in (
            "id",
            "ts",
            "task",
            "tenant",
            "source",
            "release",
            "promptVersion",
            "teacher",
            "messages",
            "tools",
            "output",
            "labels",
            "latencyMs",
            "costUsd",
        ):
            self.assertIn(key, example)
        self.assertEqual(example["task"], "inbox_reply")
        self.assertEqual(example["source"], "real")
        self.assertEqual(example["output"]["text"], "هزار تومان")
        self.assertNotIn("09120001111", example["tenant"])
        self.assertEqual(len(example["tenant"]), 16)
        self.assertNotIn("۰۹۱۲۳۴۵۶۷۸۹", example["messages"][-1]["content"])
        self.assertIn("[تلفن]", example["messages"][-1]["content"])
        self.assertEqual(example["teacher"], "openrouter/anthropic/claude-haiku-4.5")

    def test_consent_default_on_and_off(self):
        with _settings(None):
            self.assertTrue(training_log.consent_enabled())
        with _settings("sozanImprove", True):
            self.assertTrue(training_log.consent_enabled())
        for off in (False, "false", "off", "0", "خاموش"):
            with _settings("sozanImprove", off):
                self.assertFalse(training_log.consent_enabled())

    def test_consent_off_records_nothing(self):
        captured = []
        with _settings("sozanImprove", False), tenant_scope("09120001111"):
            example = training_log.build_example(
                task="inbox_reply",
                messages=[{"role": "user", "content": "سلام"}],
                output={"text": "سلام، در خدمتم"},
            )
            with patch.object(training_log, "emit_later", lambda **kw: captured.append(kw)):
                self.assertEqual(training_log.log_example(task="inbox_reply", messages=[], output={"text": "جواب"}), "")
                self.assertEqual(training_log.log_label("e1", {"accept": True}), "")
        self.assertIsNone(example)
        self.assertEqual(captured, [])

    def test_voice_never_recorded(self):
        with _settings(None), tenant_scope("09120001111"):
            self.assertIsNone(
                training_log.build_example(
                    task="inbox_reply",
                    messages=[{"role": "user", "content": "سلام"}],
                    output={"text": "سلام"},
                    source="voice",
                )
            )

    def test_empty_output_and_unknown_task_refused(self):
        with _settings(None):
            self.assertIsNone(training_log.build_example(task="other", messages=[], output={"text": "جواب"}))
            self.assertIsNone(training_log.build_example(task="inbox_reply", messages=[], output={"text": " "}))
            self.assertIsNone(training_log.build_example(task="inbox_reply", messages=[], output={}))

    def test_log_example_emits_train_event(self):
        captured = []
        with _settings(None), tenant_scope("09120001111"):
            with patch.object(training_log, "emit_later", lambda **kw: captured.append(kw)):
                eid = training_log.log_example(
                    task="inbox_reply",
                    messages=[{"role": "user", "content": "موجود است؟"}],
                    output={"text": "موجود است."},
                    source="battery",
                    surface="inbox",
                )
        self.assertTrue(eid)
        self.assertEqual(len(captured), 1)
        row = captured[0]
        self.assertEqual(row["kind"], "train")
        self.assertEqual(row["title"], "train-example")
        self.assertEqual(row["surface"], "inbox")
        self.assertEqual(row["payload"]["id"], eid)
        self.assertEqual(row["payload"]["source"], "battery")

    def test_log_label_emits_join_row(self):
        captured = []
        with _settings(None), tenant_scope("09120001111"):
            with patch.object(training_log, "emit_later", lambda **kw: captured.append(kw)):
                out = training_log.log_label("abc", {"accept": True, "editedText": "درست‌شده"})
        self.assertEqual(out, "abc")
        row = captured[0]
        self.assertEqual(row["kind"], "train")
        self.assertEqual(row["title"], "train-label")
        self.assertEqual(row["payload"]["exampleId"], "abc")
        self.assertEqual(row["payload"]["labels"]["editedText"], "درست‌شده")

    def test_tenant_hash_stable_and_separated(self):
        with tenant_scope("09120001111"):
            first = training_log.tenant_hash()
        with tenant_scope("09120001111"):
            again = training_log.tenant_hash()
        with tenant_scope("09120002222"):
            other = training_log.tenant_hash()
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertNotIn("09120001111", first)
        self.assertEqual(contextvars.copy_context().run(training_log.tenant_hash), "")

    def test_fingerprint_distinguishes_pairs(self):
        row = {"messages": [{"role": "user", "content": "سلام"}], "output": {"text": "درود"}}
        same = {"messages": [{"role": "user", "content": "سلام"}], "output": {"text": "درود"}}
        changed = {"messages": [{"role": "user", "content": "سلام"}], "output": {"text": "دیگر"}}
        self.assertEqual(training_log.fingerprint(row), training_log.fingerprint(same))
        self.assertNotEqual(training_log.fingerprint(row), training_log.fingerprint(changed))


if __name__ == "__main__":
    unittest.main()
