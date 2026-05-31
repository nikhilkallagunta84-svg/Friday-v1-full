from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class Event:
    id: int
    kind: str
    payload: Dict[str, Any]
    created_at: float


class EventBus:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._events: List[Event] = []
        self._next_id = 1

    def publish(self, kind: str, payload: Dict[str, Any]) -> Event:
        with self._condition:
            event = Event(self._next_id, kind, payload, time.time())
            self._next_id += 1
            self._events.append(event)
            if len(self._events) > 500:
                self._events = self._events[-500:]
            self._condition.notify_all()
            return event

    def wait_after(self, last_seen_id: int, timeout: float = 20.0) -> List[Event]:
        deadline = time.time() + timeout
        with self._condition:
            while True:
                events = [event for event in self._events if event.id > last_seen_id]
                if events:
                    return events
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._condition.wait(remaining)

    def latest(self) -> List[Event]:
        with self._condition:
            return list(self._events)
