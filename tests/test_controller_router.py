from __future__ import annotations

from datetime import datetime, timezone
import unittest

from friday.control.controller_router import ControllerRouter
from friday.schemas.action_result import ActionResult
from friday.schemas.risk import RiskLevel
from friday.schemas.screen_action import ScreenAction


class FakeBrowserController:
    def __init__(self, fail_actions: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail_actions = fail_actions or set()

    def open_url(self, url: str) -> ActionResult:
        self.calls.append(("open_url", url, ""))
        return self._result("browser.open_url", "Opened fake URL.", "open_url")

    def search(self, query: str) -> ActionResult:
        self.calls.append(("search", query, ""))
        return self._result("browser.search", "Searched fake query.", "search")

    def click(self, target: str) -> ActionResult:
        self.calls.append(("click", target, ""))
        return self._result("browser.click", "Clicked fake target.", "click")

    def type_text(self, target: str, text: str) -> ActionResult:
        self.calls.append(("type_text", target, text))
        return self._result("browser.type", "Typed fake text.", "type_text")

    def go_back(self) -> ActionResult:
        self.calls.append(("go_back", "", ""))
        return self._result("browser.navigate", "Went back.", "go_back")

    def new_tab(self) -> ActionResult:
        self.calls.append(("new_tab", "", ""))
        return self._result("browser.navigate", "Opened new tab.", "new_tab")

    def close_tab(self) -> ActionResult:
        self.calls.append(("close_tab", "", ""))
        return self._result("browser.navigate", "Closed tab.", "close_tab")

    def get_page_title(self) -> str:
        return "Fake Title"

    def get_current_url(self) -> str:
        return "https://example.com"

    def _result(self, action_id: str, message: str, method: str) -> ActionResult:
        now = datetime.now(timezone.utc)
        if method in self.fail_actions:
            return ActionResult(
                action_id=action_id,
                success=False,
                message=f"{method} failed.",
                error="fake failure",
                started_at=now,
                finished_at=now,
                controller_used="fake-browser",
            )
        return ActionResult(
            action_id=action_id,
            success=True,
            message=message,
            error="",
            started_at=now,
            finished_at=now,
            controller_used="fake-browser",
        )


class FakeDesktopController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def open_app(self, app_name: str) -> ActionResult:
        self.calls.append(("open_app", app_name))
        return self._result("desktop.open_app", "Opened fake app.")

    def focus_app(self, app_name: str) -> ActionResult:
        self.calls.append(("focus_app", app_name))
        return self._result("desktop.focus_app", "Focused fake app.")

    def type_text(self, text: str) -> ActionResult:
        self.calls.append(("type_text", text))
        return self._result("desktop.type", "Typed fake text.")

    def hotkey(self, keys: str, confirmed: bool = False) -> ActionResult:
        self.calls.append(("hotkey", f"{keys}:{confirmed}"))
        return self._result("desktop.hotkey", "Pressed fake hotkey.")

    def _result(self, action_id: str, message: str) -> ActionResult:
        now = datetime.now(timezone.utc)
        return ActionResult(
            action_id=action_id,
            success=True,
            message=message,
            error="",
            started_at=now,
            finished_at=now,
            controller_used="fake-desktop",
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


class ControllerRouterTests(unittest.TestCase):
    def test_browser_open_url_routes_to_browser_controller(self) -> None:
        browser = FakeBrowserController()
        router = ControllerRouter(browser_controller=browser)
        action = make_action("action-1", "browser.open_url", target="youtube", value="https://www.youtube.com")

        result = router.execute_action(action)

        self.assertTrue(result.success)
        self.assertEqual(browser.calls, [("open_url", "https://www.youtube.com", "")])

    def test_blocked_action_refuses(self) -> None:
        browser = FakeBrowserController()
        router = ControllerRouter(browser_controller=browser)
        action = make_action("action-2", "browser.type", target="Password", value="secret", risk_level=RiskLevel.BLOCKED, requires_confirmation=True)

        result = router.execute_action(action)

        self.assertFalse(result.success)
        self.assertEqual(result.controller_used, "router")
        self.assertIn("Blocked actions are not executable", result.error)
        self.assertEqual(browser.calls, [])

    def test_high_risk_action_does_not_execute_without_confirmation(self) -> None:
        browser = FakeBrowserController()
        router = ControllerRouter(browser_controller=browser)
        action = make_action("action-3", "browser.click", target="Send", risk_level=RiskLevel.HIGH, requires_confirmation=True)

        result = router.execute_action(action)

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Confirmation required before execution.")
        self.assertIn("Just to confirm", result.message)
        self.assertEqual(browser.calls, [])

    def test_failed_action_stops_plan_if_critical(self) -> None:
        browser = FakeBrowserController(fail_actions={"open_url"})
        router = ControllerRouter(browser_controller=browser)
        actions = [
            make_action("action-4", "browser.open_url", target="bad", value="https://bad.example"),
            make_action("action-5", "browser.search", target="search", value="should not run"),
        ]

        results = router.execute_plan(actions)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertEqual(browser.calls, [("open_url", "https://bad.example", "")])

    def test_successful_multi_action_plan_returns_multiple_results(self) -> None:
        browser = FakeBrowserController()
        router = ControllerRouter(browser_controller=browser)
        actions = [
            make_action("action-6", "browser.open_url", target="spotify", value="https://open.spotify.com"),
            make_action("action-7", "browser.search", target="spotify search", value="Lil Baby"),
        ]

        results = router.execute_plan(actions)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.success for result in results))
        self.assertEqual(browser.calls, [("open_url", "https://open.spotify.com", ""), ("search", "Lil Baby", "")])

    def test_desktop_open_routes_to_desktop_controller(self) -> None:
        desktop = FakeDesktopController()
        router = ControllerRouter(browser_controller=FakeBrowserController(), desktop_controller=desktop)
        action = make_action("action-8", "desktop.open_app", target="Spotify", risk_level=RiskLevel.SAFE)

        result = router.execute_action(action)

        self.assertTrue(result.success)
        self.assertEqual(desktop.calls, [("open_app", "Spotify")])


if __name__ == "__main__":
    unittest.main()
