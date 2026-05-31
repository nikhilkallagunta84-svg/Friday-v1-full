"""Schemas for FRIDAY's phone-call assistant.

Mirrors `screen_action.py` conventions: frozen dataclasses, enum coercion,
ISO-datetime parsing, and `to_dict`/`from_dict` round-trips that survive JSONL
serialization in `logs/phone-calls.jsonl`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class CallStatus(str, Enum):
    PLANNED = "planned"
    DIALING = "dialing"
    RINGING = "ringing"
    CONNECTED = "connected"
    TALKING = "talking"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def coerce_call_status(value: Any) -> CallStatus:
    if isinstance(value, CallStatus):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        for status in CallStatus:
            if normalized == status.value:
                return status
    allowed = ", ".join(status.value for status in CallStatus)
    raise ValueError(f"Invalid call status {value!r}. Expected one of: {allowed}.")


def _coerce_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO datetime string.") from exc
    else:
        raise TypeError(f"{field_name} must be a datetime or ISO datetime string.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _str_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list of strings.")
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass(frozen=True)
class CallBrief:
    """Structured plan for a single outbound call."""

    call_id: str
    recipient_name: str
    recipient_number: str
    objective: str
    talking_points: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    max_minutes: int = 5
    persona: str = "respectful"
    source_command: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must be a non-empty string.")
        if not isinstance(self.recipient_name, str) or not self.recipient_name.strip():
            raise ValueError("recipient_name must be a non-empty string.")
        if not isinstance(self.recipient_number, str):
            raise TypeError("recipient_number must be a string (empty allowed for planner fallback).")
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("objective must be a non-empty string.")
        if not isinstance(self.persona, str) or not self.persona.strip():
            raise ValueError("persona must be a non-empty string.")
        if not isinstance(self.max_minutes, int) or self.max_minutes <= 0 or self.max_minutes > 60:
            raise ValueError("max_minutes must be an integer between 1 and 60.")
        # Normalise list fields without mutating the frozen instance.
        object.__setattr__(self, "talking_points", _str_list(self.talking_points, "talking_points"))
        object.__setattr__(self, "success_criteria", _str_list(self.success_criteria, "success_criteria"))
        object.__setattr__(self, "created_at", _coerce_datetime(self.created_at, "created_at"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "recipient_name": self.recipient_name,
            "recipient_number": self.recipient_number,
            "objective": self.objective,
            "talking_points": list(self.talking_points),
            "success_criteria": list(self.success_criteria),
            "max_minutes": self.max_minutes,
            "persona": self.persona,
            "source_command": self.source_command,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CallBrief":
        return cls(
            call_id=str(payload.get("call_id", "")),
            recipient_name=str(payload.get("recipient_name", "")),
            recipient_number=str(payload.get("recipient_number", "")),
            objective=str(payload.get("objective", "")),
            talking_points=list(payload.get("talking_points") or []),
            success_criteria=list(payload.get("success_criteria") or []),
            max_minutes=int(payload.get("max_minutes", 5)),
            persona=str(payload.get("persona", "respectful")),
            source_command=str(payload.get("source_command", "")),
            created_at=payload.get("created_at", datetime.now(timezone.utc)),
        )


@dataclass(frozen=True)
class CallTurn:
    """One exchange in a call's transcript."""

    speaker: str  # "friday", "recipient", or "system"
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.speaker not in {"friday", "recipient", "system"}:
            raise ValueError("speaker must be one of: friday, recipient, system.")
        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")
        object.__setattr__(self, "timestamp", _coerce_datetime(self.timestamp, "timestamp"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CallTurn":
        return cls(
            speaker=str(payload.get("speaker", "system")),
            text=str(payload.get("text", "")),
            timestamp=payload.get("timestamp", datetime.now(timezone.utc)),
        )


@dataclass(frozen=True)
class CallResult:
    """Final record of a completed (or failed) call."""

    call_id: str
    status: CallStatus | str
    transcript: List[CallTurn] = field(default_factory=list)
    summary: str = ""
    outcome: str = ""
    follow_ups: List[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must be a non-empty string.")
        object.__setattr__(self, "status", coerce_call_status(self.status))
        object.__setattr__(self, "follow_ups", _str_list(self.follow_ups, "follow_ups"))
        object.__setattr__(self, "started_at", _coerce_datetime(self.started_at, "started_at"))
        object.__setattr__(self, "ended_at", _coerce_datetime(self.ended_at, "ended_at"))
        # Coerce transcript items to CallTurn if dicts were passed in.
        coerced_turns: List[CallTurn] = []
        for turn in self.transcript:
            if isinstance(turn, CallTurn):
                coerced_turns.append(turn)
            elif isinstance(turn, dict):
                coerced_turns.append(CallTurn.from_dict(turn))
            else:
                raise TypeError("transcript entries must be CallTurn or dict.")
        object.__setattr__(self, "transcript", coerced_turns)

    def to_dict(self) -> Dict[str, Any]:
        status_value = self.status.value if isinstance(self.status, CallStatus) else str(self.status)
        return {
            "call_id": self.call_id,
            "status": status_value,
            "transcript": [turn.to_dict() for turn in self.transcript],
            "summary": self.summary,
            "outcome": self.outcome,
            "follow_ups": list(self.follow_ups),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CallResult":
        return cls(
            call_id=str(payload.get("call_id", "")),
            status=payload.get("status", CallStatus.PLANNED),
            transcript=list(payload.get("transcript") or []),
            summary=str(payload.get("summary", "")),
            outcome=str(payload.get("outcome", "")),
            follow_ups=list(payload.get("follow_ups") or []),
            started_at=payload.get("started_at", datetime.now(timezone.utc)),
            ended_at=payload.get("ended_at", datetime.now(timezone.utc)),
            error=str(payload.get("error", "")),
        )
