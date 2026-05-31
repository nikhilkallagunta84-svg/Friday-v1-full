from __future__ import annotations

import hashlib
import re
import threading

from friday.config import PersonalityConfig


class PersonalityEngine:
    def __init__(self, config: PersonalityConfig) -> None:
        self.config = config
        self._pick_lock = threading.Lock()
        self._pick_count = 0

    def polish(self, text: str, context: str = "default") -> str:
        clean = " ".join(text.split()).strip()
        if self._looks_internal(clean):
            return "I hit an internal issue, boss."
        if context == "wake":
            return self.pick(["Yes boss?", "I'm listening, sir.", "Go ahead, boss."])
        if context == "gratitude":
            return self.pick(["Anytime, sir.", "Of course, boss.", "Always, boss."])
        if context == "night":
            return self.pick(["Good night, sir.", "Rest easy, boss."])
        if context == "cancel":
            return self.pick(["Canceled, boss.", "Canceled, sir.", "No problem, boss."])
        if context == "task_start":
            return self.pick(["On it, boss.", "Right away, sir.", "Absolutely, boss.", "Already moving, boss."])
        if not clean:
            return clean
        if context == "task_complete":
            if clean.lower() not in {"done", "done.", "handled", "handled."}:
                return clean
            return self.pick(["Done, boss.", "Handled, sir.", "Handled.", "All set, boss."])
        return clean

    def pick(self, options: list[str]) -> str:
        if not options:
            return ""
        with self._pick_lock:
            self._pick_count += 1
            index_seed = self._pick_count
        digest = hashlib.sha1(f"{index_seed}|{'|'.join(options)}".encode("utf-8")).digest()
        return options[digest[0] % len(options)]

    def _looks_internal(self, text: str) -> bool:
        stripped = text.strip()
        if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
            return True
        return bool(re.search(r"\b(traceback|stack trace|system prompt|api[_ -]?key|password=|secret=)\b", stripped, re.I))
