from __future__ import annotations

from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


CONFIRMATION_REQUIRED_RISKS = {RiskLevel.HIGH, RiskLevel.BLOCKED}


def coerce_risk_level(value: Any) -> RiskLevel:
    if isinstance(value, RiskLevel):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        for risk_level in RiskLevel:
            if normalized == risk_level.value:
                return risk_level
    allowed = ", ".join(risk.value for risk in RiskLevel)
    raise ValueError(f"Invalid risk_level {value!r}. Expected one of: {allowed}.")


def risk_requires_confirmation(value: RiskLevel | str) -> bool:
    return coerce_risk_level(value) in CONFIRMATION_REQUIRED_RISKS
