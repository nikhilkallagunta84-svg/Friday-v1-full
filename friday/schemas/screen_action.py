from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

from friday.schemas.risk import RiskLevel, coerce_risk_level, risk_requires_confirmation


class ActionType(str, Enum):
    BROWSER_OPEN_URL = "browser.open_url"
    BROWSER_SEARCH = "browser.search"
    BROWSER_CLICK = "browser.click"
    BROWSER_TYPE = "browser.type"
    BROWSER_EXTRACT = "browser.extract"
    BROWSER_NAVIGATE = "browser.navigate"
    DESKTOP_OPEN_APP = "desktop.open_app"
    DESKTOP_FOCUS_APP = "desktop.focus_app"
    DESKTOP_TYPE = "desktop.type"
    DESKTOP_HOTKEY = "desktop.hotkey"
    SYSTEM_WAIT = "system.wait"
    SYSTEM_ASK_CONFIRMATION = "system.ask_confirmation"
    SYSTEM_STOP = "system.stop"


def coerce_action_type(value: Any) -> ActionType:
    if isinstance(value, ActionType):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        for action_type in ActionType:
            if normalized == action_type.value:
                return action_type
    allowed = ", ".join(action.value for action in ActionType)
    raise ValueError(f"Invalid action_type {value!r}. Expected one of: {allowed}.")


def coerce_datetime(value: Any, field_name: str) -> datetime:
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


@dataclass(frozen=True)
class ScreenAction:
    action_id: str
    action_type: ActionType | str
    target: str
    value: str
    risk_level: RiskLevel | str
    requires_confirmation: bool
    source_command: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be a non-empty string.")
        if not isinstance(self.target, str):
            raise TypeError("target must be a string.")
        if not isinstance(self.value, str):
            raise TypeError("value must be a string.")
        if not isinstance(self.requires_confirmation, bool):
            raise TypeError("requires_confirmation must be a boolean.")
        if not isinstance(self.source_command, str) or not self.source_command.strip():
            raise ValueError("source_command must be a non-empty string.")

        action_type = coerce_action_type(self.action_type)
        risk_level = coerce_risk_level(self.risk_level)
        created_at = coerce_datetime(self.created_at, "created_at")

        if risk_requires_confirmation(risk_level) and not self.requires_confirmation:
            raise ValueError(f"{risk_level.value} actions must require confirmation.")

        object.__setattr__(self, "action_id", self.action_id.strip())
        object.__setattr__(self, "action_type", action_type)
        object.__setattr__(self, "risk_level", risk_level)
        object.__setattr__(self, "source_command", self.source_command.strip())
        object.__setattr__(self, "created_at", created_at)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ScreenAction":
        return cls(
            action_id=payload["action_id"],
            action_type=payload["action_type"],
            target=payload["target"],
            value=payload["value"],
            risk_level=payload["risk_level"],
            requires_confirmation=payload["requires_confirmation"],
            source_command=payload["source_command"],
            created_at=payload.get("created_at", datetime.now(timezone.utc)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "target": self.target,
            "value": self.value,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
            "source_command": self.source_command,
            "created_at": self.created_at.isoformat(),
        }
