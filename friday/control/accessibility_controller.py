from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from friday.control.sensitive_text import contains_sensitive_text as _shared_contains_sensitive, redact_sensitive_text
from friday.schemas.action_result import ActionResult


TEXT_FIELD_ROLES = ("AXTextField", "AXTextArea", "AXComboBox", "text field", "text area")
BUTTON_ROLES = ("AXButton", "button")


class AccessibilityBackend(Protocol):
    def has_permission(self) -> bool:
        ...

    def list_windows(self) -> list[str]:
        ...

    def get_focused_window(self) -> str:
        ...

    def find_element(self, label: str, roles: tuple[str, ...]) -> str:
        ...

    def click_element(self, label: str) -> bool:
        ...

    def type_into_element(self, label: str, text: str) -> bool:
        ...


@dataclass
class SystemEventsAccessibilityBackend:
    runner: Any = subprocess.run

    def has_permission(self) -> bool:
        completed = self._run_applescript('tell application "System Events" to return UI elements enabled')
        return completed.returncode == 0 and completed.stdout.strip().lower() == "true"

    def list_windows(self) -> list[str]:
        script = """
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set windowNames to {}
            repeat with itemRef in windows of frontApp
                try
                    set end of windowNames to name of itemRef
                end try
            end repeat
            set AppleScript's text item delimiters to linefeed
            return windowNames as text
        end tell
        """
        completed = self._run_applescript(script)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Could not list accessibility windows.")
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    def get_focused_window(self) -> str:
        script = """
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            try
                return name of window 1 of frontApp
            on error
                return name of frontApp
            end try
        end tell
        """
        completed = self._run_applescript(script)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Could not read focused accessibility window.")
        return completed.stdout.strip()

    def find_element(self, label: str, roles: tuple[str, ...]) -> str:
        script = _find_element_script(label, roles, action="describe")
        completed = self._run_applescript(script)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Could not search accessibility elements.")
        return completed.stdout.strip()

    def click_element(self, label: str) -> bool:
        script = _find_element_script(label, BUTTON_ROLES, action="click")
        completed = self._run_applescript(script)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Could not click accessibility element.")
        return completed.stdout.strip().lower() == "clicked"

    def type_into_element(self, label: str, text: str) -> bool:
        script = _type_into_element_script(label, text)
        completed = self._run_applescript(script)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Could not type into accessibility element.")
        return completed.stdout.strip().lower() == "typed"

    def _run_applescript(self, script: str) -> Any:
        return self.runner(["osascript", "-e", script], capture_output=True, text=True, timeout=8)


class AccessibilityController:
    def __init__(
        self,
        backend: AccessibilityBackend | None = None,
        system_name: str | None = None,
    ) -> None:
        self.backend = backend or SystemEventsAccessibilityBackend()
        self.system_name = system_name or platform.system()

    def list_windows(self) -> ActionResult:
        started_at = _now()
        permission = self._permission_result("accessibility.list_windows", started_at)
        if permission:
            return permission
        try:
            windows = [_redact_sensitive_text(window) for window in self.backend.list_windows()]
        except BaseException as exc:
            return _failure("accessibility.list_windows", "Could not list accessibility windows.", _redact_sensitive_text(str(exc)), started_at)
        message = "Visible windows: " + "; ".join(windows) if windows else "No accessibility windows were found."
        return _success("accessibility.list_windows", message, started_at)

    def get_focused_window(self) -> ActionResult:
        started_at = _now()
        permission = self._permission_result("accessibility.get_focused_window", started_at)
        if permission:
            return permission
        try:
            window = _redact_sensitive_text(self.backend.get_focused_window())
        except BaseException as exc:
            return _failure("accessibility.get_focused_window", "Could not read the focused window.", _redact_sensitive_text(str(exc)), started_at)
        if not window:
            return _failure("accessibility.get_focused_window", "No focused accessibility window was found.", "Focused window unavailable.", started_at)
        return _success("accessibility.get_focused_window", f"Focused window: {window}.", started_at)

    def find_button(self, label: str) -> ActionResult:
        return self._find_element("accessibility.find_button", label, BUTTON_ROLES, "button")

    def find_text_field(self, label: str) -> ActionResult:
        return self._find_element("accessibility.find_text_field", label, TEXT_FIELD_ROLES, "text field")

    def click_accessibility_element(self, label: str) -> ActionResult:
        started_at = _now()
        clean_label = _clean_label(label)
        if not clean_label:
            return _failure("accessibility.click", "Tell me which accessibility element to click.", "Element label is empty.", started_at)
        permission = self._permission_result("accessibility.click", started_at)
        if permission:
            return permission
        try:
            clicked = self.backend.click_element(clean_label)
        except BaseException as exc:
            return _failure("accessibility.click", f"Could not click {_redact_sensitive_text(clean_label)}.", _redact_sensitive_text(str(exc)), started_at)
        if not clicked:
            return _failure("accessibility.click", f"Could not find {_redact_sensitive_text(clean_label)} to click.", "Accessibility element not found.", started_at)
        return _success("accessibility.click", f"Clicked {_redact_sensitive_text(clean_label)}.", started_at)

    def type_into_accessibility_element(self, label: str, text: str) -> ActionResult:
        started_at = _now()
        clean_label = _clean_label(label)
        if not clean_label:
            return _failure("accessibility.type", "Tell me which accessibility text field to use.", "Element label is empty.", started_at)
        if _contains_sensitive_text(text):
            return _failure("accessibility.type", "I can't type passwords or security codes, boss.", "Sensitive text typing refused.", started_at)
        permission = self._permission_result("accessibility.type", started_at)
        if permission:
            return permission
        try:
            typed = self.backend.type_into_element(clean_label, text)
        except BaseException as exc:
            return _failure("accessibility.type", f"Could not type into {_redact_sensitive_text(clean_label)}.", _redact_sensitive_text(str(exc)), started_at)
        if not typed:
            return _failure("accessibility.type", f"Could not find {_redact_sensitive_text(clean_label)} to type into.", "Accessibility text field not found.", started_at)
        return _success("accessibility.type", f"Typed text into {_redact_sensitive_text(clean_label)}.", started_at)

    def _find_element(self, action_id: str, label: str, roles: tuple[str, ...], friendly_type: str) -> ActionResult:
        started_at = _now()
        clean_label = _clean_label(label)
        if not clean_label:
            return _failure(action_id, f"Tell me which {friendly_type} to find.", "Element label is empty.", started_at)
        permission = self._permission_result(action_id, started_at)
        if permission:
            return permission
        try:
            match = _redact_sensitive_text(self.backend.find_element(clean_label, roles))
        except BaseException as exc:
            return _failure(action_id, f"Could not search for {_redact_sensitive_text(clean_label)}.", _redact_sensitive_text(str(exc)), started_at)
        if not match:
            return _failure(action_id, f"I couldn't find a {friendly_type} labeled {_redact_sensitive_text(clean_label)}.", "Accessibility element not found.", started_at)
        return _success(action_id, f"Found {friendly_type}: {match}.", started_at)

    def _permission_result(self, action_id: str, started_at: datetime) -> ActionResult | None:
        if self.system_name != "Darwin":
            return _failure(action_id, "Accessibility control is only implemented for macOS right now.", "Unsupported operating system.", started_at)
        try:
            has_permission = self.backend.has_permission()
        except BaseException as exc:
            return _failure(action_id, "Accessibility permission is required for UI control.", _redact_sensitive_text(str(exc)), started_at)
        if not has_permission:
            return _failure(
                action_id,
                "Accessibility permission is required for UI control. Enable it for Codex, Terminal, or your Python app in System Settings > Privacy & Security > Accessibility.",
                "Accessibility permission is missing.",
                started_at,
            )
        return None


def _find_element_script(label: str, roles: tuple[str, ...], action: str) -> str:
    label_text = _apple_string(label)
    roles_list = "{" + ", ".join(_apple_string(role) for role in roles) + "}"
    press_block = 'perform action "AXPress" of itemRef\nreturn "clicked"' if action == "click" else 'return itemName & " " & itemRole'
    return f"""
    set targetLabel to {label_text}
    set targetRoles to {roles_list}
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        repeat with itemRef in entire contents of frontApp
            try
                set itemRole to role of itemRef as text
                if targetRoles contains itemRole then
                    set itemName to ""
                    try
                        set itemName to name of itemRef as text
                    end try
                    set itemDesc to ""
                    try
                        set itemDesc to description of itemRef as text
                    end try
                    set itemValue to ""
                    try
                        set itemValue to value of itemRef as text
                    end try
                    if itemName contains targetLabel or itemDesc contains targetLabel or itemValue contains targetLabel then
                        {press_block}
                    end if
                end if
            end try
        end repeat
    end tell
    return ""
    """


def _type_into_element_script(label: str, text: str) -> str:
    label_text = _apple_string(label)
    value_text = _apple_string(text)
    roles_list = "{" + ", ".join(_apple_string(role) for role in TEXT_FIELD_ROLES) + "}"
    return f"""
    set targetLabel to {label_text}
    set textValue to {value_text}
    set targetRoles to {roles_list}
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        repeat with itemRef in entire contents of frontApp
            try
                set itemRole to role of itemRef as text
                if targetRoles contains itemRole then
                    set itemName to ""
                    try
                        set itemName to name of itemRef as text
                    end try
                    set itemDesc to ""
                    try
                        set itemDesc to description of itemRef as text
                    end try
                    if itemName contains targetLabel or itemDesc contains targetLabel then
                        set value of itemRef to textValue
                        return "typed"
                    end if
                end if
            end try
        end repeat
    end tell
    return ""
    """


def _apple_string(value: str) -> str:
    return json.dumps(value)


def _clean_label(label: str) -> str:
    return " ".join(label.strip().split())


def _contains_sensitive_text(text: str) -> bool:
    return _shared_contains_sensitive(text)


def _redact_sensitive_text(text: str) -> str:
    return redact_sensitive_text(text)


def _success(action_id: str, message: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        success=True,
        message=_redact_sensitive_text(message),
        error="",
        started_at=started_at,
        finished_at=_now(),
        controller_used="accessibility",
    )


def _failure(action_id: str, message: str, error: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        success=False,
        message=_redact_sensitive_text(message),
        error=_redact_sensitive_text(error or message),
        started_at=started_at,
        finished_at=_now(),
        controller_used="accessibility",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
