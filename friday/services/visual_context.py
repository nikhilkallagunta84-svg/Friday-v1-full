from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class VisualContext:
    file_name: str
    mime_type: str
    image_data_urls: List[str]
    frame_labels: List[str]
    analysis: str
    vision_model: str
    created_at: float


class VisualContextManager:
    def __init__(self, ttl_seconds: float = 1800.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._context: VisualContext | None = None
        self._lock = threading.RLock()

    def store(
        self,
        file_name: str,
        mime_type: str,
        image_data_urls: List[str],
        frame_labels: List[str],
        analysis: str,
        vision_model: str,
    ) -> VisualContext:
        with self._lock:
            context = VisualContext(
                file_name=file_name,
                mime_type=mime_type,
                image_data_urls=list(image_data_urls),
                frame_labels=list(frame_labels),
                analysis=analysis,
                vision_model=vision_model,
                created_at=time.time(),
            )
            self._context = context
            return context

    def current(self) -> VisualContext | None:
        with self._lock:
            if not self._context:
                return None
            if time.time() - self._context.created_at > self.ttl_seconds:
                self._context = None
                return None
            return self._context

    def clear(self) -> None:
        with self._lock:
            self._context = None

    def should_use_for_prompt(self, prompt: str) -> bool:
        if not self.current():
            return False
        text = " ".join(prompt.lower().strip().split())
        if not text:
            return False
        if self._is_unrelated_command(text):
            return False
        if text in {"solve", "solve it", "answer", "answer it", "read", "read it", "explain", "explain it", "continue", "more", "tell me more"}:
            return True
        visual_terms = (
            "image",
            "screenshot",
            "screen shot",
            "video",
            "file",
            "upload",
            "picture",
            "photo",
            "frame",
            "clip",
            "diagram",
            "worksheet",
            "problem",
            "question",
            "equation",
            "answer",
        )
        if any(term in text for term in visual_terms):
            return True
        if re.search(r"\b(solve|answer|explain|summarize|describe|read|transcribe|translate|identify|find|check|grade)\b", text):
            return True
        pronoun_reference = re.search(r"\b(it|this|that|these|those|there)\b", text)
        question_or_followup = re.search(r"^(?:what|which|where|why|how|can|could|does|is|are|tell|show|help|make)\b", text)
        return bool(pronoun_reference and question_or_followup)

    def build_follow_up_prompt(self, prompt: str) -> str:
        context = self.current()
        if not context:
            return prompt
        prior = " ".join(context.analysis.split())
        return (
            f"The user is asking a follow-up about the previously uploaded file. "
            f"Previous visual analysis: {prior} "
            f"Follow-up request: {prompt}"
        )

    def _is_unrelated_command(self, text: str) -> bool:
        unrelated_patterns = [
            r"^(?:friday\s+)?(?:open|launch|start|close|quit|switch|search|google|look up|click|type|press|scroll|run|install|delete|send|draft|control|automate)\b",
            r"^(?:friday\s+)?(?:status|system status|check status|set tone|test tts|tts|voice|chrome mic)\b",
            r"^(?:what|when)\s+(?:time|date)\b",
            r"\b(?:weather|temperature|forecast)\b",
            r"^(?:thanks|thank you|cancel|nevermind|never mind|stop listening|go idle|sleep friday)\b",
        ]
        return any(re.search(pattern, text) for pattern in unrelated_patterns)
