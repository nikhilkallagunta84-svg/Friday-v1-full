from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List

from friday.input_filter import ProcessedInput
from friday.memory.action_logger import ActionLogger
from friday.memory.task_history import TaskHistory, TaskLogEntry


@dataclass(frozen=True)
class MemoryItem:
    created_at: float
    source: str
    cleaned_input: str
    objects: List[str]


class ShortTermMemory:
    def __init__(self, ttl_seconds: int = 1800, max_items: int = 24) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: Deque[MemoryItem] = deque(maxlen=max_items)

    def remember(self, source: str, processed: ProcessedInput) -> None:
        self._expire()
        self._items.append(
            MemoryItem(
                created_at=time.time(),
                source=source,
                cleaned_input=processed.cleaned,
                objects=processed.object_entities,
            )
        )

    def context_lines(self) -> List[str]:
        self._expire()
        lines: List[str] = []
        for item in list(self._items)[-8:]:
            object_text = ", ".join(item.objects) if item.objects else "none"
            lines.append(f"{item.source}: {item.cleaned_input} | objects: {object_text}")
        return lines

    def last_object(self) -> str:
        self._expire()
        for item in reversed(self._items):
            if item.objects:
                return item.objects[-1]
        return ""

    def resolve_context_reference(self, cleaned_input: str) -> str:
        if any(token in cleaned_input.split() for token in {"it", "that", "this"}):
            last_object = self.last_object()
            if last_object:
                return f"{cleaned_input} (context reference: {last_object})"
        return cleaned_input

    def _expire(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        while self._items and self._items[0].created_at < cutoff:
            self._items.popleft()


__all__ = [
    "ActionLogger",
    "MemoryItem",
    "ShortTermMemory",
    "TaskHistory",
    "TaskLogEntry",
]
