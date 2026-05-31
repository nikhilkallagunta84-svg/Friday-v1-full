from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from friday.voice.transcript_cleaner import TranscriptCleaner


FILLER_WORDS = {
    "um",
    "uh",
    "umm",
    "uhh",
    "like",
    "please",
    "basically",
    "actually",
    "literally",
    "just",
    "kind of",
    "sort of",
}

ACTION_WORDS = {
    "open",
    "close",
    "restart",
    "focus",
    "switch",
    "check",
    "show",
    "run",
    "start",
    "stop",
    "install",
    "create",
    "write",
    "append",
    "read",
    "summarize",
    "send",
    "search",
    "draft",
    "explain",
    "plan",
    "build",
    "launch",
    "mute",
    "adjust",
    "toggle",
    "add",
    "complete",
    "finish",
    "done",
}


@dataclass(frozen=True)
class ProcessedInput:
    raw: str
    cleaned: str
    action_keywords: List[str]
    object_entities: List[str]


class InputProcessor:
    def __init__(self) -> None:
        self.cleaner = TranscriptCleaner()

    def normalize(self, raw_input: str) -> ProcessedInput:
        raw = " ".join(raw_input.strip().split())
        text = self.cleaner.clean(raw)
        action_keywords = [word for word in text.split() if word in ACTION_WORDS]
        object_entities = self._extract_objects(text, action_keywords)
        return ProcessedInput(
            raw=raw,
            cleaned=text or raw.lower(),
            action_keywords=action_keywords,
            object_entities=object_entities,
        )

    def _extract_objects(self, cleaned: str, actions: List[str]) -> List[str]:
        if not cleaned:
            return []
        words = cleaned.split()
        objects: List[str] = []
        for action in actions:
            try:
                index = words.index(action)
            except ValueError:
                continue
            tail = words[index + 1 :]
            if tail:
                candidate = " ".join(tail[:6]).strip(" ,.")
                if candidate and candidate not in objects:
                    objects.append(candidate)
        return objects
