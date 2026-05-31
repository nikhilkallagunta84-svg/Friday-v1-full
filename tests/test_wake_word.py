from __future__ import annotations

import unittest

from friday.voice.wake_word import WakeWordManager


class WakeWordManagerTests(unittest.TestCase):
    def test_wake_word_preserves_trailing_command(self) -> None:
        manager = WakeWordManager({"cooldown_ms": 0})
        result = manager.detect_text("Yo Friday open Spotify")

        self.assertTrue(result.detected)
        self.assertEqual(result.trailing_text, "open spotify")

    def test_jarvis_optional_wake_word(self) -> None:
        manager = WakeWordManager({"cooldown_ms": 0})
        result = manager.detect_text("Hey Jarvis search AI agents")

        self.assertTrue(result.detected)
        self.assertEqual(result.trailing_text, "search ai agents")

    def test_echo_text_does_not_wake(self) -> None:
        manager = WakeWordManager({"cooldown_ms": 0})
        result = manager.detect_text("Hello boss my name is Friday", "Hello boss. My name is FRIDAY.")

        self.assertFalse(result.detected)


if __name__ == "__main__":
    unittest.main()
