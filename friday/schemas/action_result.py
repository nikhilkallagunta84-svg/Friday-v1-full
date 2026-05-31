from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from friday.schemas.screen_action import coerce_datetime


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    success: bool
    message: str
    error: str
    controller_used: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be a non-empty string.")
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string.")
        if not isinstance(self.error, str):
            raise TypeError("error must be a string.")
        if not isinstance(self.controller_used, str) or not self.controller_used.strip():
            raise ValueError("controller_used must be a non-empty string.")

        started_at = coerce_datetime(self.started_at, "started_at")
        finished_at = coerce_datetime(self.finished_at, "finished_at")
        if finished_at < started_at:
            raise ValueError("finished_at cannot be earlier than started_at.")
        if self.success and self.error.strip():
            raise ValueError("successful action results must not include an error.")
        if not self.success and not self.error.strip():
            raise ValueError("failed action results must include an error.")

        object.__setattr__(self, "action_id", self.action_id.strip())
        object.__setattr__(self, "controller_used", self.controller_used.strip())
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ActionResult":
        return cls(
            action_id=payload["action_id"],
            success=payload["success"],
            message=payload["message"],
            error=payload["error"],
            controller_used=payload["controller_used"],
            started_at=payload["started_at"],
            finished_at=payload["finished_at"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "success": self.success,
            "message": self.message,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "controller_used": self.controller_used,
        }
