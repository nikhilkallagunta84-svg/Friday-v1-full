from __future__ import annotations

import unittest

from friday.local_intents import LocalIntentResolver


class CodeGenerateIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = LocalIntentResolver()

    def test_write_python_function_routes_to_generate_code(self) -> None:
        intent = self.resolver.resolve("write a python function that adds two numbers")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "generate_code")
        self.assertEqual(intent.intent["parameters"].get("language"), "python")
        self.assertIn("adds two numbers", intent.intent["parameters"]["prompt"])

    def test_generate_javascript_snippet(self) -> None:
        intent = self.resolver.resolve("generate javascript code to fetch users from an api")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "generate_code")
        self.assertEqual(intent.intent["parameters"].get("language"), "javascript")

    def test_write_code_in_rust_phrasing(self) -> None:
        intent = self.resolver.resolve("write a script in rust to parse json")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "generate_code")
        self.assertEqual(intent.intent["parameters"].get("language"), "rust")

    def test_code_keyword_alone(self) -> None:
        intent = self.resolver.resolve("code up a regex that matches email addresses")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "generate_code")

    def test_report_request_does_not_route_to_code(self) -> None:
        # Whatever this resolves to (document drafter, screen control, or None),
        # it must NOT be generate_code.
        intent = self.resolver.resolve("write a report about climate change")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "generate_code")

    def test_slides_request_does_not_route_to_code(self) -> None:
        intent = self.resolver.resolve("make a slide deck about AI")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "generate_code")

    def test_run_a_script_does_not_route_to_code(self) -> None:
        # "run a script" is execution, not generation.
        intent = self.resolver.resolve("run the script")

        # Should not be generate_code; either None or another intent.
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "generate_code")

    def test_bare_question_about_code_does_not_route(self) -> None:
        intent = self.resolver.resolve("what is code")

        # Should fall through to conversational reply (None from local resolver).
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "generate_code")


if __name__ == "__main__":
    unittest.main()
