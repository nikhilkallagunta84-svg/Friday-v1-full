from __future__ import annotations

import unittest

from friday.voice.stop_phrase_detector import StopPhraseDetector


class StopPhraseDetectorTests(unittest.TestCase):
    def test_gratitude_returns_idle_category(self) -> None:
        detector = StopPhraseDetector()

        self.assertEqual(detector.category("Thanks Friday"), "gratitude")

    def test_tts_interrupt_phrase_is_detected(self) -> None:
        detector = StopPhraseDetector()

        self.assertTrue(detector.is_tts_interrupt("Friday stop"))

    def test_cancel_phrase_is_detected(self) -> None:
        detector = StopPhraseDetector()

        self.assertEqual(detector.category("never mind"), "cancel")

    def test_session_stop_variants_are_detected(self) -> None:
        detector = StopPhraseDetector()

        self.assertEqual(detector.category("you're good Friday"), "gratitude")
        self.assertEqual(detector.category("youre good Friday"), "gratitude")
        self.assertEqual(detector.category("stop listening Friday"), "cancel")
        self.assertEqual(detector.category("sleep Friday"), "night")

    def test_cancel_phrases_interrupt_tts_too(self) -> None:
        detector = StopPhraseDetector()

        self.assertTrue(detector.is_tts_interrupt("cancel"))
        self.assertTrue(detector.is_tts_interrupt("thanks Friday"))


if __name__ == "__main__":
    unittest.main()
