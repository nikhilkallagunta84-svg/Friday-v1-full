from __future__ import annotations

import unittest

from friday.brain.risk_classifier import classify_action
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


class RiskClassifierTests(unittest.TestCase):
    def test_open_youtube_is_safe_or_low(self) -> None:
        action = make_action("browser.open_url", "YouTube", "https://www.youtube.com", "open YouTube")

        classified = classify_action(action)

        self.assertIn(classified.risk_level, {RiskLevel.SAFE, RiskLevel.LOW})
        self.assertFalse(classified.requires_confirmation)

    def test_search_spotify_is_safe_or_low(self) -> None:
        action = make_action("browser.search", "Spotify", "Lil Baby songs", "search Spotify for Lil Baby songs")

        classified = classify_action(action)

        self.assertIn(classified.risk_level, {RiskLevel.SAFE, RiskLevel.LOW})
        self.assertFalse(classified.requires_confirmation)

    def test_send_email_is_high_risk(self) -> None:
        action = make_action("browser.click", "Send email button", "", "send this email to my teacher")

        classified = classify_action(action)

        self.assertEqual(classified.risk_level, RiskLevel.HIGH)
        self.assertTrue(classified.requires_confirmation)

    def test_delete_file_is_blocked(self) -> None:
        action = make_action("desktop.hotkey", "Files", "", "delete the files in my downloads folder")

        classified = classify_action(action)

        self.assertEqual(classified.risk_level, RiskLevel.BLOCKED)
        self.assertTrue(classified.requires_confirmation)

    def test_type_password_is_blocked(self) -> None:
        action = make_action("browser.type", "Password field", "hunter2", "type my password into the login form")

        classified = classify_action(action)

        self.assertEqual(classified.risk_level, RiskLevel.BLOCKED)
        self.assertTrue(classified.requires_confirmation)

    def test_submit_form_is_high_risk(self) -> None:
        action = make_action("browser.click", "Submit form", "", "submit this application form")

        classified = classify_action(action)

        self.assertEqual(classified.risk_level, RiskLevel.HIGH)
        self.assertTrue(classified.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
