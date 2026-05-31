from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from friday.schemas.action_result import ActionResult
from friday.schemas.risk import RiskLevel, coerce_risk_level
from friday.schemas.screen_action import ActionType, ScreenAction


class ScreenActionSchemaTests(unittest.TestCase):
    def test_valid_action_can_be_created(self) -> None:
        action = ScreenAction(
            action_id="act-001",
            action_type="browser.click",
            target="Search box",
            value="Lil Baby songs",
            risk_level="low",
            requires_confirmation=False,
            source_command="open YouTube and search Lil Baby songs",
        )

        self.assertEqual(action.action_type, ActionType.BROWSER_CLICK)
        self.assertEqual(action.risk_level, RiskLevel.LOW)
        self.assertEqual(action.to_dict()["action_type"], "browser.click")

    def test_invalid_action_type_fails(self) -> None:
        with self.assertRaises(ValueError):
            ScreenAction(
                action_id="act-002",
                action_type="browser.hover",
                target="Search box",
                value="",
                risk_level="safe",
                requires_confirmation=False,
                source_command="hover the search box",
            )

    def test_risk_levels_validate_correctly(self) -> None:
        self.assertEqual(coerce_risk_level("safe"), RiskLevel.SAFE)
        self.assertEqual(coerce_risk_level("blocked"), RiskLevel.BLOCKED)
        with self.assertRaises(ValueError):
            coerce_risk_level("dangerous")

    def test_blocked_and_high_actions_can_require_confirmation(self) -> None:
        high = ScreenAction(
            action_id="act-003",
            action_type="system.ask_confirmation",
            target="Email send confirmation",
            value="send",
            risk_level="high",
            requires_confirmation=True,
            source_command="send that email",
        )
        blocked = ScreenAction(
            action_id="act-004",
            action_type="system.stop",
            target="Unsafe payment action",
            value="blocked",
            risk_level="blocked",
            requires_confirmation=True,
            source_command="buy this with my card",
        )

        self.assertTrue(high.requires_confirmation)
        self.assertTrue(blocked.requires_confirmation)

    def test_high_action_without_confirmation_fails(self) -> None:
        with self.assertRaises(ValueError):
            ScreenAction(
                action_id="act-005",
                action_type="browser.type",
                target="Password field",
                value="secret",
                risk_level="high",
                requires_confirmation=False,
                source_command="type my password",
            )

    def test_action_result_records_success_and_failure(self) -> None:
        started = datetime.now(timezone.utc)
        finished = started + timedelta(milliseconds=20)
        success = ActionResult(
            action_id="act-006",
            success=True,
            message="Clicked Search box.",
            error="",
            started_at=started,
            finished_at=finished,
            controller_used="schema-test",
        )
        failure = ActionResult(
            action_id="act-007",
            success=False,
            message="Could not locate target.",
            error="Target not visible.",
            started_at=started,
            finished_at=finished,
            controller_used="schema-test",
        )

        self.assertTrue(success.success)
        self.assertEqual(success.error, "")
        self.assertFalse(failure.success)
        self.assertEqual(failure.error, "Target not visible.")


if __name__ == "__main__":
    unittest.main()
