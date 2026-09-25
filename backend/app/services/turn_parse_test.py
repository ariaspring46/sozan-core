from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.services.loop_watch import blocked
from app.services.turn_parse import parse_turn, registry


class TurnParseTests(unittest.TestCase):
    def test_registry_examples_match_the_parser(self) -> None:
        data = registry()
        for row in data["examples"]:
            turn = parse_turn(row["text"])
            self.assertEqual(turn.act, row["act"], row["text"])
            self.assertEqual(turn.write, row["write"], row["text"])
            if "topic" in row:
                self.assertEqual(turn.topic, row["topic"], row["text"])
            if "revise" in row:
                self.assertEqual(turn.revise, row["revise"], row["text"])
        for row in data["counter_examples"]:
            turn = parse_turn(row["text"])
            if "not_topic" in row:
                self.assertNotEqual(turn.topic, row["not_topic"], row["text"])
            if "not_act" in row:
                self.assertNotEqual(turn.act, row["not_act"], row["text"])

    def test_spec_file_has_the_four_states(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data" / "router_spec.json"
        states = json.loads(path.read_text(encoding="utf-8"))["states"]
        self.assertEqual(set(states), {"idle", "built", "card_open", "composing"})

    def test_loop_watch_flags_a_stale_beat(self) -> None:
        self.assertFalse(blocked(10, 14))
        self.assertTrue(blocked(10, 16))


if __name__ == "__main__":
    unittest.main()
