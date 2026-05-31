from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from friday.local_intents import LocalIntentResolver
from friday.tools.router import ToolRouter
from friday.tools.todo import TodoListTool


def fixed_now() -> datetime:
    return datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)


class TodoListTests(unittest.TestCase):
    def test_add_todo_intent_routes_locally(self) -> None:
        intent = LocalIntentResolver().resolve("add finish math homework to the to do list by 5 pm")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "todo_add")
        self.assertEqual(intent.intent["parameters"]["task"], "finish math homework by 5 pm")

    def test_complete_todo_intent_routes_locally(self) -> None:
        intent = LocalIntentResolver().resolve("im done with math homework task")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "todo_complete")
        self.assertEqual(intent.intent["parameters"]["task"], "math homework")

    def test_list_todo_intent_routes_locally(self) -> None:
        intent = LocalIntentResolver().resolve("show my todo list")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "todo_list")

    def test_clear_todo_intent_routes_locally(self) -> None:
        intent = LocalIntentResolver().resolve("clear my todo list")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "todo_clear")
        self.assertEqual(intent.intent["parameters"], {"mode": "active"})

    def test_plain_complete_form_is_not_todo(self) -> None:
        intent = LocalIntentResolver().resolve("complete the form")

        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "todo_complete")

    def test_add_task_persists_due_time_and_time_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = TodoListTool(Path(tmp), clock=fixed_now)

            result = tool.add_task({"task": "finish math homework by 5 pm with a time limit of 30 minutes"})
            snapshot = tool.snapshot()

        self.assertTrue(result["success"])
        task = result["data"]["task"]
        self.assertEqual(task["title"], "finish math homework")
        self.assertTrue(task["due_at"].endswith("17:00:00+00:00"))
        self.assertEqual(task["time_limit_minutes"], 30)
        self.assertEqual(snapshot["count"], 1)

    def test_in_duration_becomes_due_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = TodoListTool(Path(tmp), clock=fixed_now)

            result = tool.add_task({"task": "review notes in 45 minutes"})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["task"]["title"], "review notes")
        self.assertTrue(result["data"]["task"]["due_at"].endswith("12:45:00+00:00"))

    def test_time_limit_does_not_route_to_get_time(self) -> None:
        intent = LocalIntentResolver().resolve("add temporary codex verification to the todo list by 6 pm with a time limit of 15 minutes")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "todo_add")

    def test_complete_removes_active_task_by_fuzzy_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = TodoListTool(Path(tmp), clock=fixed_now)
            tool.add_task({"task": "finish APUSH essay tomorrow"})

            result = tool.complete_task({"task": "apush essay"})
            snapshot = tool.snapshot()

        self.assertTrue(result["success"])
        self.assertEqual(snapshot["count"], 0)
        self.assertEqual(snapshot["completed_count"], 1)

    def test_clear_active_tasks_marks_them_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = TodoListTool(Path(tmp), clock=fixed_now)
            tool.add_task({"task": "finish math"})
            tool.add_task({"task": "read chapter"})

            result = tool.clear_tasks()
            snapshot = tool.snapshot()

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["cleared_count"], 2)
        self.assertEqual(snapshot["count"], 0)
        self.assertEqual(snapshot["completed_count"], 2)

    def test_tool_router_dispatches_todos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            add = router._execute_one("todo_add", {"task": "finish science project by 8 pm"})
            listed = router._execute_one("todo_list", {})
            complete = router._execute_one("todo_complete", {"task": "science project"})

        self.assertTrue(add["success"])
        self.assertTrue(listed["success"])
        self.assertIn("science project", listed["message"])
        self.assertTrue(complete["success"])

    def test_tool_router_dispatches_todo_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            router._execute_one("todo_add", {"task": "one"})
            result = router._execute_one("todo_clear", {})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["cleared_count"], 1)


if __name__ == "__main__":
    unittest.main()
