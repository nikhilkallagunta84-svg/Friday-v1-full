from __future__ import annotations

import unittest
from unittest.mock import patch

from friday.assistant import FridayAssistant
from friday.config import FridayConfig
from friday.events import EventBus
from friday.ollama_engine import OllamaClient
from friday.state import StateManager
from friday.tools import ToolRouter
from friday.transcript import TranscriptLogger
from friday.tts import MacOSTTS


class PersonalityResponseTests(unittest.TestCase):
    def _assistant(self) -> FridayAssistant:
        config = FridayConfig.load(silent_tts=True)
        return FridayAssistant(
            StateManager(),
            MacOSTTS(silent=True),
            TranscriptLogger(config.transcript_dir),
            EventBus(),
            OllamaClient(config.ollama_host, config.ollama_model, config.personality.assistant_name, config.personality.acronym),
            ToolRouter(config.root_dir, config.resend_api_key),
            assistant_name=config.personality.assistant_name,
            assistant_acronym=config.personality.acronym,
            personality=config.personality,
            publish_ready=False,
        )

    def test_default_response_is_polite(self) -> None:
        assistant = self._assistant()

        self.assertEqual(assistant._ensure_named_response("Handled."), "Handled, boss.")

    def test_task_complete_response_has_boss_language(self) -> None:
        assistant = self._assistant()

        self.assertEqual(assistant._ensure_named_response("Opened Spotify.", context="task_complete"), "Done, boss. Opened Spotify.")

    def test_confirmation_is_respectful(self) -> None:
        assistant = self._assistant()

        response = assistant._ensure_named_response("This may send an email. Say confirm to proceed.")
        self.assertTrue(response.startswith("Just to confirm, sir - "))

    def test_plain_question_can_skip_intent_pass(self) -> None:
        assistant = self._assistant()

        self.assertTrue(assistant._can_answer_without_intent_pass("what is recursion"))
        self.assertTrue(assistant._can_answer_without_intent_pass("what is binary search"))
        self.assertTrue(assistant._can_answer_without_intent_pass("can you explain how browser tabs work"))
        self.assertFalse(assistant._can_answer_without_intent_pass("open spotify"))
        self.assertFalse(assistant._can_answer_without_intent_pass("what is the weather today"))

    def test_search_keyword_only_routes_when_it_is_a_command(self) -> None:
        assistant = self._assistant()

        self.assertFalse(assistant._explicit_web_search_requested("what is binary search"))
        self.assertFalse(assistant._explicit_web_search_requested("explain search algorithms"))
        self.assertTrue(assistant._explicit_web_search_requested("search the web for qwen models"))
        self.assertTrue(assistant._explicit_web_search_requested("google qwen models"))

    def test_specialist_agents_can_use_direct_reasoning_when_safe(self) -> None:
        assistant = self._assistant()

        math_agent = assistant.agents.select("solve 2x + 4 = 10")
        automation_agent = assistant.agents.select("open Spotify")
        coding_agent = assistant.agents.select("write a Python function to parse dates")

        self.assertTrue(assistant._can_agent_answer_directly("solve 2x + 4 = 10", math_agent))
        self.assertFalse(assistant._can_agent_answer_directly("open Spotify", automation_agent))
        self.assertTrue(assistant._can_agent_answer_directly("write a Python function to parse dates", coding_agent))

    def test_agent_context_is_logged_on_intents(self) -> None:
        assistant = self._assistant()
        agent = assistant.agents.select("solve 2 + 2")
        intent = {"intent": "conversation", "command": "none", "parameters": {}}

        assistant._attach_agent_context(intent, agent)

        self.assertEqual(intent["parameters"]["agent"]["id"], "math")
        self.assertEqual(intent["parameters"]["agent"]["name"], "Math Agent")

    def test_current_question_uses_freshness_search(self) -> None:
        assistant = self._assistant()

        self.assertTrue(assistant._should_use_freshness_search("who is the president today"))
        self.assertFalse(assistant._should_use_freshness_search("search the web for ai news"))
        self.assertFalse(assistant._should_use_freshness_search("open weather"))

    def test_knowledge_cutoff_is_intercepted_locally(self) -> None:
        assistant = self._assistant()

        self.assertTrue(assistant._is_operational_freshness_request("what is your knowledge cutoff"))
        self.assertTrue(assistant._is_operational_freshness_request("are you up to date"))
        response = assistant._freshness_status_response().lower()
        self.assertIn("operationally", response)
        self.assertIn("current", response)
        self.assertIn("web", response)
        self.assertNotIn("december 2023", response)

    def test_balanced_qwen_is_default_reasoning_model(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config = FridayConfig.load(silent_tts=True)

        self.assertEqual(config.ollama_model, "qwen3:4b")

    def test_thinking_trace_is_not_user_facing(self) -> None:
        client = OllamaClient("http://127.0.0.1:11434", "qwen3:4b")

        self.assertTrue(client._supports_thinking("qwen3:4b"))
        self.assertEqual(client._clean_response("<think>private chain</think>Handled, boss."), "Handled, boss.")


if __name__ == "__main__":
    unittest.main()
