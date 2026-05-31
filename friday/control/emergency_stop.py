from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

from friday.schemas.action_result import ActionResult


class ControlStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    WAITING_FOR_CONFIRMATION = "waiting for confirmation"
    CONTROLLING_BROWSER = "controlling browser"
    CONTROLLING_DESKTOP = "controlling desktop"
    STOPPED = "stopped"


@dataclass(frozen=True)
class EmergencyStopSnapshot:
    stop_requested: bool
    status: str
    reason: str
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stop_requested": self.stop_requested,
            "status": self.status,
            "reason": self.reason,
            "updated_at": self.updated_at.isoformat(),
        }


class EmergencyStopController:
    STOP_PATTERNS = [
        r"\bfriday\s+stop\b",
        r"\bstop\s+friday\b",
        r"^\s*stop\s*$",
        r"\bstop\s+now\b",
        r"\bstop\s+controlling\b",
        r"\bcancel\b",
        r"\babort\b",
    ]

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_requested = False
        self._status = ControlStatus.IDLE
        self._reason = ""
        self._updated_at = _now()

    def trigger(self, reason: str = "Emergency stop requested.") -> ActionResult:
        with self._lock:
            self._stop_requested = True
            self._status = ControlStatus.STOPPED
            self._reason = reason.strip() or "Emergency stop requested."
            self._updated_at = _now()
            return self.cancellation_result()

    def trigger_from_text(self, text: str) -> bool:
        if not self.is_stop_text(text):
            return False
        clean = " ".join(text.split())
        self.trigger(f"User stop phrase: {clean}")
        return True

    def trigger_from_hotkey(self, hotkey: str = "keyboard hotkey") -> ActionResult:
        return self.trigger(f"Emergency stop hotkey: {hotkey}")

    def is_stop_text(self, text: str) -> bool:
        clean = _normalize_text(text)
        return any(re.search(pattern, clean, flags=re.IGNORECASE) for pattern in self.STOP_PATTERNS)

    def is_stop_requested(self) -> bool:
        with self._lock:
            return self._stop_requested

    def clear(self) -> None:
        with self._lock:
            self._stop_requested = False
            self._status = ControlStatus.IDLE
            self._reason = ""
            self._updated_at = _now()

    def set_status(self, status: ControlStatus | str, reason: str = "") -> None:
        next_status = coerce_control_status(status)
        with self._lock:
            if self._stop_requested and self._status == ControlStatus.STOPPED and next_status != ControlStatus.STOPPED:
                return
            self._status = next_status
            self._reason = reason.strip()
            self._updated_at = _now()

    def snapshot(self) -> EmergencyStopSnapshot:
        with self._lock:
            return EmergencyStopSnapshot(
                stop_requested=self._stop_requested,
                status=self._status.value,
                reason=self._reason,
                updated_at=self._updated_at,
            )

    def cancellation_result(self, action_id: str = "emergency-stop") -> ActionResult:
        now = _now()
        with self._lock:
            error = self._reason or "Emergency stop requested."
        return ActionResult(
            action_id=action_id,
            success=False,
            message="Stopped, sir.",
            error=error,
            started_at=now,
            finished_at=_now(),
            controller_used="emergency-stop",
        )


def coerce_control_status(value: ControlStatus | str) -> ControlStatus:
    if isinstance(value, ControlStatus):
        return value
    clean = str(value).strip().lower().replace("_", " ")
    for status in ControlStatus:
        if clean == status.value:
            return status
    allowed = ", ".join(status.value for status in ControlStatus)
    raise ValueError(f"Invalid control status {value!r}. Expected one of: {allowed}.")


def _normalize_text(text: str) -> str:
    clean = text.lower().replace("’", "'")
    clean = re.sub(r"[^a-z0-9']+", " ", clean)
    return " ".join(clean.split())


def _now() -> datetime:
    return datetime.now(timezone.utc)
