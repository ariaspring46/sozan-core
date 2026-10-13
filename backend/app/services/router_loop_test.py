from __future__ import annotations

import unittest

from app.services import router_loop
from app.state_store import tenant_scope


class GoalQueueTests(unittest.TestCase):
    """A plan with several goals keeps all of them: the current goal and a queue behind it."""

    def test_every_goal_line_is_kept_in_order(self) -> None:
        text = "پلن:\n- هدف: گزینهٔ A را بساز\n- توضیح کوتاه\n- هدف: گزینهٔ B را بساز\n- هدف: گزینهٔ A را بساز"
        self.assertEqual(router_loop._goal_lines(text), ["گزینهٔ A را بساز", "گزینهٔ B را بساز"])
        self.assertEqual(router_loop._goal_line(text), "گزینهٔ A را بساز")

    def test_a_plan_without_goal_lines_keeps_its_first_line(self) -> None:
        self.assertEqual(router_loop._goal_lines("اولین خط\nدومین خط"), ["اولین خط"])
        self.assertEqual(router_loop._goal_lines(""), [])

    def test_finishing_a_goal_moves_to_the_next_one(self) -> None:
        with tenant_scope("09129900031"):
            state = {"goal": "A", "goalQueue": ["B"], "planSkill": "ui-ux-pro-max", "suggestions": "s"}
            self.assertTrue(router_loop._advance_goal(state, "ui-ux-pro-max"))
            self.assertEqual(state["goal"], "B")
            self.assertEqual(state["goalQueue"], [])
            saved = router_loop._load_goal()
            self.assertEqual(saved["goal"], "B")
            self.assertFalse(saved["reached"])
            self.assertFalse(router_loop._advance_goal(state, "ui-ux-pro-max"))
            self.assertTrue(router_loop._load_goal()["reached"])


if __name__ == "__main__":
    unittest.main()
