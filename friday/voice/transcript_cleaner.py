from __future__ import annotations

import re


FILLERS = [
    "you know",
    "i mean",
    "i guess",
    "kind of",
    "sort of",
    "um",
    "uh",
    "umm",
    "uhh",
    "ummm",
    "uhhh",
    "er",
    "erm",
    "ah",
    "hmm",
    "hm",
    "mmm",
    "like",
    "basically",
    "literally",
    "kinda",
    "sorta",
    "please",
]

STARTING_FILLERS = [
    "okay",
    "ok",
    "alright",
    "all right",
    "so",
    "well",
    "yeah",
    "yes",
]


class TranscriptCleaner:
    def clean(self, transcript: str, verbatim: bool = False) -> str:
        raw = " ".join(transcript.strip().split())
        if not raw:
            return ""
        if verbatim:
            return raw
        text = raw.lower()
        text = text.replace("’", "'")
        text = self._apply_corrections(text)
        text = self.remove_wake_words(text)
        text = self._remove_starting_fillers(text)
        text = re.sub(r"\b(?:can you|could you|would you|will you|would you mind|i need you to|i want you to)\b", " ", text)
        for filler in sorted(FILLERS, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(filler)}\b", " ", text)
        text = re.sub(r"\b(?:uh+|um+|hm+|mm+|ah+)\b", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" ,.;:-")

    def remove_wake_words(self, transcript: str) -> str:
        return re.sub(
            r"^\s*(?:(?:hey|yo|okay|ok)\s+)?(?:fri\s*day|jarvis)\b[\s,;:\-]*",
            "",
            transcript,
            flags=re.I,
        ).strip()

    def _apply_corrections(self, text: str) -> str:
        patterns = [
            r"\b(?:actually\s+no|no\s+actually|wait\s+no|no\s+wait|scratch\s+that|instead)\b",
        ]
        for pattern in patterns:
            matches = list(re.finditer(pattern, text, re.I))
            if matches:
                text = text[matches[-1].end() :].strip()
        return text

    def _remove_starting_fillers(self, text: str) -> str:
        changed = True
        while changed:
            changed = False
            for filler in sorted(STARTING_FILLERS, key=len, reverse=True):
                updated = re.sub(rf"^\s*{re.escape(filler)}[\s,;:\-]+", "", text)
                if updated != text:
                    text = updated
                    changed = True
        return text
