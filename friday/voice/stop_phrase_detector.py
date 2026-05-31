from __future__ import annotations

import re
from typing import Sequence

_CLEAN_RE = re.compile(r"[^a-z0-9']+")


def _normalize(text: str) -> str:
    clean = text.lower().replace("’", "'")
    clean = _CLEAN_RE.sub(" ", clean)
    return " ".join(clean.split())


def _compile_phrases(phrases: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(rf"\b{re.escape(_normalize(p))}\b") for p in phrases]


GRATITUDE_STOP_PHRASES = [
    "thanks friday",
    "thank you friday",
    "appreciate it friday",
    "that's all friday",
    "thats all friday",
    "that is all friday",
    "you're good friday",
    "youre good friday",
    "good job friday",
]

NIGHT_STOP_PHRASES = ["good night friday", "night friday", "sleep friday", "go to sleep friday"]

CANCEL_STOP_PHRASES = [
    "cancel",
    "abort",
    "nevermind",
    "never mind",
    "stop listening",
    "stop listening friday",
    "go idle",
    "go idle friday",
    "pause listening",
]

TTS_INTERRUPT_PHRASES = [
    "stop",
    "stop talking",
    "stop speaking",
    "pause",
    "quiet",
    "shut up",
    "that's enough",
    "thats enough",
    "friday stop",
    "friday pause",
    "quiet friday",
    "shut up friday",
]

_CATEGORIES: list[tuple[str, list[re.Pattern[str]]]] = [
    ("gratitude", _compile_phrases(GRATITUDE_STOP_PHRASES)),
    ("night", _compile_phrases(NIGHT_STOP_PHRASES)),
    ("cancel", _compile_phrases(CANCEL_STOP_PHRASES)),
    ("interrupt", _compile_phrases(TTS_INTERRUPT_PHRASES)),
]


class StopPhraseDetector:
    def category(self, text: str) -> str:
        clean = _normalize(text)
        for name, patterns in _CATEGORIES:
            if any(p.search(clean) for p in patterns):
                return name
        return ""

    def is_stop_phrase(self, text: str) -> bool:
        return bool(self.category(text))

    def is_tts_interrupt(self, text: str) -> bool:
        return self.category(text) in {"interrupt", "cancel", "gratitude", "night"}
