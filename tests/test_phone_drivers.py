from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from friday.ollama_engine import OllamaResponse, OllamaUnavailable
from friday.phone.drivers import (
    SimulatedPhoneDriver,
    TwilioNotConfiguredError,
    TwilioPhoneDriver,
)
from friday.schemas.phone_call import CallBrief, CallStatus


def _brief() -> CallBrief:
    return CallBrief(
        call_id="call-abc",
        recipient_name="United Airlines",
        recipient_number="+18008648331",
        objective="ask about my refund for booking ABC123",
        talking_points=["booking ABC123"],
        success_criteria=["got refund or callback"],
        max_minutes=5,
        persona="respectful",
        source_command="call united about my refund",
    )


def _text_response(text: str) -> OllamaResponse:
    return OllamaResponse(text=text, model="qwen3:4b", prompt_type="text")


def _json_response(payload: dict) -> OllamaResponse:
    return OllamaResponse(text=json.dumps(payload), model="qwen3:4b", prompt_type="json")


class _ScriptedOllama:
    """An OllamaClient stand-in that returns canned responses in order."""

    def __init__(self, text_responses, summary_payload):
        self._text_responses = list(text_responses)
        self._summary_payload = summary_payload

    def generate_text(self, prompt, model=None):  # noqa: D401 - mirror real signature
        if not self._text_responses:
            return _text_response("<END>")
        return self._text_responses.pop(0)

    def generate_json(self, prompt, model=None):
        return _json_response(self._summary_payload)


class SimulatedPhoneDriverTests(unittest.TestCase):
    def test_runs_full_call_and_returns_completed_result(self) -> None:
        ollama = _ScriptedOllama(
            text_responses=[
                _text_response("Hi, this is FRIDAY calling on behalf of my user about a refund."),
                _text_response("Hello, this is Carla with United. How can I help?"),
                _text_response("We are calling about booking ABC123 — could you process a refund?"),
                _text_response("I can see that booking. The refund has been approved. Goodbye."),
            ],
            summary_payload={
                "summary": "Refund approved on first contact.",
                "outcome": "success",
                "follow_ups": ["Watch for refund email"],
            },
        )
        driver = SimulatedPhoneDriver(ollama, turn_delay=0.0, sleeper=lambda _s: None)
        events: list[tuple[str, dict]] = []

        result = driver.place_call(_brief(), on_event=lambda kind, payload: events.append((kind, payload)))

        self.assertEqual(result.status, CallStatus.COMPLETED)
        self.assertGreaterEqual(len(result.transcript), 2)
        self.assertEqual(result.outcome, "success")
        self.assertIn("Refund", result.summary)
        kinds = [kind for kind, _ in events]
        self.assertEqual(
            kinds[:4],
            [
                "phone_call_status",
                "phone_call_status",
                "phone_call_status",
                "phone_call_status",
            ],
        )
        # At least one turn must have been emitted
        self.assertIn("phone_call_turn", kinds)

    def test_caps_at_max_turns_when_no_natural_end(self) -> None:
        # Every text reply is non-ending; should hit max_turns boundary.
        responses = [_text_response(f"Line number {i}") for i in range(20)]
        ollama = _ScriptedOllama(responses, summary_payload={"summary": "wrap", "outcome": "partial", "follow_ups": []})
        driver = SimulatedPhoneDriver(ollama, max_turns=4, turn_delay=0.0, sleeper=lambda _s: None)

        result = driver.place_call(_brief(), on_event=lambda *_: None)

        # max_turns=4 + an opening; cap is inclusive of opening line.
        self.assertLessEqual(len(result.transcript), 4)
        self.assertEqual(result.status, CallStatus.COMPLETED)

    def test_returns_failed_when_ollama_breaks_mid_call(self) -> None:
        ollama = MagicMock()
        # Opening succeeds; next_line call fails.
        ollama.generate_text.side_effect = [
            _text_response("Hi, calling about a refund."),
            OllamaUnavailable("ollama crashed"),
        ]
        ollama.generate_json.return_value = _json_response({"summary": "x", "outcome": "y", "follow_ups": []})
        driver = SimulatedPhoneDriver(ollama, turn_delay=0.0, sleeper=lambda _s: None)

        result = driver.place_call(_brief(), on_event=lambda *_: None)

        self.assertEqual(result.status, CallStatus.FAILED)
        self.assertIn("ollama", result.error.lower())

    def test_cancel_short_circuits_call(self) -> None:
        ollama = _ScriptedOllama([_text_response("nope")] * 5, summary_payload={})
        driver = SimulatedPhoneDriver(ollama, turn_delay=0.0, sleeper=lambda _s: None)
        brief = _brief()
        driver.cancel(brief.call_id)

        result = driver.place_call(brief, on_event=lambda *_: None)

        self.assertEqual(result.status, CallStatus.CANCELLED)


class TwilioPhoneDriverTests(unittest.TestCase):
    def test_raises_when_creds_missing(self) -> None:
        driver = TwilioPhoneDriver()
        self.assertFalse(driver.configured)
        with self.assertRaises(TwilioNotConfiguredError):
            driver.place_call(_brief(), on_event=lambda *_: None)

    def test_configured_returns_failed_with_not_implemented_message(self) -> None:
        driver = TwilioPhoneDriver(
            account_sid="AC_test",
            auth_token="auth_test",
            from_number="+15550000000",
        )
        self.assertTrue(driver.configured)

        result = driver.place_call(_brief(), on_event=lambda *_: None)

        self.assertEqual(result.status, CallStatus.FAILED)
        self.assertEqual(result.outcome, "not_implemented")
        self.assertIn("simulator", result.summary.lower())

    def test_configured_but_missing_number_fails_cleanly(self) -> None:
        driver = TwilioPhoneDriver(
            account_sid="AC_test",
            auth_token="auth_test",
            from_number="+15550000000",
        )
        brief = CallBrief(
            call_id="call-x",
            recipient_name="Someone",
            recipient_number="",
            objective="ask a question",
        )

        result = driver.place_call(brief, on_event=lambda *_: None)

        self.assertEqual(result.status, CallStatus.FAILED)
        self.assertEqual(result.outcome, "missing_number")


if __name__ == "__main__":
    unittest.main()
