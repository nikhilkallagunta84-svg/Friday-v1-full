from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from friday.ollama_engine import OllamaResponse, OllamaUnavailable
from friday.phone.call_planner import CallPlanner


def _json_response(payload: dict) -> OllamaResponse:
    return OllamaResponse(text=json.dumps(payload), model="qwen3:1.7b", prompt_type="json")


class CallPlannerTests(unittest.TestCase):
    def test_parses_clean_ollama_brief(self) -> None:
        ollama = MagicMock()
        ollama.generate_json.return_value = _json_response(
            {
                "recipient_name": "United Airlines",
                "recipient_number": "+18008648331",
                "objective": "ask about my refund for booking ABC123",
                "talking_points": ["booking ABC123", "be polite"],
                "success_criteria": ["got refund or callback"],
                "max_minutes": 10,
                "persona": "respectful",
            }
        )
        planner = CallPlanner(ollama)

        brief, confidence = planner.plan("call United about my refund for booking ABC123")

        self.assertEqual(brief.recipient_name, "United Airlines")
        self.assertEqual(brief.recipient_number, "+18008648331")
        self.assertIn("refund", brief.objective)
        self.assertEqual(brief.talking_points, ["booking ABC123", "be polite"])
        self.assertEqual(brief.max_minutes, 10)
        self.assertGreaterEqual(confidence, 0.9)

    def test_falls_back_to_keyword_extraction_when_ollama_unavailable(self) -> None:
        ollama = MagicMock()
        ollama.generate_json.side_effect = OllamaUnavailable("ollama down")
        planner = CallPlanner(ollama)

        brief, confidence = planner.plan(
            "call my dentist at 555-867-5309 to reschedule my appointment"
        )

        self.assertIn("dentist", brief.recipient_name.lower())
        self.assertIn("555", brief.recipient_number)
        # 0.4 for the number + 0.1 for a real (non-generic) recipient name; no Ollama bonus.
        self.assertAlmostEqual(confidence, 0.5, places=2)

    def test_invalid_json_response_falls_back(self) -> None:
        ollama = MagicMock()
        ollama.generate_json.return_value = OllamaResponse(
            text="not actually json", model="qwen3:1.7b", prompt_type="json"
        )
        planner = CallPlanner(ollama)

        brief, confidence = planner.plan("call my mom and ask about dinner")

        # Fallback path: recipient guessed from request, no number, low confidence.
        self.assertIn("mom", brief.recipient_name.lower())
        self.assertEqual(brief.recipient_number, "")
        self.assertLess(confidence, 0.5)

    def test_rejects_invented_phone_number_field_with_too_few_digits(self) -> None:
        ollama = MagicMock()
        ollama.generate_json.return_value = _json_response(
            {
                "recipient_name": "United",
                "recipient_number": "555",  # too short, should be discarded
                "objective": "refund",
            }
        )
        planner = CallPlanner(ollama)

        brief, _ = planner.plan("call United about my refund")

        self.assertEqual(brief.recipient_number, "")

    def test_clamps_max_minutes_to_safe_range(self) -> None:
        ollama = MagicMock()
        ollama.generate_json.return_value = _json_response(
            {
                "recipient_name": "United",
                "recipient_number": "+15551234567",
                "objective": "refund",
                "max_minutes": 999,
            }
        )
        planner = CallPlanner(ollama)

        brief, _ = planner.plan("call United about my refund")

        self.assertLessEqual(brief.max_minutes, 30)
        self.assertGreaterEqual(brief.max_minutes, 1)

    def test_empty_request_raises(self) -> None:
        ollama = MagicMock()
        planner = CallPlanner(ollama)

        with self.assertRaises(ValueError):
            planner.plan("")

    def test_uses_model_manager_to_select_simple_model(self) -> None:
        ollama = MagicMock()
        ollama.generate_json.return_value = _json_response(
            {"recipient_name": "X", "recipient_number": "+15551234567", "objective": "test"}
        )
        model_manager = MagicMock()
        model_manager.select_model_for_task.return_value = "qwen3:1.7b"
        planner = CallPlanner(ollama, model_manager=model_manager)

        planner.plan("call X about Y")

        model_manager.select_model_for_task.assert_called_with("simple")
        # The selected model should be threaded into generate_json
        self.assertEqual(ollama.generate_json.call_args.kwargs.get("model"), "qwen3:1.7b")


if __name__ == "__main__":
    unittest.main()
