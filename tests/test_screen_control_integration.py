from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.assistant import FridayAssistant
from friday.control.controller_router import ControllerRouter
from friday.events import EventBus
from friday.local_intents import LocalIntentResolver
from friday.ollama_engine import OllamaClient
from friday.schemas.action_result import ActionResult
from friday.state import StateManager
from friday.tools.router import ToolRouter
from friday.transcript import TranscriptLogger


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def interrupt(self) -> bool:
        return False

    def speak(self, text: str) -> None:
        self.spoken.append(text)


class FakeBrowserController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def open_url(self, url: str) -> ActionResult:
        self.calls.append(("open_url", url, ""))
        return self._result("browser.open_url", "Opened fake URL.")

    def search(self, query: str) -> ActionResult:
        self.calls.append(("search", query, ""))
        return self._result("browser.search", "Searched fake query.")

    def click(self, target: str) -> ActionResult:
        self.calls.append(("click", target, ""))
        return self._result("browser.click", "Clicked fake target.")

    def type_text(self, target: str, text: str) -> ActionResult:
        self.calls.append(("type_text", target, text))
        return self._result("browser.type", "Typed fake text.")

    def go_back(self) -> ActionResult:
        self.calls.append(("go_back", "", ""))
        return self._result("browser.navigate", "Went back.")

    def new_tab(self) -> ActionResult:
        self.calls.append(("new_tab", "", ""))
        return self._result("browser.navigate", "Opened new tab.")

    def close_tab(self) -> ActionResult:
        self.calls.append(("close_tab", "", ""))
        return self._result("browser.navigate", "Closed tab.")

    def get_page_title(self) -> str:
        return "Fake Page"

    def get_current_url(self) -> str:
        return "https://example.com"

    def _result(self, action_id: str, message: str) -> ActionResult:
        now = datetime.now(timezone.utc)
        return ActionResult(
            action_id=action_id,
            success=True,
            message=message,
            error="",
            started_at=now,
            finished_at=now,
            controller_used="fake-browser",
        )


class FakeBrowserTool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def open_page(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("open_page", dict(parameters)))
        return {
            "success": True,
            "requires_confirmation": False,
            "message": "Opened URL in your default browser.",
            "data": dict(parameters),
        }

    def search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("search", dict(parameters)))
        return {
            "success": True,
            "requires_confirmation": False,
            "message": "Opened search results in your default browser.",
            "data": dict(parameters),
        }

    def close_tab(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("close_tab", dict(parameters)))
        return {"success": True, "requires_confirmation": False, "message": "Closed browser tab.", "data": dict(parameters)}

    def switch_tab(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("switch_tab", dict(parameters)))
        return {"success": True, "requires_confirmation": False, "message": "Switched browser tab.", "data": dict(parameters)}


class FakeMusicTool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def play(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(parameters))
        return {"success": True, "requires_confirmation": False, "message": "Playing lil baby on Spotify.", "data": dict(parameters)}


class FakeProductivityTool:
    def __init__(self) -> None:
        self.report_calls: list[dict[str, Any]] = []
        self.slide_calls: list[dict[str, Any]] = []

    def write_report(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.report_calls.append(dict(parameters))
        return {"success": True, "requires_confirmation": False, "message": "I drafted the report, opened Google Docs, and pasted it in, boss.", "data": dict(parameters)}

    def make_slides(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.slide_calls.append(dict(parameters))
        return {"success": True, "requires_confirmation": False, "message": "I drafted the slide deck, opened Gamma, and pasted the prompt in, boss.", "data": dict(parameters)}


class FakeOllama:
    def __init__(self) -> None:
        self.responses: list[tuple[str, str]] = []

    def build_intent(self, cleaned_input: str, *_: Any) -> dict[str, Any]:
        return {"intent": "conversation", "command": "none", "parameters": {"query": cleaned_input}}

    def build_response(self, user_input: str, filtered_input: str, **_: Any) -> str:
        self.responses.append((user_input, filtered_input))
        return "Binary search checks the middle of a sorted list, then halves the search range."


def build_assistant(tmp: str, browser: FakeBrowserController, ollama: Any | None = None) -> FridayAssistant:
    root = Path(tmp)
    tools = ToolRouter(root, "")
    tools.controller_router = ControllerRouter(browser_controller=browser, root_dir=root)
    tools.browser = FakeBrowserTool()  # type: ignore[assignment]
    tools.music = FakeMusicTool()  # type: ignore[assignment]
    tools.productivity = FakeProductivityTool()  # type: ignore[assignment]
    return FridayAssistant(
        StateManager(),
        FakeTTS(),  # type: ignore[arg-type]
        TranscriptLogger(root / "transcripts"),
        EventBus(),
        ollama or OllamaClient("http://127.0.0.1:11434", "qwen3:4b"),
        tools,
        publish_ready=False,
    )


class ScreenControlIntegrationTests(unittest.TestCase):
    def test_existing_app_opening_behavior_is_preserved(self) -> None:
        intent = LocalIntentResolver().resolve("open spotify")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "open_app")

    def test_open_precedence_is_app_then_website_then_google_search(self) -> None:
        resolver = LocalIntentResolver()

        app_intent = resolver.resolve("open spotify")
        website_intent = resolver.resolve("open instagram")
        search_intent = resolver.resolve("open flarble unknown service")

        self.assertIsNotNone(app_intent)
        self.assertIsNotNone(website_intent)
        self.assertIsNotNone(search_intent)
        assert app_intent is not None
        assert website_intent is not None
        assert search_intent is not None
        self.assertEqual(app_intent.intent["command"], "open_app")
        self.assertEqual(website_intent.intent["command"], "browser_open")
        self.assertEqual(website_intent.intent["parameters"]["url"], "https://www.instagram.com/")
        self.assertEqual(search_intent.intent["command"], "browser_search")
        self.assertIn("official website", search_intent.intent["parameters"]["query"])

    def test_open_spotify_and_play_routes_to_music_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("open Spotify and play Lil Baby", "text")

        self.assertEqual(result.intent["command"], "music_play")
        self.assertEqual(result.intent["parameters"]["service"], "spotify")
        self.assertEqual(result.intent["parameters"]["query"], "lil baby")
        self.assertEqual(assistant.tools.music.calls, [{"service": "spotify", "query": "lil baby"}])  # type: ignore[attr-defined]
        self.assertIn("Spotify", result.final_output)

    def test_google_docs_report_routes_to_productivity_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("open Google Docs and write a report about AI agents", "text")

        self.assertEqual(result.intent["command"], "draft_document")
        self.assertEqual(result.intent["parameters"]["target"], "google_docs")
        self.assertEqual(result.intent["parameters"]["prompt"], "ai agents")
        self.assertEqual(
            assistant.tools.productivity.report_calls,  # type: ignore[attr-defined]
            [{"target": "google_docs", "document_type": "report", "prompt": "ai agents"}],
        )
        self.assertIn("Google Docs", result.final_output)

    def test_gamma_slides_routes_to_productivity_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("open Gamma and make slides about robotics", "text")

        self.assertEqual(result.intent["command"], "draft_slides")
        self.assertEqual(result.intent["parameters"]["target"], "gamma")
        self.assertEqual(result.intent["parameters"]["prompt"], "robotics")
        self.assertEqual(assistant.tools.productivity.slide_calls, [{"target": "gamma", "prompt": "robotics"}])  # type: ignore[attr-defined]
        self.assertIn("Gamma", result.final_output)

    def test_open_youtube_routes_through_browser_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("open YouTube", "text")

        self.assertEqual(result.intent["command"], "browser_open")
        self.assertEqual(browser.calls, [])
        self.assertEqual(assistant.tools.browser.calls, [("open_page", {"url": "https://www.youtube.com/", "visible": True})])  # type: ignore[attr-defined]
        self.assertIn("default browser", result.final_output)
        self.assertNotIn("{", result.final_output)

    def test_text_and_voice_route_to_same_screen_control_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            text_result = assistant._process_text("open ChatGPT", "text")
            voice_result = assistant._process_text("open ChatGPT", "voice")

        self.assertEqual(text_result.intent["command"], "browser_open")
        self.assertEqual(voice_result.intent["command"], "browser_open")
        self.assertEqual(browser.calls, [])
        self.assertEqual(
            assistant.tools.browser.calls,  # type: ignore[attr-defined]
            [
                ("open_page", {"url": "https://chatgpt.com/", "visible": True}),
                ("open_page", {"url": "https://chatgpt.com/", "visible": True}),
            ],
        )

    def test_search_youtube_routes_to_real_browser_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("search YouTube for calculus chain rule", "text")

        self.assertEqual(result.intent["command"], "browser_search")
        self.assertEqual(browser.calls, [])
        self.assertEqual(assistant.tools.browser.calls, [("search", {"engine": "youtube", "query": "calculus chain rule"})])  # type: ignore[attr-defined]
        self.assertIn("search results", result.final_output)

    def test_search_major_website_routes_to_real_browser_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("search Instagram for AI engineering", "text")

        self.assertEqual(result.intent["command"], "browser_search")
        self.assertEqual(browser.calls, [])
        self.assertEqual(assistant.tools.browser.calls, [("search", {"engine": "instagram", "query": "ai engineering"})])  # type: ignore[attr-defined]
        self.assertIn("search results", result.final_output)

    def test_plain_google_search_uses_same_browser_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("search for AI engineering", "text")

        self.assertEqual(result.intent["command"], "browser_search")
        self.assertEqual(browser.calls, [])
        self.assertEqual(assistant.tools.browser.calls, [("search", {"engine": "google", "query": "ai engineering"})])  # type: ignore[attr-defined]
        self.assertIn("search results", result.final_output)

    def test_search_then_ordinal_click_share_browser_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            search_result = assistant._process_text("search for AI engineering", "text")
            click_result = assistant._process_text("click first link on AI engineering tab", "text")

        self.assertEqual(search_result.intent["command"], "browser_search")
        self.assertEqual(click_result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [("click", "first link on ai engineering tab", "")])
        self.assertEqual(assistant.tools.browser.calls, [("search", {"engine": "google", "query": "ai engineering"})])  # type: ignore[attr-defined]

    def test_click_search_bar_and_type_routes_two_browser_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("click the search bar and type Lil Baby", "text")

        self.assertEqual(result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [("click", "search bar", ""), ("type_text", "current field", "lil baby")])
        self.assertIn("Clicking search bar", result.final_output)

    def test_click_button_on_specific_website_routes_open_then_semantic_click(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("click the sign in button on YouTube", "text")

        self.assertEqual(result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [("open_url", "https://www.youtube.com", ""), ("click", "sign in", "")])
        self.assertIn("Clicking sign in on YouTube", result.final_output)

    def test_open_website_and_click_button_routes_open_then_semantic_click(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("open Canva and click templates", "text")

        self.assertEqual(result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [("open_url", "https://www.canva.com", ""), ("click", "templates", "")])
        self.assertIn("Clicking templates on Canva", result.final_output)

    def test_find_element_on_website_and_click_routes_before_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("find templates on Canva and click it", "text")

        self.assertEqual(result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [("open_url", "https://www.canva.com", ""), ("click", "templates", "")])
        self.assertEqual(assistant.tools.browser.calls, [])  # type: ignore[attr-defined]

    def test_blocked_command_produces_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("type my password", "text")

        self.assertEqual(result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [])
        self.assertIn("blocked action", result.final_output)

    def test_high_risk_command_produces_confirmation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            assistant = build_assistant(tmp, browser)

            result = assistant._process_text("send this email", "text")

        self.assertEqual(result.intent["command"], "screen_control_plan")
        self.assertEqual(browser.calls, [])
        self.assertIn("confirmation before sending", result.final_output)

    def test_binary_search_question_stays_conversational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            ollama = FakeOllama()
            assistant = build_assistant(tmp, browser, ollama)

            result = assistant._process_text("what is binary search", "text")

        self.assertEqual(result.intent["command"], "none")
        self.assertEqual(browser.calls, [])
        self.assertEqual(ollama.responses, [("what is binary search", "what is binary search")])
        self.assertIn("Binary search checks", result.final_output)

    def test_browser_tab_explanation_stays_conversational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser = FakeBrowserController()
            ollama = FakeOllama()
            assistant = build_assistant(tmp, browser, ollama)

            result = assistant._process_text("can you explain how browser tabs work", "text")

        self.assertEqual(result.intent["command"], "none")
        self.assertEqual(browser.calls, [])
        self.assertTrue(ollama.responses)


if __name__ == "__main__":
    unittest.main()
