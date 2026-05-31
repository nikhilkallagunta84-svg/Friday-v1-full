from __future__ import annotations

import unittest

from friday.brain.risk_classifier import classify_action
from friday.control.confirmation_manager import build_confirmation_prompt, needs_confirmation
from friday.schemas.risk import RiskLevel
from friday.schemas.screen_action import ScreenAction


def make_action(
    action_type: str,
    target: str,
    value: str,
    source_command: str,
    risk_level: str = "safe",
    requires_confirmation: bool = False,
) -> ScreenAction:
    return ScreenAction(
        action_id=f"action-{abs(hash((action_type, target, value, source_command))) % 100000}",
        action_type=action_type,
        target=target,
        value=value,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        source_command=source_command,
    )


class ConfirmationManagerTests(unittest.TestCase):
    def test_low_risk_action_does_not_need_confirmation(self) -> None:
        action = classify_action(make_action("browser.open_url", "YouTube", "https://www.youtube.com", "open YouTube"))

        self.assertEqual(action.risk_level, RiskLevel.LOW)
        self.assertFalse(needs_confirmation(action))

    def test_high_risk_action_needs_confirmation(self) -> None:
        action = classify_action(make_action("browser.click", "Send email", "", "send this email"))

        self.assertEqual(action.risk_level, RiskLevel.HIGH)
        self.assertTrue(needs_confirmation(action))
        self.assertIn("Just to confirm", build_confirmation_prompt(action))

    def test_submit_form_needs_confirmation(self) -> None:
        action = classify_action(make_action("browser.click", "Submit form", "", "submit this form"))

        self.assertEqual(action.risk_level, RiskLevel.HIGH)
        self.assertTrue(needs_confirmation(action))
        self.assertIn("submit", build_confirmation_prompt(action).lower())

    def test_blocked_action_is_not_confirmable_for_execution(self) -> None:
        action = classify_action(make_action("desktop.hotkey", "Files", "", "delete files from downloads"))

        self.assertEqual(action.risk_level, RiskLevel.BLOCKED)
        self.assertFalse(needs_confirmation(action))
        self.assertIn("blocked for safety", build_confirmation_prompt(action))

    def test_type_password_gets_blocked_prompt(self) -> None:
        action = classify_action(make_action("browser.type", "Password field", "secret", "type my password"))

        self.assertEqual(action.risk_level, RiskLevel.BLOCKED)
        self.assertFalse(needs_confirmation(action))
        self.assertIn("can't do that", build_confirmation_prompt(action))


if __name__ == "__main__":
    unittest.main()
