from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.control.accessibility_controller import AccessibilityController
from friday.schemas.action_result import ActionResult


class FakeAccessibilityBackend:
    def __init__(
        self,
        trusted: bool = True,
        windows: list[str] | None = None,
        focused_window: str = "Main Window",
        elements: dict[tuple[str, tuple[str, ...]], str] | None = None,
        clickable: set[str] | None = None,
        typable: set[str] | None = None,
    ) -> None:
        self.trusted = trusted
        self.windows = windows or []
        self.focused_window = focused_window
        self.elements = elements or {}
        self.clickable = clickable or set()
        self.typable = typable or set()
        self.typed: list[tuple[str, str]] = []
        self.clicked: list[str] = []

    def has_permission(self) -> bool:
        return self.trusted

    def list_windows(self) -> list[str]:
        return self.windows

    def get_focused_window(self) -> str:
        return self.focused_window

    def find_element(self, label: str, roles: tuple[str, ...]) -> str:
        return self.elements.get((label, roles), "")

    def click_element(self, label: str) -> bool:
        if label not in self.clickable:
            return False
        self.clicked.append(label)
        return True

    def type_into_element(self, label: str, text: str) -> bool:
        if label not in self.typable:
            return False
        self.typed.append((label, text))
        return True


class AccessibilityControllerTests(unittest.TestCase):
    def test_missing_permissions_handled_cleanly(self) -> None:
        controller = AccessibilityController(backend=FakeAccessibilityBackend(trusted=False), system_name="Darwin")

        result = controller.list_windows()

        self.assertIsInstance(result, ActionResult)
        self.assertFalse(result.success)
        self.assertIn("Accessibility permission is required", result.message)
        self.assertIn("Accessibility permission is missing", result.error)

    def test_find_element_failure_returns_action_result(self) -> None:
        controller = AccessibilityController(backend=FakeAccessibilityBackend(trusted=True), system_name="Darwin")

        result = controller.find_button("Play")

        self.assertIsInstance(result, ActionResult)
        self.assertFalse(result.success)
        self.assertIn("couldn't find", result.message)
        self.assertEqual(result.controller_used, "accessibility")

    def test_sensitive_text_is_redacted_in_results(self) -> None:
        backend = FakeAccessibilityBackend(
            trusted=True,
            windows=[
                "Password: hunter2",
                "Account nikvik@example.com",
                "API key sk_abcdefghijklmnopqrstuvwxyz",
            ],
        )
        controller = AccessibilityController(backend=backend, system_name="Darwin")

        result = controller.list_windows()

        self.assertTrue(result.success)
        self.assertNotIn("hunter2", result.message)
        self.assertNotIn("nikvik@example.com", result.message)
        self.assertNotIn("sk_abcdefghijklmnopqrstuvwxyz", result.message)
        self.assertIn("[REDACTED]", result.message)
        self.assertIn("[REDACTED_EMAIL]", result.message)
        self.assertIn("[REDACTED_SECRET]", result.message)

    def test_no_screenshots_are_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            before = set(Path(tmp).iterdir())
            controller = AccessibilityController(
                backend=FakeAccessibilityBackend(trusted=True, windows=["Spotify"]),
                system_name="Darwin",
            )

            result = controller.list_windows()

            after = set(Path(tmp).iterdir())

        self.assertTrue(result.success)
        self.assertEqual(before, after)

    def test_click_accessibility_element_success_and_failure(self) -> None:
        backend = FakeAccessibilityBackend(trusted=True, clickable={"Play"})
        controller = AccessibilityController(backend=backend, system_name="Darwin")

        success = controller.click_accessibility_element("Play")
        failure = controller.click_accessibility_element("Pause")

        self.assertTrue(success.success)
        self.assertEqual(backend.clicked, ["Play"])
        self.assertFalse(failure.success)
        self.assertIn("Could not find", failure.message)

    def test_type_into_accessibility_element_success_and_sensitive_refusal(self) -> None:
        backend = FakeAccessibilityBackend(trusted=True, typable={"Search"})
        controller = AccessibilityController(backend=backend, system_name="Darwin")

        success = controller.type_into_accessibility_element("Search", "Lil Baby")
        refused = controller.type_into_accessibility_element("Search", "my password is hunter2")

        self.assertTrue(success.success)
        self.assertEqual(backend.typed, [("Search", "Lil Baby")])
        self.assertFalse(refused.success)
        self.assertIn("Sensitive text", refused.error)


if __name__ == "__main__":
    unittest.main()
