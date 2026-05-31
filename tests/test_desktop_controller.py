from __future__ import annotations

import unittest

from friday.control.desktop_controller import DesktopController
from friday.schemas.action_result import ActionResult


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


class FakeRunner:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.calls: list[dict[str, object]] = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, command: list[str], **kwargs: object) -> FakeCompletedProcess:
        self.calls.append({"command": command, "kwargs": kwargs})
        return FakeCompletedProcess(self.returncode, self.stderr)


class FakeKeyboard:
    def __init__(self) -> None:
        self.writes: list[tuple[str, float]] = []
        self.hotkeys: list[tuple[str, ...]] = []
        self.presses: list[str] = []

    def write(self, text: str, interval: float = 0.0) -> None:
        self.writes.append((text, interval))

    def hotkey(self, *keys: str) -> None:
        self.hotkeys.append(tuple(keys))

    def press(self, key: str) -> None:
        self.presses.append(key)


class DesktopControllerTests(unittest.TestCase):
    def test_open_app_builds_safe_command(self) -> None:
        runner = FakeRunner()
        controller = DesktopController(system_name="Darwin", subprocess_runner=runner)

        result = controller.open_app("Spotify")

        self.assertIsInstance(result, ActionResult)
        self.assertTrue(result.success)
        self.assertEqual(runner.calls[0]["command"], ["open", "-a", "Spotify"])
        self.assertNotIn("shell", runner.calls[0]["kwargs"])

    def test_unknown_app_fails_cleanly(self) -> None:
        runner = FakeRunner()
        controller = DesktopController(system_name="Darwin", subprocess_runner=runner)

        result = controller.open_app("Totally Unknown App")

        self.assertFalse(result.success)
        self.assertIn("Unknown", result.error)
        self.assertEqual(runner.calls, [])

    def test_terminal_is_not_executed_without_explicit_allow(self) -> None:
        runner = FakeRunner()
        controller = DesktopController(system_name="Darwin", subprocess_runner=runner)

        result = controller.open_app("Terminal")

        self.assertFalse(result.success)
        self.assertIn("explicit allow", result.error)
        self.assertEqual(runner.calls, [])

    def test_terminal_can_be_opened_when_explicitly_allowed(self) -> None:
        runner = FakeRunner()
        controller = DesktopController(system_name="Darwin", subprocess_runner=runner, allow_terminal=True)

        result = controller.open_app("Terminal")

        self.assertTrue(result.success)
        self.assertEqual(runner.calls[0]["command"], ["open", "-a", "Terminal"])

    def test_password_typing_is_refused(self) -> None:
        keyboard = FakeKeyboard()
        controller = DesktopController(system_name="Darwin", keyboard_backend=keyboard)

        result = controller.type_text("my password is hunter2")

        self.assertFalse(result.success)
        self.assertIn("Sensitive text", result.error)
        self.assertEqual(keyboard.writes, [])

    def test_hotkeys_validate_allowed_keys(self) -> None:
        keyboard = FakeKeyboard()
        controller = DesktopController(system_name="Darwin", keyboard_backend=keyboard)

        result = controller.hotkey(["command", "l"])

        self.assertTrue(result.success)
        self.assertEqual(keyboard.hotkeys, [("command", "l")])

        invalid = controller.hotkey(["command", "power"])

        self.assertFalse(invalid.success)
        self.assertIn("Unsupported", invalid.error)
        self.assertEqual(keyboard.hotkeys, [("command", "l")])

    def test_destructive_hotkey_requires_confirmation(self) -> None:
        keyboard = FakeKeyboard()
        controller = DesktopController(system_name="Darwin", keyboard_backend=keyboard)

        result = controller.hotkey(["command", "q"])

        self.assertFalse(result.success)
        self.assertIn("requires confirmation", result.error)
        self.assertEqual(keyboard.hotkeys, [])

    def test_press_key_validates_allowed_keys(self) -> None:
        keyboard = FakeKeyboard()
        controller = DesktopController(system_name="Darwin", keyboard_backend=keyboard)

        result = controller.press_key("tab")

        self.assertTrue(result.success)
        self.assertEqual(keyboard.presses, ["tab"])


if __name__ == "__main__":
    unittest.main()
