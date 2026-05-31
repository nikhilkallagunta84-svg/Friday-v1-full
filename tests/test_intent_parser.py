from __future__ import annotations

import unittest

from friday.brain.intent_parser import IntentParser


class IntentParserTests(unittest.TestCase):
    def test_validated_schema_is_attached_before_execution(self) -> None:
        parser = IntentParser()
        intent = {"intent": "open_app", "command": "open_app", "parameters": {"app_name": "Spotify"}}

        validated = parser.validate_legacy_intent("Friday open Spotify", "open spotify", intent)

        schema = validated["voice_intent"]
        self.assertEqual(schema["raw_transcript"], "Friday open Spotify")
        self.assertEqual(schema["cleaned_transcript"], "open spotify")
        self.assertEqual(schema["tool"], "open_app")
        self.assertEqual(schema["target"], "Spotify")
        self.assertGreater(schema["confidence"], 0.9)

    def test_risky_intent_marks_confirmation_requirement(self) -> None:
        parser = IntentParser()
        intent = {"intent": "send_email", "command": "send_email", "parameters": {"to": "test@example.com"}}

        validated = parser.validate_legacy_intent("Friday send that email", "send that email", intent)

        self.assertTrue(validated["voice_intent"]["requires_confirmation"])
        self.assertIn("sending", validated["voice_intent"]["confirmation_reason"])


if __name__ == "__main__":
    unittest.main()
