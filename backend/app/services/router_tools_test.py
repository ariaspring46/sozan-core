import asyncio
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import router_loop, router_service, router_tools
from app.services.router_tools import Tool


class RegistryTests(unittest.TestCase):
    def test_the_router_sees_the_same_tools_as_before(self) -> None:
        # order, levels and ranks are what router_service had before the registry (2026-10-09); seller_tools come after
        self.assertEqual(
            [item["function"]["name"] for item in router_service.TOOLS],
            [
                "channel", "status", "inbox_status", "ask_user", "set_auto_reply", "set_voice_tone", "shop_chat", "edit_shop",
                "add_product", "studio_chat", "publish_post",
                "orders", "sales_report", "products", "edit_product", "set_discount", "reply_customer",
                "update_order", "approve_receipt",
            ],
        )
        self.assertEqual(
            router_service.WRITE_TOOLS,
            {
                "set_auto_reply", "set_voice_tone", "edit_shop", "add_product", "studio_chat", "publish_post", "edit_product",
                "set_discount", "reply_customer", "update_order", "approve_receipt",
            },
        )
        self.assertEqual(router_service.READ_TOOLS, {"status", "ask_user", "inbox_status", "channel", "orders", "sales_report", "products"})
        self.assertEqual(router_service.PASSTHROUGH, {"shop_chat"})
        self.assertEqual(router_service._TOOL_RANK["shop_chat"], 1)
        self.assertEqual(router_service._TOOL_RANK["ask_user"], 2)
        self.assertEqual(router_service._TOOL_RANK["status"], 3)
        self.assertEqual(router_service._TOOL_RANK["edit_shop"], 0)

    def test_a_tool_must_name_itself_and_have_a_known_level(self) -> None:
        schema = {"type": "function", "function": {"name": "x_tool", "parameters": {"type": "object", "properties": {}}}}
        with self.assertRaises(ValueError):
            router_tools.register(Tool(name="x_tool", schema=schema, level="maybe"))
        with self.assertRaises(ValueError):
            router_tools.register(Tool(name="other", schema=schema))

    def test_a_toolset_never_adds_another_write(self) -> None:
        for name in router_tools.names():
            extra = router_tools.toolset(name)[1:]
            self.assertTrue(all(router_tools.get(item).level == "read" for item in extra), name)
            self.assertNotIn("ask_user", extra)
        self.assertEqual(router_tools.toolset("set_auto_reply"), ["set_auto_reply", "inbox_status"])
        self.assertIn("status", router_tools.toolset("edit_shop"))
        self.assertEqual(router_tools.toolset("edit_product"), ["edit_product", "products"])
        self.assertEqual(router_tools.toolset("reply_customer"), ["reply_customer", "inbox_status"])

    def test_every_decider_action_names_a_registered_tool(self) -> None:
        from app.services import decider_service

        for action, (tool, _args) in decider_service._ACTIONS.items():
            self.assertTrue(not tool or router_tools.get(tool) is not None, action)
            self.assertIn(action, decider_service._LABELS)
            self.assertIn(action, decider_service._CRITERIA)

    def test_a_tool_module_imported_first_still_reaches_the_router(self) -> None:
        # order_tools imported before the router used to freeze WRITE_TOOLS without its own tools (2026-10-09)
        import subprocess
        import sys
        from pathlib import Path

        code = (
            "import app.services.order_tools\n"
            "from app.services import router_service as r\n"
            "assert {'update_order', 'approve_receipt'} <= r.ALLOWED, sorted(r.ALLOWED)\n"
            "assert [t['function']['name'] for t in r.TOOLS][:2] == ['channel', 'status']\n"
        )
        backend = Path(__file__).resolve().parents[2]
        done = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])

    def test_a_check_answers_before_the_card(self) -> None:
        self.assertIsNone(router_tools.check("status", {}, "وضعیت"))
        self.assertEqual(router_tools.check("set_discount", {"percent": 95, "all": True}, ""), "تخفیف باید بین ۱ تا ۹۰ درصد باشد.")

    def test_a_new_tool_brings_its_own_handler_and_card(self) -> None:
        schema = {"type": "function", "function": {"name": "demo_write", "description": "آزمون", "parameters": {"type": "object", "properties": {}}}}

        async def run(spoken: str, args: dict):
            return f"انجام شد: {args.get('x')}", {}

        router_tools.register(Tool(name="demo_write", schema=schema, level="write", rank=0, run=run, summary=lambda args, spoken: "این کار انجام شود؟"))
        self.addCleanup(router_tools._REGISTRY.pop, "demo_write", None)
        self.assertEqual(router_service._summary_for("demo_write", {"x": 1}, spoken="بکن"), "این کار انجام شود؟")
        reply, _extra = asyncio.run(router_service._run_tool("demo_write", {"x": 1}, source_text="بکن"))
        self.assertEqual(reply, "انجام شد: 1")

    def test_groups_are_off_until_turned_on(self) -> None:
        names = lambda subset: [item["function"]["name"] for item in subset]  # noqa: E731
        with patch.object(settings, "decider_tool_groups", False):
            self.assertEqual(names(router_loop._subset_for("edit_shop")), ["edit_shop"])
        with patch.object(settings, "decider_tool_groups", True):
            self.assertEqual(sorted(names(router_loop._subset_for("edit_shop"))), ["edit_shop", "status"])
        self.assertEqual(router_loop._subset_for("ask_user"), [])


if __name__ == "__main__":
    unittest.main()
