"""Tool wrapper around :class:`PhoneCallManager`.

Returns the canonical ``{success, requires_confirmation, message, data}`` shape
expected by :class:`ToolRouter`. Accepts a None manager so the router stays
constructable in test/self-test environments where Ollama isn't wired up.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from friday.phone.manager import PhoneCallManager


class PhoneTool:
    def __init__(self, manager: Optional[PhoneCallManager] = None) -> None:
        self.manager = manager

    # -- public commands ------------------------------------------------

    def place_call(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if self.manager is None:
            return self._unavailable("phone call")
        request = self._extract_request(parameters)
        if not request:
            return self._failure("Tell me who to call and why, boss.")
        confirmed = bool(parameters.get("confirmed", False))
        persona = str(parameters.get("persona") or "").strip()
        return self.manager.place_call(
            request,
            confirmed=confirmed,
            persona_override=persona or None,
        )

    def cancel_call(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if self.manager is None:
            return self._unavailable("call cancellation")
        call_id = str(parameters.get("call_id") or "").strip()
        recipient_hint = str(
            parameters.get("recipient")
            or parameters.get("recipient_name")
            or parameters.get("target")
            or ""
        ).strip()
        return self.manager.cancel_call(call_id=call_id, recipient_hint=recipient_hint)

    def list_calls(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: ARG002 - shape match
        if self.manager is None:
            return self._unavailable("call listing")
        return self.manager.list_calls()

    def summarize_last_call(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: ARG002
        if self.manager is None:
            return self._unavailable("call summary")
        return self.manager.summarize_last_call()

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _extract_request(parameters: Dict[str, Any]) -> str:
        for key in ("request", "task", "user_command", "prompt"):
            value = parameters.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        # Build a minimal request from structured parameters when present.
        name = str(parameters.get("recipient_name") or parameters.get("recipient") or "").strip()
        number = str(parameters.get("recipient_number") or parameters.get("number") or "").strip()
        objective = str(parameters.get("objective") or "").strip()
        if name or number or objective:
            who = name or number or "the recipient"
            if number and number not in who:
                who = f"{who} at {number}"
            return f"call {who} to {objective}" if objective else f"call {who}"
        return ""

    @staticmethod
    def _failure(message: str) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": {}}

    @staticmethod
    def _unavailable(feature: str) -> Dict[str, Any]:
        return {
            "success": False,
            "requires_confirmation": False,
            "message": f"The phone subsystem is not wired up in this build, so {feature} is unavailable, boss.",
            "data": {},
        }
