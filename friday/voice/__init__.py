from __future__ import annotations

from typing import Any


__all__ = [
    "EchoGuard",
    "GreetingEngine",
    "MacOSTTS",
    "MicrophoneStream",
    "PersonalityEngine",
    "STTManager",
    "STTResult",
    "StopPhraseDetector",
    "TTSManager",
    "TTSStatus",
    "TurnManager",
    "TurnState",
    "VADManager",
    "VADSettings",
    "VoiceStatus",
    "VoicePipeline",
    "VoicePipelineResult",
    "WakeWordManager",
    "WakeWordResult",
    "WakeWordService",
]


def __getattr__(name: str) -> Any:
    if name == "EchoGuard":
        from friday.voice.echo_guard import EchoGuard

        return EchoGuard
    if name == "GreetingEngine":
        from friday.voice.greeting_engine import GreetingEngine

        return GreetingEngine
    if name == "PersonalityEngine":
        from friday.voice.personality_engine import PersonalityEngine

        return PersonalityEngine
    if name == "MicrophoneStream":
        from friday.voice.microphone_stream import MicrophoneStream

        return MicrophoneStream
    if name in {"STTManager", "STTResult"}:
        from friday.voice.stt_manager import STTManager, STTResult

        return {"STTManager": STTManager, "STTResult": STTResult}[name]
    if name == "StopPhraseDetector":
        from friday.voice.stop_phrase_detector import StopPhraseDetector

        return StopPhraseDetector
    if name in {"MacOSTTS", "TTSManager", "TTSStatus"}:
        from friday.voice.tts_manager import MacOSTTS, TTSManager, TTSStatus

        return {"MacOSTTS": MacOSTTS, "TTSManager": TTSManager, "TTSStatus": TTSStatus}[name]
    if name in {"TurnManager", "TurnState"}:
        from friday.voice.turn_manager import TurnManager, TurnState

        return {"TurnManager": TurnManager, "TurnState": TurnState}[name]
    if name in {"VADManager", "VADSettings"}:
        from friday.voice.vad_manager import VADManager, VADSettings

        return {"VADManager": VADManager, "VADSettings": VADSettings}[name]
    if name in {"VoicePipeline", "VoicePipelineResult"}:
        from friday.voice.voice_pipeline import VoicePipeline, VoicePipelineResult

        return {"VoicePipeline": VoicePipeline, "VoicePipelineResult": VoicePipelineResult}[name]
    if name in {"WakeWordManager", "WakeWordResult"}:
        from friday.voice.wake_word import WakeWordManager, WakeWordResult

        return {"WakeWordManager": WakeWordManager, "WakeWordResult": WakeWordResult}[name]
    if name in {"VoiceStatus", "WakeWordService"}:
        from friday.voice.wake_word_service import VoiceStatus, WakeWordService

        return {"VoiceStatus": VoiceStatus, "WakeWordService": WakeWordService}[name]
    raise AttributeError(name)
