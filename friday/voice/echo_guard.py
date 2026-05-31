from __future__ import annotations

import re
from difflib import SequenceMatcher


class EchoGuard:
    def __init__(self, similarity_threshold: float = 0.75) -> None:
        self.similarity_threshold = similarity_threshold

    def is_echo(self, transcript: str, spoken_text: str | None) -> bool:
        if not transcript or not spoken_text:
            return False
        clean_transcript = self._normalize(transcript)
        clean_spoken = self._normalize(spoken_text)
        if not clean_transcript or not clean_spoken:
            return False
        if clean_transcript in clean_spoken:
            return True
        ratio = SequenceMatcher(None, clean_transcript, clean_spoken).ratio()
        return ratio >= self.similarity_threshold

    def _normalize(self, text: str) -> str:
        clean = text.lower()
        clean = re.sub(r"[^a-z0-9]+", " ", clean)
        return " ".join(clean.split())
