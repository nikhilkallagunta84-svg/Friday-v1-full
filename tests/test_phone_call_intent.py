from __future__ import annotations

import unittest

from friday.local_intents import LocalIntentResolver


class PhoneCallIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = LocalIntentResolver()

    def _resolve(self, text: str):
        return self.resolver.resolve(text)

    # ---- positive matches ------------------------------------------------

    def test_call_with_objective_routes_to_place_call(self) -> None:
        intent = self._resolve("call united and ask about my refund for booking ABC123")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "place_call")
        self.assertIn("united", intent.intent["parameters"]["request"].lower())

    def test_phone_recipient_with_number(self) -> None:
        intent = self._resolve("phone my dentist at 555-867-5309 to reschedule my appointment")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "place_call")

    def test_ring_up_business(self) -> None:
        intent = self._resolve("ring up the pizza place and order a large pepperoni")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "place_call")

    def test_dial_with_confirmation_keyword(self) -> None:
        intent = self._resolve("dial my mom and confirm we're still on for dinner, go ahead and do it")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "place_call")
        self.assertTrue(intent.intent["parameters"].get("confirmed"))

    def test_cancel_call(self) -> None:
        intent = self._resolve("cancel the call to united")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "cancel_call")
        self.assertEqual(intent.intent["parameters"].get("recipient"), "united")

    def test_cancel_call_no_target(self) -> None:
        intent = self._resolve("cancel the call")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "cancel_call")
        self.assertEqual(intent.intent["parameters"], {})

    def test_status_query(self) -> None:
        intent = self._resolve("what's happening with my call")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "list_calls")

    def test_summarize_last_call(self) -> None:
        intent = self._resolve("summarize the last call")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "summarize_last_call")

    # ---- guards (false-positive protection) ------------------------------

    def test_call_function_is_not_phone_call(self) -> None:
        intent = self._resolve("call this function foo to handle the event")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "place_call")

    def test_call_api_endpoint_is_not_phone_call(self) -> None:
        intent = self._resolve("call the api endpoint and parse the response")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "place_call")

    def test_call_me_later_is_not_phone_call(self) -> None:
        intent = self._resolve("call me later")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "place_call")

    def test_call_me_back_is_not_phone_call(self) -> None:
        intent = self._resolve("call me back tomorrow")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "place_call")

    def test_call_it_foo_is_not_phone_call(self) -> None:
        intent = self._resolve("call it foo and move on")
        if intent is not None:
            self.assertNotEqual(intent.intent["command"], "place_call")


if __name__ == "__main__":
    unittest.main()
