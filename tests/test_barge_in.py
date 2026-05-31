from __future__ import annotations

import unittest

from friday.voice.echo_guard import EchoGuard
from friday.voice.stop_phrase_detector import StopPhraseDetector


class BargeInTests(unittest.TestCase):
    def test_stop_talking_is_interrupt(self) -> None:
        detector = StopPhraseDetector()

        self.assertTrue(detector.is_tts_interrupt("stop talking"))

    def test_echo_guard_suppresses_own_speech(self) -> None:
        guard = EchoGuard()

        self.assertTrue(guard.is_echo("my name is friday", "Hello boss. My name is FRIDAY."))


if __name__ == "__main__":
    unittest.main()
