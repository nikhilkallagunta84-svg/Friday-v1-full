from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from friday.tools.phone import PhoneTool


class PhoneToolTests(unittest.TestCase):
    def test_returns_unavailable_when_manager_is_none(self) -> None:
        tool = PhoneTool(manager=None)

        result = tool.place_call({"request": "call mom"})

        self.assertFalse(result["success"])
        self.assertIn("not wired", result["message"])

    def test_empty_request_returns_friendly_failure(self) -> None:
        manager = MagicMock()
        tool = PhoneTool(manager=manager)

        result = tool.place_call({})

        self.assertFalse(result["success"])
        manager.place_call.assert_not_called()

    def test_place_call_passes_confirmed_through(self) -> None:
        manager = MagicMock()
        manager.place_call.return_value = {"success": True, "requires_confirmation": False, "message": "ok", "data": {}}
        tool = PhoneTool(manager=manager)

        tool.place_call({"request": "call united", "confirmed": True, "persona": "formal"})

        manager.place_call.assert_called_once_with(
            "call united",
            confirmed=True,
            persona_override="formal",
        )

    def test_place_call_builds_request_from_structured_params(self) -> None:
        manager = MagicMock()
        manager.place_call.return_value = {"success": True, "requires_confirmation": False, "message": "ok", "data": {}}
        tool = PhoneTool(manager=manager)

        tool.place_call({
            "recipient_name": "Carla at United",
            "recipient_number": "+15551234567",
            "objective": "ask about my refund",
        })

        called_request = manager.place_call.call_args.args[0]
        self.assertIn("Carla", called_request)
        self.assertIn("refund", called_request)

    def test_cancel_call_forwards_call_id_and_recipient(self) -> None:
        manager = MagicMock()
        manager.cancel_call.return_value = {"success": True, "requires_confirmation": False, "message": "ok", "data": {}}
        tool = PhoneTool(manager=manager)

        tool.cancel_call({"call_id": "call-1", "recipient": "United"})

        manager.cancel_call.assert_called_once_with(call_id="call-1", recipient_hint="United")

    def test_list_calls_delegates(self) -> None:
        manager = MagicMock()
        manager.list_calls.return_value = {"success": True, "requires_confirmation": False, "message": "ok", "data": {}}
        tool = PhoneTool(manager=manager)

        tool.list_calls({})

        manager.list_calls.assert_called_once()

    def test_summarize_last_call_delegates(self) -> None:
        manager = MagicMock()
        manager.summarize_last_call.return_value = {"success": True, "requires_confirmation": False, "message": "ok", "data": {}}
        tool = PhoneTool(manager=manager)

        tool.summarize_last_call({})

        manager.summarize_last_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
