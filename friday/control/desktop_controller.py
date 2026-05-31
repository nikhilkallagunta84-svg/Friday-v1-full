from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from friday.control.sensitive_text import contains_sensitive_text
from friday.schemas.action_result import ActionResult


@dataclass(frozen=True)
class DesktopApp:
    display_name: str
    aliases: tuple[str, ...]
    requires_explicit_allow: bool = False


APP_REGISTRY = (
    DesktopApp("Google Chrome", ("chrome", "google chrome")),
    DesktopApp("Safari", ("safari",)),
    DesktopApp("Spotify", ("spotify",)),
    DesktopApp("Visual Studio Code", ("vs code", "vscode", "visual studio code", "code")),
    DesktopApp("Notes", ("notes", "apple notes")),
    DesktopApp("Finder", ("finder",)),
    DesktopApp("Terminal", ("terminal", "terminal app"), requires_explicit_allow=True),
)

KEY_ALIASES = {
    "cmd": "command",
    "⌘": "command",
    "control": "ctrl",
    "option": "alt",
    "return": "enter",
    "escape": "esc",
    "spacebar": "space",
    "delete": "backspace",
}

ALLOWED_KEYS = {
    "command",
    "shift",
    "ctrl",
    "alt",
    "tab",
    "enter",
    "esc",
    "space",
    "backspace",
    "left",
    "right",
    "up",
    "down",
    "home",
    "end",
    "pageup",
    "pagedown",
    *tuple(chr(code) for code in range(ord("a"), ord("z") + 1)),
    *tuple(str(number) for number in range(10)),
    *tuple(f"f{number}" for number in range(1, 13)),
}

DESTRUCTIVE_HOTKEYS = {
    ("command", "q"),
    ("command", "w"),
    ("command", "backspace"),
    ("command", "shift", "backspace"),
}



class DesktopController:
    def __init__(
        self,
        allow_terminal: bool = False,
        system_name: str | None = None,
        subprocess_runner: Callable[..., Any] | None = None,
        keyboard_backend: Any | None = None,
    ) -> None:
        self.allow_terminal = allow_terminal
        self.system_name = system_name or platform.system()
        self.subprocess_runner = subprocess_runner or subprocess.run
        self.keyboard_backend = keyboard_backend

    def open_app(self, app_name: str) -> ActionResult:
        started_at = _now()
        app = self._resolve_app(app_name)
        if app is None:
            return _failure("desktop.open_app", f"I don't recognize {app_name!r} as an allowed app.", "Unknown or disallowed app.", started_at)
        if app.requires_explicit_allow and not self.allow_terminal:
            return _failure("desktop.open_app", "Terminal control is disabled unless explicitly allowed.", "Terminal requires explicit allow.", started_at)
        if self.system_name != "Darwin":
            return _failure("desktop.open_app", f"Desktop app control is only implemented for macOS right now, not {self.system_name}.", "Unsupported operating system.", started_at)
        return self._run_open_app(app.display_name, "desktop.open_app", f"Opened {app.display_name}.", started_at)

    def focus_app(self, app_name: str) -> ActionResult:
        started_at = _now()
        app = self._resolve_app(app_name)
        if app is None:
            return _failure("desktop.focus_app", f"I don't recognize {app_name!r} as an allowed app.", "Unknown or disallowed app.", started_at)
        if app.requires_explicit_allow and not self.allow_terminal:
            return _failure("desktop.focus_app", "Terminal focus is disabled unless explicitly allowed.", "Terminal requires explicit allow.", started_at)
        if self.system_name != "Darwin":
            return _failure("desktop.focus_app", f"Desktop app focus is only implemented for macOS right now, not {self.system_name}.", "Unsupported operating system.", started_at)
        return self._run_open_app(app.display_name, "desktop.focus_app", f"Focused {app.display_name}.", started_at)

    def type_text(self, text: str) -> ActionResult:
        started_at = _now()
        if self._contains_sensitive_text(text):
            return _failure("desktop.type", "I can't type passwords or security codes, boss.", "Sensitive text typing refused.", started_at)
        try:
            keyboard = self._keyboard()
            keyboard.write(text, interval=0.01)
        except BaseException as exc:
            return _failure("desktop.type", "Could not type into the active app.", str(exc), started_at)
        return _success("desktop.type", "Typed text into the active app.", started_at)

    def hotkey(self, keys: Sequence[str] | str, confirmed: bool = False) -> ActionResult:
        started_at = _now()
        normalized = self._normalize_keys(keys)
        if not normalized:
            return _failure("desktop.hotkey", "No hotkey was provided.", "Hotkey cannot be empty.", started_at)
        invalid = [key for key in normalized if key not in ALLOWED_KEYS]
        if invalid:
            return _failure("desktop.hotkey", f"Hotkey contains unsupported key: {', '.join(invalid)}.", "Unsupported hotkey key.", started_at)
        if self._is_destructive_hotkey(normalized) and not confirmed:
            return _failure("desktop.hotkey", "That hotkey can close or delete things, so I need confirmation first.", "Destructive hotkey requires confirmation.", started_at)
        try:
            keyboard = self._keyboard()
            keyboard.hotkey(*normalized)
        except BaseException as exc:
            return _failure("desktop.hotkey", "Could not press that hotkey.", str(exc), started_at)
        return _success("desktop.hotkey", f"Pressed {'+'.join(normalized)}.", started_at)

    def press_key(self, key: str) -> ActionResult:
        started_at = _now()
        normalized = self._normalize_key(key)
        if not normalized:
            return _failure("desktop.press_key", "No key was provided.", "Key cannot be empty.", started_at)
        if normalized not in ALLOWED_KEYS:
            return _failure("desktop.press_key", f"Unsupported key: {normalized}.", "Unsupported key.", started_at)
        try:
            keyboard = self._keyboard()
            keyboard.press(normalized)
        except BaseException as exc:
            return _failure("desktop.press_key", f"Could not press {normalized}.", str(exc), started_at)
        return _success("desktop.press_key", f"Pressed {normalized}.", started_at)

    def _run_open_app(self, app_name: str, action_id: str, message: str, started_at: datetime) -> ActionResult:
        command = ["open", "-a", app_name]
        try:
            completed = self.subprocess_runner(command, capture_output=True, text=True, timeout=10)
        except BaseException as exc:
            return _failure(action_id, f"Could not open {app_name}.", str(exc), started_at)
        if getattr(completed, "returncode", 1) != 0:
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            return _failure(action_id, f"Could not open {app_name}.", stderr or "open command failed.", started_at)
        return _success(action_id, message, started_at)

    def _resolve_app(self, app_name: str) -> DesktopApp | None:
        clean = _normalize_text(app_name)
        if not clean:
            return None
        for app in APP_REGISTRY:
            if clean == _normalize_text(app.display_name) or clean in app.aliases:
                return app
        return None

    def _keyboard(self) -> Any:
        if self.keyboard_backend is not None:
            return self.keyboard_backend
        import pyautogui

        return pyautogui

    def _normalize_keys(self, keys: Sequence[str] | str) -> list[str]:
        if isinstance(keys, str):
            raw_keys = re.split(r"\s*\+\s*|\s+", keys.strip())
        else:
            raw_keys = [str(key) for key in keys]
        return [key for key in (self._normalize_key(key) for key in raw_keys) if key]

    def _normalize_key(self, key: str) -> str:
        clean = _normalize_text(key).replace(" ", "")
        return KEY_ALIASES.get(clean, clean)

    def _is_destructive_hotkey(self, keys: Sequence[str]) -> bool:
        key_tuple = tuple(keys)
        return key_tuple in DESTRUCTIVE_HOTKEYS

    @staticmethod
    def _contains_sensitive_text(text: str) -> bool:
        return contains_sensitive_text(text)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _success(action_id: str, message: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        success=True,
        message=message,
        error="",
        started_at=started_at,
        finished_at=_now(),
        controller_used="desktop",
    )


def _failure(action_id: str, message: str, error: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        success=False,
        message=message,
        error=error or message,
        started_at=started_at,
        finished_at=_now(),
        controller_used="desktop",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
