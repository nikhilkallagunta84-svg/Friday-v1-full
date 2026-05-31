from __future__ import annotations

import unittest

from friday.brain.safety_validator import SafetyValidator


class SafetyValidatorTests(unittest.TestCase):
    def test_submit_requires_confirmation(self) -> None:
        decision = SafetyValidator().validate("submit the assignment", {"parameters": {}})

        self.assertTrue(decision.requires_confirmation)
        self.assertIn("submitting", decision.reason)

    def test_confirmed_risky_action_is_allowed_to_continue(self) -> None:
        decision = SafetyValidator().validate("submit the assignment", {"parameters": {"confirmed": True}})

        self.assertFalse(decision.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
