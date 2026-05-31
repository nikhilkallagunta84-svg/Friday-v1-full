from __future__ import annotations

import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from friday.control.desktop_controller import ALLOWED_KEYS, KEY_ALIASES
from friday.control.sensitive_text import contains_visual_sensitive_text
from friday.schemas.action_result import ActionResult


HIGH_RISK_CLICK_PATTERNS = [
    r"\bpay(?:ment)?\b",
    r"\bpurchase\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\bsend\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bsubmit\b",
    r"\bturn\s+in\b",
    r"\bpost\b",
    r"\bpublish\b",
]



@dataclass(frozen=True)
class VisionLocation:
    x: float
    y: float
    confidence: float
    description: str = ""


class VisionController:
    def __init__(
        self,
        pyautogui_backend: Any | None = None,
        locator_backend: Callable[[Path, str], VisionLocation | None] | None = None,
        screenshot_redactor: Callable[[Path], None] | None = None,
        confidence_threshold: float = 0.72,
        max_screenshot_lifetime_seconds: float = 2.0,
        dry_run: bool = False,
    ) -> None:
        self.pyautogui_backend = pyautogui_backend
        self.locator_backend = locator_backend or self._default_locator
        self.screenshot_redactor = screenshot_redactor or self._redact_screenshot_stub
        self.confidence_threshold = max(0.0, min(float(confidence_threshold), 1.0))
        self.max_screenshot_lifetime_seconds = max(0.1, float(max_screenshot_lifetime_seconds))
        self.dry_run = dry_run
        self.last_location: VisionLocation | None = None

    def take_ephemeral_screenshot(self) -> ActionResult:
        started_at = _now()
        try:
            with self._ephemeral_screenshot_path() as path:
                if not path.exists():
                    return _failure("vision.screenshot", "Could not capture an ephemeral screenshot.", "Screenshot file was missing.", started_at)
        except BaseException as exc:
            return _failure("vision.screenshot", "Could not capture an ephemeral screenshot.", str(exc), started_at)
        return _success("vision.screenshot", "Captured an ephemeral screenshot and deleted it immediately.", started_at)

    def locate_text_or_element(self, description: str, confirmed: bool = False) -> ActionResult:
        started_at = _now()
        clean_description = _clean_text(description)
        if not clean_description:
            return _failure("vision.locate", "Tell me what to locate on screen.", "Description cannot be empty.", started_at)
        if _contains_blocked_sensitive_text(clean_description):
            return _failure("vision.locate", "I can't locate sensitive security fields with vision, boss.", "Blocked sensitive visual target.", started_at)
        try:
            with self._ephemeral_screenshot_path() as path:
                location = self.locator_backend(path, clean_description)
        except BaseException as exc:
            return _failure("vision.locate", f"I couldn't locate {clean_description}.", str(exc), started_at)
        if location is None:
            return _failure("vision.locate", f"I couldn't locate {clean_description}.", "Vision locator did not find a match.", started_at)
        self.last_location = location
        if location.confidence < self.confidence_threshold and not confirmed:
            return _failure(
                "vision.locate",
                f"I found a possible match for {clean_description}, but confidence is low. I need confirmation before clicking.",
                "Low confidence requires confirmation.",
                started_at,
            )
        return _success(
            "vision.locate",
            f"Located {clean_description} at {location.x:g}, {location.y:g} with confidence {location.confidence:.2f}.",
            started_at,
        )

    def click_coordinates(
        self,
        x: float,
        y: float,
        description: str = "",
        confidence: float = 1.0,
        confirmed: bool = False,
    ) -> ActionResult:
        started_at = _now()
        clean_description = _clean_text(description)
        if _contains_blocked_sensitive_text(clean_description):
            return _failure("vision.click", "I can't click sensitive security fields with vision, boss.", "Blocked sensitive visual action.", started_at)
        if _is_high_risk_click(clean_description) and not confirmed:
            return _failure("vision.click", "I need confirmation before clicking that high-risk UI element, sir.", "High-risk click requires confirmation.", started_at)
        if confidence < self.confidence_threshold and not confirmed:
            return _failure("vision.click", "The visual match confidence is low. I need confirmation before clicking.", "Low confidence click requires confirmation.", started_at)
        try:
            x_value = float(x)
            y_value = float(y)
        except (TypeError, ValueError) as exc:
            return _failure("vision.click", "Click coordinates must be numbers.", str(exc), started_at)
        if self.dry_run:
            return _success("vision.click", f"Dry run: would click {x_value:g}, {y_value:g}.", started_at)
        try:
            self._pyautogui().click(x_value, y_value)
        except BaseException as exc:
            return _failure("vision.click", f"Could not click {x_value:g}, {y_value:g}.", str(exc), started_at)
        return _success("vision.click", f"Clicked {x_value:g}, {y_value:g}.", started_at)

    def type_text(self, text: str) -> ActionResult:
        started_at = _now()
        if _contains_blocked_sensitive_text(text):
            return _failure("vision.type", "I can't type passwords or security codes, boss.", "Blocked sensitive typing action.", started_at)
        if self.dry_run:
            return _success("vision.type", "Dry run: would type text.", started_at)
        try:
            self._pyautogui().write(text, interval=0.01)
        except BaseException as exc:
            return _failure("vision.type", "Could not type with PyAutoGUI.", str(exc), started_at)
        return _success("vision.type", "Typed text with PyAutoGUI fallback.", started_at)

    def press_key(self, key: str) -> ActionResult:
        started_at = _now()
        normalized = _normalize_key(key)
        if not normalized:
            return _failure("vision.press_key", "No key was provided.", "Key cannot be empty.", started_at)
        if normalized not in ALLOWED_KEYS:
            return _failure("vision.press_key", f"Unsupported key: {normalized}.", "Unsupported key.", started_at)
        if self.dry_run:
            return _success("vision.press_key", f"Dry run: would press {normalized}.", started_at)
        try:
            self._pyautogui().press(normalized)
        except BaseException as exc:
            return _failure("vision.press_key", f"Could not press {normalized}.", str(exc), started_at)
        return _success("vision.press_key", f"Pressed {normalized}.", started_at)

    def hotkey(self, keys: Sequence[str] | str) -> ActionResult:
        started_at = _now()
        normalized = _normalize_keys(keys)
        if not normalized:
            return _failure("vision.hotkey", "No hotkey was provided.", "Hotkey cannot be empty.", started_at)
        invalid = [key for key in normalized if key not in ALLOWED_KEYS]
        if invalid:
            return _failure("vision.hotkey", f"Unsupported hotkey key: {', '.join(invalid)}.", "Unsupported hotkey key.", started_at)
        if self.dry_run:
            return _success("vision.hotkey", f"Dry run: would press {'+'.join(normalized)}.", started_at)
        try:
            self._pyautogui().hotkey(*normalized)
        except BaseException as exc:
            return _failure("vision.hotkey", f"Could not press {'+'.join(normalized)}.", str(exc), started_at)
        return _success("vision.hotkey", f"Pressed {'+'.join(normalized)}.", started_at)

    @contextmanager
    def _ephemeral_screenshot_path(self) -> Iterator[Path]:
        started = time.monotonic()
        temp = tempfile.NamedTemporaryFile(prefix="friday-vision-", suffix=".png", delete=False)
        path = Path(temp.name)
        temp.close()
        try:
            image = self._pyautogui().screenshot()
            image.save(path)
            self.screenshot_redactor(path)
            if time.monotonic() - started > self.max_screenshot_lifetime_seconds:
                raise TimeoutError("Ephemeral screenshot exceeded its maximum lifetime.")
            yield path
        finally:
            path.unlink(missing_ok=True)

    def _pyautogui(self) -> Any:
        if self.pyautogui_backend is not None:
            return self.pyautogui_backend
        import pyautogui

        return pyautogui

    def _default_locator(self, _path: Path, _description: str) -> VisionLocation | None:
        return None

    def _redact_screenshot_stub(self, _path: Path) -> None:
        return None


def _contains_blocked_sensitive_text(text: str) -> bool:
    return contains_visual_sensitive_text(text)


def _is_high_risk_click(description: str) -> bool:
    lowered = description.lower()
    return any(re.search(pattern, lowered) for pattern in HIGH_RISK_CLICK_PATTERNS)


def _normalize_keys(keys: Sequence[str] | str) -> list[str]:
    if isinstance(keys, str):
        raw_keys = re.split(r"\s*\+\s*|\s+", keys.strip())
    else:
        raw_keys = [str(key) for key in keys]
    return [key for key in (_normalize_key(key) for key in raw_keys) if key]


def _normalize_key(key: str) -> str:
    clean = _clean_text(key).replace(" ", "")
    return KEY_ALIASES.get(clean, clean)


def _clean_text(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _success(action_id: str, message: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        success=True,
        message=message,
        error="",
        started_at=started_at,
        finished_at=_now(),
        controller_used="vision",
    )


def _failure(action_id: str, message: str, error: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=action_id,
        success=False,
        message=message,
        error=error or message,
        started_at=started_at,
        finished_at=_now(),
        controller_used="vision",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
