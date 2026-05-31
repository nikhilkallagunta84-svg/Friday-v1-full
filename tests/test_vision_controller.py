from __future__ import annotations

from pathlib import Path
import unittest

from friday.control.vision_controller import VisionController, VisionLocation
from friday.schemas.action_result import ActionResult


class FakeScreenshot:
    def __init__(self, owner: "FakePyAutoGUI") -> None:
        self.owner = owner

    def save(self, path: Path | str) -> None:
        clean_path = Path(path)
        clean_path.write_bytes(b"fake screenshot")
        self.owner.saved_paths.append(clean_path)


class FakePyAutoGUI:
    def __init__(self) -> None:
        self.saved_paths: list[Path] = []
        self.clicks: list[tuple[float, float]] = []
        self.writes: list[str] = []
        self.presses: list[str] = []
        self.hotkeys: list[tuple[str, ...]] = []

    def screenshot(self) -> FakeScreenshot:
        return FakeScreenshot(self)

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    def write(self, text: str, interval: float = 0.0) -> None:
        self.writes.append(text)

    def press(self, key: str) -> None:
        self.presses.append(key)

    def hotkey(self, *keys: str) -> None:
        self.hotkeys.append(tuple(keys))


class VisionControllerTests(unittest.TestCase):
    def test_temp_screenshot_file_is_deleted(self) -> None:
        fake = FakePyAutoGUI()
        controller = VisionController(pyautogui_backend=fake)

        result = controller.take_ephemeral_screenshot()

        self.assertIsInstance(result, ActionResult)
        self.assertTrue(result.success)
        self.assertEqual(len(fake.saved_paths), 1)
        self.assertFalse(fake.saved_paths[0].exists())

    def test_low_confidence_asks_for_confirmation(self) -> None:
        fake = FakePyAutoGUI()

        def locator(_path: Path, description: str) -> VisionLocation:
            return VisionLocation(10, 20, 0.35, description)

        controller = VisionController(pyautogui_backend=fake, locator_backend=locator, confidence_threshold=0.75)

        result = controller.locate_text_or_element("blue search button")

        self.assertFalse(result.success)
        self.assertIn("confirmation", result.message)
        self.assertIn("Low confidence", result.error)
        self.assertFalse(fake.saved_paths[0].exists())

    def test_high_risk_click_requires_confirmation(self) -> None:
        fake = FakePyAutoGUI()
        controller = VisionController(pyautogui_backend=fake)

        result = controller.click_coordinates(100, 200, description="send button", confidence=0.95)

        self.assertFalse(result.success)
        self.assertIn("High-risk", result.error)
        self.assertEqual(fake.clicks, [])

    def test_blocked_sensitive_action_refuses(self) -> None:
        fake = FakePyAutoGUI()
        controller = VisionController(pyautogui_backend=fake)

        result = controller.type_text("my password is hunter2")

        self.assertFalse(result.success)
        self.assertIn("Blocked sensitive", result.error)
        self.assertEqual(fake.writes, [])

    def test_failed_locate_returns_action_result_not_exception(self) -> None:
        fake = FakePyAutoGUI()

        def failing_locator(_path: Path, _description: str) -> VisionLocation:
            raise RuntimeError("locator failed")

        controller = VisionController(pyautogui_backend=fake, locator_backend=failing_locator)

        result = controller.locate_text_or_element("play button")

        self.assertIsInstance(result, ActionResult)
        self.assertFalse(result.success)
        self.assertIn("locator failed", result.error)
        self.assertFalse(fake.saved_paths[0].exists())

    def test_dry_run_does_not_click_or_type(self) -> None:
        fake = FakePyAutoGUI()
        controller = VisionController(pyautogui_backend=fake, dry_run=True)

        click_result = controller.click_coordinates(5, 8, description="play button", confidence=0.99)
        type_result = controller.type_text("hello")

        self.assertTrue(click_result.success)
        self.assertTrue(type_result.success)
        self.assertEqual(fake.clicks, [])
        self.assertEqual(fake.writes, [])


if __name__ == "__main__":
    unittest.main()
