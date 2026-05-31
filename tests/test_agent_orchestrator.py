from __future__ import annotations

import unittest

from friday.agents import MultiAgentOrchestrator


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = MultiAgentOrchestrator()

    def test_routes_coding_prompts_to_coding_agent(self) -> None:
        selection = self.orchestrator.select("write a Python function to parse JSON safely")

        self.assertEqual(selection.agent_id, "coding")
        self.assertIn("20 years", selection.prompt_context)

    def test_routes_math_prompts_to_math_agent(self) -> None:
        selection = self.orchestrator.select("solve 2x + 4 = 10")

        self.assertEqual(selection.agent_id, "math")

    def test_routes_current_questions_to_information_agent(self) -> None:
        selection = self.orchestrator.select("who is the president today")

        self.assertEqual(selection.agent_id, "information")

    def test_routes_open_commands_to_automation_agent(self) -> None:
        selection = self.orchestrator.select("open YouTube")

        self.assertEqual(selection.agent_id, "automation")

    def test_routes_school_prompts_to_study_agent(self) -> None:
        selection = self.orchestrator.select("make flashcards for my biology quiz")

        self.assertEqual(selection.agent_id, "study")

    def test_routes_chat_prompts_to_conversational_agent(self) -> None:
        selection = self.orchestrator.select("how are you doing today")

        self.assertEqual(selection.agent_id, "conversational")


if __name__ == "__main__":
    unittest.main()
