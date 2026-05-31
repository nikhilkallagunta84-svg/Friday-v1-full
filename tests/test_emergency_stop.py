from __future__ import annotations

from datetime import datetime, timezone
import unittest

from friday.control.controller_router import ControllerRouter
from friday.control.emergency_stop import ControlStatus, EmergencyStopController
from friday.schemas.action_result import ActionResult
from friday.schemas.risk import RiskLevel
from friday.schemas.screen_action import ScreenAction


class FakeBrowserController:
    def __init__(self, emergency_stop: EmergencyStopController | None = None, stop_on_open: bool = False) -> None:
        self.emergency_stop = emergency_stop
        self.stop_on_open = stop_on_open
        self.calls: list[tuple[str, str]] = []
        self.statuses_seen: list[str] = []

    def open_url(self, url: str) -> ActionResult:
        self.calls.append(("open_url", url))
        self._record_status()
        if self.stop_on_open and self.emergency_stop is not None:
            self.emergency_stop.trigger("Fake browser requested emergency stop.")
        return self._success("browser.open_url", "Opened fake URL.")

    def search(self, query: str) -> ActionResult:
        self.calls.append(("search", query))
        self._record_status()
        return self._success("browser.search", "Searched fake query.")

    def _record_status(self) -> None:
        if self.emergency_stop is not None:
            self.statuses_seen.append(self.emergency_stop.snapshot().status)

    def _success(self, action_id: str, message: str) -> ActionResult:
        now = datetime.now(timezone.utc)
        return ActionResult(
            action_id=action_id,
            success=True,
            message=message,
            error="",
            started_at=now,
            finished_at=now,
            controller_used="fake-browser",
        )


def make_action(
    action_id: str,
    action_type: str,
    target: str = "",
    value: str = "",
    risk_level: RiskLevel | str = RiskLevel.LOW,
    requires_confirmation: bool = False,
) -> ScreenAction:
    return ScreenAction(
        action_id=action_id,
        action_type=action_type,
        target=target,
        value=value,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        source_command=f"test command for {action_id}",
    )


class EmergencyStopTests(unittest.TestCase):
    def test_stop_flag_can_be_triggered_from_text(self) -> None:
        emergency_stop = EmergencyStopController()

        triggered = emergency_stop.trigger_from_text("Friday stop")

        snapshot = emergency_stop.snapshot()
        self.assertTrue(triggered)
        self.assertTrue(snapshot.stop_requested)
        self.assertEqual(snapshot.status, ControlStatus.STOPPED.value)
        self.assertIn("Friday stop", snapshot.reason)

    def test_router_stops_plan_mid_execution(self) -> None:
        emergency_stop = EmergencyStopController()
        browser = FakeBrowserController(emergency_stop=emergency_stop, stop_on_open=True)
        router = ControllerRouter(browser_controller=browser, emergency_stop=emergency_stop)
        actions = [
            make_action("open-youtube", "browser.open_url", target="youtube", value="https://www.youtube.com"),
            make_action("search-calculus", "browser.search", target="youtube search", value="calculus"),
        ]

        results = router.execute_plan(actions)

        self.assertEqual(browser.calls, [("open_url", "https://www.youtube.com")])
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].success)
        self.assertFalse(results[1].success)
        self.assertEqual(results[1].message, "Stopped, sir.")
        self.assertEqual(results[1].controller_used, "emergency-stop")
        self.assertEqual(emergency_stop.snapshot().status, ControlStatus.STOPPED.value)

    def test_queued_actions_are_not_executed_after_stop(self) -> None:
        emergency_stop = EmergencyStopController()
        emergency_stop.trigger("Pre-existing stop.")
        browser = FakeBrowserController(emergency_stop=emergency_stop)
        router = ControllerRouter(browser_controller=browser, emergency_stop=emergency_stop)
        actions = [
            make_action("open-youtube", "browser.open_url", target="youtube", value="https://www.youtube.com"),
            make_action("search-calculus", "browser.search", target="youtube search", value="calculus"),
        ]

        results = router.execute_plan(actions)

        self.assertEqual(browser.calls, [])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertEqual(results[0].message, "Stopped, sir.")

    def test_status_changes_correctly(self) -> None:
        emergency_stop = EmergencyStopController()
        browser = FakeBrowserController(emergency_stop=emergency_stop)
        router = ControllerRouter(browser_controller=browser, emergency_stop=emergency_stop)

        emergency_stop.set_status(ControlStatus.PLANNING)
        self.assertEqual(emergency_stop.snapshot().status, ControlStatus.PLANNING.value)

        router.execute_plan([
            make_action("open-youtube", "browser.open_url", target="youtube", value="https://www.youtube.com"),
        ])
        self.assertIn(ControlStatus.CONTROLLING_BROWSER.value, browser.statuses_seen)
        self.assertEqual(emergency_stop.snapshot().status, ControlStatus.IDLE.value)

        high_risk = make_action(
            "send-form",
            "browser.click",
            target="Submit form",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True,
        )
        result = router.execute_action(high_risk)
        self.assertFalse(result.success)
        self.assertEqual(emergency_stop.snapshot().status, ControlStatus.WAITING_FOR_CONFIRMATION.value)

        emergency_stop.trigger_from_text("abort")
        self.assertEqual(emergency_stop.snapshot().status, ControlStatus.STOPPED.value)
        emergency_stop.clear()
        self.assertEqual(emergency_stop.snapshot().status, ControlStatus.IDLE.value)


if __name__ == "__main__":
    unittest.main()
