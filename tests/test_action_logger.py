from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from friday.memory import ActionLogger, TaskHistory
from friday.schemas.action_result import ActionResult
from friday.schemas.screen_action import ScreenAction


def make_action(
    action_id: str,
    action_type: str,
    target: str = "",
    value: str = "",
    source_command: str = "open youtube",
) -> ScreenAction:
    return ScreenAction(
        action_id=action_id,
        action_type=action_type,
        target=target,
        value=value,
        risk_level="safe",
        requires_confirmation=False,
        source_command=source_command,
    )


def make_result(
    action_id: str,
    success: bool = True,
    message: str = "Done.",
    error: str = "",
    controller_used: str = "browser",
) -> ActionResult:
    now = datetime.now(timezone.utc)
    return ActionResult(
        action_id=action_id,
        success=success,
        message=message,
        error=error,
        started_at=now,
        finished_at=now,
        controller_used=controller_used,
    )


class ActionLoggerTests(unittest.TestCase):
    def test_normal_action_logs_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = ActionLogger(Path(temp_dir) / "screen-actions.jsonl")
            actions = [
                make_action("open", "browser.open_url", target="youtube", value="https://www.youtube.com", source_command="open youtube"),
                make_action("search", "browser.search", target="youtube search", value="AP Calculus derivatives", source_command="open youtube and search AP Calculus derivatives"),
            ]
            results = [
                make_result("open", controller_used="browser"),
                make_result("search", message="Searched.", controller_used="browser"),
            ]

            entry = logger.log_task("open youtube and search AP Calculus derivatives", actions, results)

            self.assertTrue(entry.success)
            self.assertEqual(entry.controllers_used, ["browser"])
            self.assertEqual(len(logger.get_recent_actions()), 1)
            self.assertIn("opened YouTube and searched for AP Calculus derivatives", logger.summarize_last_task())
            persisted = (Path(temp_dir) / "screen-actions.jsonl").read_text(encoding="utf-8")
            self.assertIn("AP Calculus derivatives", persisted)

    def test_password_is_redacted(self) -> None:
        logger = ActionLogger()
        action = make_action(
            "type-password",
            "browser.type",
            target="Password field",
            value="hunter2",
            source_command="type my password hunter2",
        )
        result = make_result("type-password", success=False, message="Refused password typing.", error="password hunter2 is blocked")

        entry = logger.log_task("type my password hunter2", [action], [result])
        payload = json.dumps(entry.to_dict()).lower()

        self.assertNotIn("hunter2", payload)
        self.assertIn("[redacted]", payload)

    def test_screenshots_are_never_logged(self) -> None:
        logger = ActionLogger()
        action = {
            "action_id": "vision",
            "action_type": "browser.extract",
            "target": "Screenshot 2026-05-14 at 10.55.27 AM.png",
            "value": "/tmp/private-screen.png",
            "risk_level": "safe",
            "requires_confirmation": False,
            "source_command": "analyze screenshot /tmp/private-screen.png",
            "created_at": datetime.now(timezone.utc),
        }
        result = make_result("vision", message="Analyzed /tmp/private-screen.png")

        entry = logger.log_task("analyze screenshot /tmp/private-screen.png", [action], [result])
        payload = json.dumps(entry.to_dict()).lower()

        self.assertNotIn("/tmp/private-screen.png", payload)
        self.assertNotIn("screenshot 2026", payload)
        self.assertNotIn(".png", payload)

    def test_error_messages_are_sanitized(self) -> None:
        logger = ActionLogger()
        action = make_action("send", "browser.click", target="Send", source_command="send email using api key re_secret_123456789")
        result = make_result(
            "send",
            success=False,
            message="Could not send with token abc.def.ghi",
            error="API key re_secret_123456789 failed for user@example.com",
            controller_used="router",
        )

        entry = logger.log_task("send email using api key re_secret_123456789", [action], [result])
        payload = json.dumps(entry.to_dict())

        self.assertNotIn("re_secret_123456789", payload)
        self.assertNotIn("user@example.com", payload)
        self.assertIn("[REDACTED_SECRET]", payload)
        self.assertIn("[REDACTED_EMAIL]", payload)

    def test_task_history_limit_and_empty_summary(self) -> None:
        history = TaskHistory()

        self.assertIn("do not have", history.summarize_last_task())
        self.assertEqual(history.get_recent_actions(limit=0), [])


if __name__ == "__main__":
    unittest.main()
