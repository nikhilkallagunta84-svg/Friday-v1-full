from __future__ import annotations

import unittest

from friday.voice.stop_phrase_detector import StopPhraseDetector
from friday.voice.transcript_cleaner import TranscriptCleaner
from friday.voice.turn_manager import TurnManager, TurnState
from friday.voice.voice_pipeline import VoicePipeline
from friday.voice.wake_word import WakeWordManager


class VoicePipelineTests(unittest.TestCase):
    def test_random_speech_is_ignored_in_wake_mode(self) -> None:
        pipeline = VoicePipeline(WakeWordManager({"cooldown_ms": 0}), TranscriptCleaner(), StopPhraseDetector(), TurnManager())

        result = pipeline.process_transcript("random room speech")

        self.assertFalse(result.should_process)

    def test_wake_and_command_in_one_sentence(self) -> None:
        turn_manager = TurnManager()
        pipeline = VoicePipeline(WakeWordManager({"cooldown_ms": 0}), TranscriptCleaner(), StopPhraseDetector(), turn_manager)

        result = pipeline.process_transcript("Friday uh can you open YouTube")

        self.assertTrue(result.activated)
        self.assertEqual(result.command_text, "open youtube")
        self.assertEqual(turn_manager.state, TurnState.THINKING)

    def test_stop_phrase_returns_idle(self) -> None:
        turn_manager = TurnManager(TurnState.SESSION_LISTENING, session_mode=True)
        pipeline = VoicePipeline(WakeWordManager({"cooldown_ms": 0}), TranscriptCleaner(), StopPhraseDetector(), turn_manager)

        result = pipeline.process_transcript("thanks friday")

        self.assertEqual(result.stop_category, "gratitude")
        self.assertEqual(turn_manager.state, TurnState.IDLE_WAKE_LISTENING)


if __name__ == "__main__":
    unittest.main()
