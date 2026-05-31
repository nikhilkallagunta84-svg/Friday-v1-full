from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict

from friday.voice.echo_guard import EchoGuard


@dataclass(frozen=True)
class WakeWordResult:
    detected: bool
    phrase: str
    trailing_text: str
    confidence: float


class WakeWordManager:
    def __init__(self, config: Dict[str, Any] | None = None, echo_guard: EchoGuard | None = None) -> None:
        values = config or {}
        alternates = values.get("alternates", ["hey friday", "yo friday", "okay friday", "jarvis", "hey jarvis"])
        self.wake_words = [str(values.get("primary") or "friday"), *[str(item) for item in alternates if str(item).strip()]]
        self.cooldown_seconds = float(values.get("cooldown_ms", 1500)) / 1000.0
        self.echo_guard = echo_guard or EchoGuard()
        self._last_detection_at = 0.0
        self._pattern = self._build_pattern(self.wake_words)

    def warmup(self) -> None:
        return

    def detect_text(self, transcript: str, spoken_text: str | None = None) -> WakeWordResult:
        clean = " ".join(transcript.lower().split())
        if not clean:
            return WakeWordResult(False, "", "", 0.0)
        if self.echo_guard.is_echo(clean, spoken_text):
            return WakeWordResult(False, "", "", 0.0)
        now = time.monotonic()
        if now - self._last_detection_at < self.cooldown_seconds:
            return WakeWordResult(False, "", "", 0.0)
        match = self._pattern.search(clean)
        if not match:
            return WakeWordResult(False, "", "", 0.0)
        self._last_detection_at = now
        trailing = clean[match.end() :].strip(" ,;:-")
        return WakeWordResult(True, match.group(0), trailing, 1.0)

    def strip_wake_word(self, transcript: str) -> str:
        match = self._pattern.search(transcript.lower())
        if not match:
            return transcript.strip()
        return transcript[match.end() :].strip(" ,;:-")

    def _build_pattern(self, wake_words: list[str]) -> re.Pattern[str]:
        pieces = []
        for phrase in sorted(set(wake_words), key=len, reverse=True):
            normalized = re.sub(r"\s+", r"\\s+", re.escape(phrase.lower()))
            normalized = normalized.replace("fri\\s+day", r"fri\s*day")
            pieces.append(normalized)
        return re.compile(r"\b(?:" + "|".join(pieces) + r")\b", re.I)
