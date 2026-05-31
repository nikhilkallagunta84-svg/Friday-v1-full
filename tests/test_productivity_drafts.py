from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from friday.local_intents import LocalIntentResolver
from friday.tools.productivity import ProductivityDraftTool
from friday.tools.router import ToolRouter


def _successful_runner(*_: Any, **__: Any) -> Any:
    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    return Completed()


def _noop_opener(*_: Any, **__: Any) -> Any:
    class Process:
        pass

    return Process()


class FakeProductivityTool:
    def __init__(self) -> None:
        self.report_calls: list[dict[str, Any]] = []
        self.slide_calls: list[dict[str, Any]] = []

    def write_report(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.report_calls.append(dict(parameters))
        return {
            "success": True,
            "requires_confirmation": False,
            "message": "I drafted the report, opened Google Docs, and pasted it in, boss.",
            "data": dict(parameters),
        }

    def make_slides(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.slide_calls.append(dict(parameters))
        return {
            "success": True,
            "requires_confirmation": False,
            "message": "I drafted the slide deck, opened Gamma, and pasted the prompt in, boss.",
            "data": dict(parameters),
        }


class ProductivityDraftTests(unittest.TestCase):
    def test_google_docs_report_intent(self) -> None:
        intent = LocalIntentResolver().resolve("open Google Docs and write a report about AI agents")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "draft_document")
        self.assertEqual(intent.intent["parameters"]["target"], "google_docs")
        self.assertEqual(intent.intent["parameters"]["document_type"], "report")
        self.assertEqual(intent.intent["parameters"]["prompt"], "ai agents")

    def test_write_report_in_google_docs_intent(self) -> None:
        intent = LocalIntentResolver().resolve("write an essay about renewable energy in Google Docs")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "draft_document")
        self.assertEqual(intent.intent["parameters"]["document_type"], "essay")
        self.assertEqual(intent.intent["parameters"]["prompt"], "renewable energy")

    def test_google_docs_report_without_topic_asks_follow_up(self) -> None:
        intent = LocalIntentResolver().resolve("open Google Docs and write a report")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "ask_follow_up")
        self.assertIn("What should the report", intent.intent["parameters"]["question"])

    def test_gamma_slides_intent(self) -> None:
        intent = LocalIntentResolver().resolve("open Gamma and make slides about robotics")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "draft_slides")
        self.assertEqual(intent.intent["parameters"], {"target": "gamma", "prompt": "robotics"})

    def test_google_slides_intent(self) -> None:
        intent = LocalIntentResolver().resolve("make a presentation about photosynthesis in Google Slides")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "draft_slides")
        self.assertEqual(intent.intent["parameters"], {"target": "google_slides", "prompt": "photosynthesis"})

    def test_productivity_tool_report_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": "", "FRIDAY_GOOGLE_ACCOUNT": ""}):
            result = ProductivityDraftTool(Path(tmp)).write_report(
                {"target": "google_docs", "document_type": "report", "prompt": "AI agents", "dry_run": True}
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["copied_to_clipboard"])
        self.assertTrue(result["data"]["opened"])
        self.assertTrue(result["data"]["pasted"])
        self.assertEqual(result["data"]["url"], "https://docs.new")

    def test_productivity_tool_slides_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = ProductivityDraftTool(Path(tmp)).make_slides({"target": "gamma", "prompt": "AI agents", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["url"], "https://gamma.app/create/generate")

    def test_productivity_tool_does_not_call_ollama_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = ProductivityDraftTool(Path(tmp), runner=_successful_runner, opener=_noop_opener, sleeper=lambda _: None)
            with patch.object(tool, "_generate_text", side_effect=TimeoutError("timed out")) as generate:
                result = tool.make_slides({"target": "gamma", "prompt": "AI agents"})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["generation_status"], "instant_template")
        generate.assert_not_called()

    def test_productivity_tool_falls_back_when_ollama_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = ProductivityDraftTool(Path(tmp), runner=_successful_runner, opener=_noop_opener, sleeper=lambda _: None)
            with patch.object(tool, "_generate_text", side_effect=RuntimeError("Ollama draft generation timed out or is unavailable")):
                result = tool.make_slides({"target": "gamma", "prompt": "AI agents", "use_ollama_draft": True})

        self.assertTrue(result["success"])
        self.assertIn("fallback", result["data"]["generation_status"])
        self.assertTrue(result["data"]["copied_to_clipboard"])

    def test_productivity_tool_falls_back_when_socket_timeout_bubbles_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = ProductivityDraftTool(Path(tmp), runner=_successful_runner, opener=_noop_opener, sleeper=lambda _: None)
            with patch.object(tool, "_generate_text", side_effect=TimeoutError("timed out")):
                result = tool.make_slides({"target": "gamma", "prompt": "AI agents", "use_ollama_draft": True})

        self.assertTrue(result["success"])
        self.assertIn("fallback", result["data"]["generation_status"])

    def test_router_returns_clean_error_if_productivity_tool_crashes(self) -> None:
        class BrokenProductivityTool:
            def make_slides(self, parameters: dict[str, Any]) -> dict[str, Any]:
                raise TimeoutError("timed out")

            def write_report(self, parameters: dict[str, Any]) -> dict[str, Any]:
                raise TimeoutError("timed out")

        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            router.productivity = BrokenProductivityTool()  # type: ignore[assignment]
            result = router._execute_one("draft_slides", {"target": "gamma", "prompt": "AI agents"})

        self.assertFalse(result["success"])
        self.assertIn("slide draft", result["message"])
        self.assertNotEqual(result["message"], "timed out")

    def test_tool_router_dispatches_productivity_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            fake = FakeProductivityTool()
            router.productivity = fake  # type: ignore[assignment]

            report = router._execute_one("draft_document", {"target": "google_docs", "document_type": "report", "prompt": "AI agents"})
            slides = router._execute_one("draft_slides", {"target": "gamma", "prompt": "AI agents"})

        self.assertTrue(report["success"])
        self.assertTrue(slides["success"])
        self.assertEqual(fake.report_calls, [{"target": "google_docs", "document_type": "report", "prompt": "AI agents"}])
        self.assertEqual(fake.slide_calls, [{"target": "gamma", "prompt": "AI agents"}])


if __name__ == "__main__":
    unittest.main()
