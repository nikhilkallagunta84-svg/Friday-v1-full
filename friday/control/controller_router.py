from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from friday.control.browser_controller import BrowserController
from friday.control.confirmation_manager import build_confirmation_prompt, needs_confirmation
from friday.control.desktop_controller import DesktopController
from friday.control.emergency_stop import ControlStatus, EmergencyStopController
from friday.schemas.action_result import ActionResult
from friday.schemas.risk import RiskLevel, coerce_risk_level
from friday.schemas.screen_action import ActionType, ScreenAction


class ControllerRouter:
    def __init__(
        self,
        browser_controller: BrowserController | None = None,
        desktop_controller: DesktopController | None = None,
        accessibility_controller: object | None = None,
        vision_controller: object | None = None,
        emergency_stop: EmergencyStopController | None = None,
        root_dir: Path | str | None = None,
        confirmed_action_ids: Iterable[str] | None = None,
        stop_on_failure: bool = True,
    ) -> None:
        self.browser_controller = browser_controller
        self.desktop_controller = desktop_controller
        self.accessibility_controller = accessibility_controller
        self.vision_controller = vision_controller
        self.emergency_stop = emergency_stop or EmergencyStopController()
        self.root_dir = Path(root_dir) if root_dir is not None else Path.cwd()
        self.confirmed_action_ids = set(confirmed_action_ids or [])
        self.stop_on_failure = stop_on_failure

    def get_browser_controller(self) -> BrowserController:
        return self._browser()

    def execute_action(self, action: ScreenAction) -> ActionResult:
        result = self._execute_action(action)
        if self.emergency_stop.is_stop_requested():
            return result
        if result.error == "Confirmation required before execution.":
            self.emergency_stop.set_status(ControlStatus.WAITING_FOR_CONFIRMATION)
        else:
            self.emergency_stop.set_status(ControlStatus.IDLE)
        return result

    def _execute_action(self, action: ScreenAction) -> ActionResult:
        if self.emergency_stop.is_stop_requested():
            return self.emergency_stop.cancellation_result(action.action_id)
        if coerce_risk_level(action.risk_level) == RiskLevel.BLOCKED:
            return _failure(
                action.action_id,
                build_confirmation_prompt(action),
                "Blocked actions are not executable.",
                "router",
            )
        if needs_confirmation(action) and action.action_id not in self.confirmed_action_ids:
            return _failure(
                action.action_id,
                build_confirmation_prompt(action),
                "Confirmation required before execution.",
                "router",
            )
        if action.action_type == ActionType.SYSTEM_STOP:
            self.emergency_stop.trigger("System stop action requested.")
            return self.emergency_stop.cancellation_result(action.action_id)
        if _is_browser_action(action):
            self.emergency_stop.set_status(ControlStatus.CONTROLLING_BROWSER)
            return self._execute_browser_action(action)
        if _is_desktop_action(action):
            self.emergency_stop.set_status(ControlStatus.CONTROLLING_DESKTOP)
            return self._execute_desktop_action(action)
        if action.action_type == ActionType.SYSTEM_WAIT:
            return _success(action.action_id, "Wait action accepted by router.", "router")
        if action.action_type == ActionType.SYSTEM_ASK_CONFIRMATION:
            return _failure(action.action_id, build_confirmation_prompt(action), "Confirmation required before execution.", "router")
        return _failure(action.action_id, f"No controller route for {action.action_type.value}.", "Unsupported action type.", "router")

    def execute_plan(self, actions: Sequence[ScreenAction]) -> list[ActionResult]:
        results: list[ActionResult] = []
        if self.emergency_stop.is_stop_requested():
            action_id = actions[0].action_id if actions else "screen-plan"
            return [self.emergency_stop.cancellation_result(action_id)]

        self.emergency_stop.set_status(ControlStatus.PLANNING)
        for index, action in enumerate(actions):
            if self.emergency_stop.is_stop_requested():
                results.append(self.emergency_stop.cancellation_result(action.action_id))
                break
            result = self._execute_action(action)
            results.append(result)
            if self.emergency_stop.is_stop_requested():
                if index + 1 < len(actions):
                    results.append(self.emergency_stop.cancellation_result(actions[index + 1].action_id))
                break
            if self.stop_on_failure and not result.success:
                break
        if not self.emergency_stop.is_stop_requested():
            if results and results[-1].error == "Confirmation required before execution.":
                self.emergency_stop.set_status(ControlStatus.WAITING_FOR_CONFIRMATION)
            else:
                self.emergency_stop.set_status(ControlStatus.IDLE)
        return results

    def _execute_browser_action(self, action: ScreenAction) -> ActionResult:
        controller = self._browser()
        if action.action_type == ActionType.BROWSER_OPEN_URL:
            return controller.open_url(action.value)
        if action.action_type == ActionType.BROWSER_SEARCH:
            return controller.search(action.value)
        if action.action_type == ActionType.BROWSER_CLICK:
            return controller.click(action.target)
        if action.action_type == ActionType.BROWSER_TYPE:
            return controller.type_text(action.target, action.value)
        if action.action_type == ActionType.BROWSER_NAVIGATE:
            value = action.value.strip().lower()
            target = action.target.strip().lower()
            if value == "back" or target == "browser history":
                return controller.go_back()
            if value == "new_tab" or target == "new tab":
                return controller.new_tab()
            if value == "close_tab" or target == "close tab":
                return controller.close_tab()
            return _failure(action.action_id, f"Unknown browser navigation target: {action.value or action.target}.", "Unsupported browser navigation.", "browser")
        if action.action_type == ActionType.BROWSER_EXTRACT:
            title = controller.get_page_title()
            url = controller.get_current_url()
            message = f"Page title: {title}. URL: {url}."
            return _success(action.action_id, message, "browser")
        return _failure(action.action_id, f"No browser route for {action.action_type.value}.", "Unsupported browser action.", "browser")

    def _execute_desktop_action(self, action: ScreenAction) -> ActionResult:
        controller = self._desktop()
        if action.action_type == ActionType.DESKTOP_OPEN_APP:
            return controller.open_app(action.target or action.value)
        if action.action_type == ActionType.DESKTOP_FOCUS_APP:
            return controller.focus_app(action.target or action.value)
        if action.action_type == ActionType.DESKTOP_TYPE:
            return controller.type_text(action.value or action.target)
        if action.action_type == ActionType.DESKTOP_HOTKEY:
            return controller.hotkey(action.value or action.target, confirmed=action.action_id in self.confirmed_action_ids)
        return _failure(action.action_id, f"No desktop route for {action.action_type.value}.", "Unsupported desktop action.", "desktop")

    def _browser(self) -> BrowserController:
        if self.browser_controller is None:
            self.browser_controller = BrowserController(root_dir=self.root_dir)
        return self.browser_controller

    def _desktop(self) -> DesktopController:
        if self.desktop_controller is None:
            self.desktop_controller = DesktopController()
        return self.desktop_controller



def execute_action(action: ScreenAction) -> ActionResult:
    return ControllerRouter().execute_action(action)


def execute_plan(actions: list[ScreenAction]) -> list[ActionResult]:
    return ControllerRouter().execute_plan(actions)


def _is_browser_action(action: ScreenAction) -> bool:
    return action.action_type.value.startswith("browser.")


def _is_desktop_action(action: ScreenAction) -> bool:
    return action.action_type.value.startswith("desktop.")


def _success(action_id: str, message: str, controller_used: str) -> ActionResult:
    now = _now()
    return ActionResult(
        action_id=action_id,
        success=True,
        message=message,
        error="",
        started_at=now,
        finished_at=now,
        controller_used=controller_used,
    )


def _failure(action_id: str, message: str, error: str, controller_used: str) -> ActionResult:
    now = _now()
    return ActionResult(
        action_id=action_id,
        success=False,
        message=message,
        error=error,
        started_at=now,
        finished_at=now,
        controller_used=controller_used,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
