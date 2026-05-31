from __future__ import annotations

import threading
import time
from dataclasses import dataclass


MUTED = "muted"
ACTIVE = "active"
TONES = {"formal", "neutral", "light-hearted", "professional"}


@dataclass(frozen=True)
class StateSnapshot:
    mode: str
    active_session: bool
    tone: str
    last_active_at: float


class StateManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mode = MUTED
        self._active_session = False
        self._tone = "neutral"
        self._last_active_at = time.time()

    def activate(self) -> None:
        with self._lock:
            self._mode = ACTIVE
            self._last_active_at = time.time()

    def mute(self) -> None:
        with self._lock:
            self._mode = MUTED
            self._active_session = False
            self._last_active_at = time.time()

    def begin_session(self) -> bool:
        with self._lock:
            if self._active_session:
                return False
            self._active_session = True
            self._mode = ACTIVE
            self._last_active_at = time.time()
            return True

    def end_session(self) -> None:
        with self._lock:
            self._active_session = False
            self._mode = MUTED
            self._last_active_at = time.time()

    def set_tone(self, tone: str) -> str:
        normalized = tone.strip().lower()
        if normalized not in TONES:
            raise ValueError(f"Unsupported tone: {tone}")
        with self._lock:
            self._tone = normalized
            self._last_active_at = time.time()
            return self._tone

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return StateSnapshot(
                mode=self._mode,
                active_session=self._active_session,
                tone=self._tone,
                last_active_at=self._last_active_at,
            )
