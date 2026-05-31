from __future__ import annotations

from dataclasses import dataclass

from friday.voice.stop_phrase_detector import StopPhraseDetector
from friday.voice.transcript_cleaner import TranscriptCleaner
from friday.voice.turn_manager import TurnManager
from friday.voice.wake_word import WakeWordManager


@dataclass(frozen=True)
class VoicePipelineResult:
    activated: bool
    command_text: str
    stop_category: str
    should_process: bool


class VoicePipeline:
    def __init__(
        self,
        wake_word: WakeWordManager,
        cleaner: TranscriptCleaner,
        stop_phrases: StopPhraseDetector,
        turn_manager: TurnManager,
    ) -> None:
        self.wake_word = wake_word
        self.cleaner = cleaner
        self.stop_phrases = stop_phrases
        self.turn_manager = turn_manager

    def process_transcript(self, transcript: str, currently_spoken_text: str | None = None) -> VoicePipelineResult:
        stop_category = self.stop_phrases.category(transcript)
        if stop_category:
            self.turn_manager.return_to_idle()
            return VoicePipelineResult(False, "", stop_category, True)
        wake = self.wake_word.detect_text(transcript, currently_spoken_text)
        if not wake.detected and not self.turn_manager.session_mode:
            return VoicePipelineResult(False, "", "", False)
        command = wake.trailing_text if wake.detected else transcript
        cleaned = self.cleaner.clean(command)
        if wake.detected:
            self.turn_manager.enter_command_listening() if not cleaned else self.turn_manager.set_state("THINKING")
        return VoicePipelineResult(wake.detected, cleaned, "", bool(cleaned))
