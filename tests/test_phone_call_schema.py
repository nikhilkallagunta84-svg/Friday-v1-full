from __future__ import annotations

import unittest
from datetime import datetime, timezone

from friday.schemas.phone_call import (
    CallBrief,
    CallResult,
    CallStatus,
    CallTurn,
    coerce_call_status,
)


class CoerceCallStatusTests(unittest.TestCase):
    def test_accepts_enum(self) -> None:
        self.assertEqual(coerce_call_status(CallStatus.RINGING), CallStatus.RINGING)

    def test_accepts_string(self) -> None:
        self.assertEqual(coerce_call_status("completed"), CallStatus.COMPLETED)
        self.assertEqual(coerce_call_status("  DIALING  "), CallStatus.DIALING)

    def test_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            coerce_call_status("unknown")


class CallBriefTests(unittest.TestCase):
    def test_requires_recipient_name(self) -> None:
        with self.assertRaises(ValueError):
            CallBrief(
                call_id="call-1",
                recipient_name="",
                recipient_number="+15551234567",
                objective="ask about refund",
            )

    def test_recipient_number_can_be_empty(self) -> None:
        # Empty number is allowed so the planner can return a brief asking the user for one.
        brief = CallBrief(
            call_id="call-1",
            recipient_name="United",
            recipient_number="",
            objective="ask about refund",
        )
        self.assertEqual(brief.recipient_number, "")

    def test_rejects_invalid_max_minutes(self) -> None:
        for bad_value in (0, -1, 61, 1000):
            with self.assertRaises(ValueError):
                CallBrief(
                    call_id="call-1",
                    recipient_name="United",
                    recipient_number="+15551234567",
                    objective="ask about refund",
                    max_minutes=bad_value,
                )

    def test_filters_empty_talking_points(self) -> None:
        brief = CallBrief(
            call_id="call-1",
            recipient_name="United",
            recipient_number="+15551234567",
            objective="refund",
            talking_points=["booking ABC123", "", "  ", "be polite"],
        )
        self.assertEqual(brief.talking_points, ["booking ABC123", "be polite"])

    def test_round_trip_to_and_from_dict(self) -> None:
        original = CallBrief(
            call_id="call-1",
            recipient_name="United",
            recipient_number="+15551234567",
            objective="ask about refund",
            talking_points=["booking ABC123"],
            success_criteria=["got refund or callback"],
            max_minutes=10,
            persona="formal",
            source_command="call united about my refund",
        )
        restored = CallBrief.from_dict(original.to_dict())
        self.assertEqual(restored.to_dict(), original.to_dict())

    def test_created_at_coerces_iso_string(self) -> None:
        brief = CallBrief(
            call_id="call-1",
            recipient_name="United",
            recipient_number="+15551234567",
            objective="refund",
            created_at="2026-05-30T12:00:00+00:00",
        )
        self.assertIsInstance(brief.created_at, datetime)
        self.assertEqual(brief.created_at.tzinfo, timezone.utc)


class CallTurnTests(unittest.TestCase):
    def test_rejects_unknown_speaker(self) -> None:
        with self.assertRaises(ValueError):
            CallTurn(speaker="random", text="hello")

    def test_round_trip(self) -> None:
        turn = CallTurn(speaker="friday", text="Hi, I'm calling on behalf of the user.")
        restored = CallTurn.from_dict(turn.to_dict())
        self.assertEqual(restored.speaker, turn.speaker)
        self.assertEqual(restored.text, turn.text)


class CallResultTests(unittest.TestCase):
    def test_requires_call_id(self) -> None:
        with self.assertRaises(ValueError):
            CallResult(call_id="", status=CallStatus.COMPLETED)

    def test_coerces_dict_transcript_entries(self) -> None:
        result = CallResult(
            call_id="call-1",
            status="completed",
            transcript=[
                {"speaker": "friday", "text": "Hello"},
                {"speaker": "recipient", "text": "Hi there"},
            ],
        )
        self.assertEqual(len(result.transcript), 2)
        self.assertIsInstance(result.transcript[0], CallTurn)
        self.assertEqual(result.transcript[0].text, "Hello")

    def test_round_trip(self) -> None:
        original = CallResult(
            call_id="call-1",
            status=CallStatus.COMPLETED,
            transcript=[CallTurn(speaker="friday", text="Hi")],
            summary="Brief discussion about refund",
            outcome="callback_scheduled",
            follow_ups=["call back at 3pm"],
            error="",
        )
        restored = CallResult.from_dict(original.to_dict())
        self.assertEqual(restored.call_id, original.call_id)
        self.assertEqual(restored.status, original.status)
        self.assertEqual(len(restored.transcript), 1)
        self.assertEqual(restored.summary, original.summary)


if __name__ == "__main__":
    unittest.main()
