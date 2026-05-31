from __future__ import annotations

from friday.schemas.risk import RiskLevel, coerce_risk_level
from friday.schemas.screen_action import ScreenAction


def needs_confirmation(action: ScreenAction) -> bool:
    risk_level = coerce_risk_level(action.risk_level)
    if risk_level == RiskLevel.BLOCKED:
        return False
    return risk_level == RiskLevel.HIGH or bool(action.requires_confirmation)


def build_confirmation_prompt(action: ScreenAction) -> str:
    risk_level = coerce_risk_level(action.risk_level)
    description = _describe_action(action)
    if risk_level == RiskLevel.BLOCKED:
        return f"I can't do that, boss. This action is blocked for safety: {description}."
    if needs_confirmation(action):
        return f"Just to confirm, sir — do you want me to {description}?"
    return f"No confirmation needed for {description}."


def _describe_action(action: ScreenAction) -> str:
    target = action.target.strip()
    value = action.value.strip()
    if target and value:
        return f"{action.action_type.value} on {target} with {value}"
    if target:
        return f"{action.action_type.value} on {target}"
    if value:
        return f"{action.action_type.value} with {value}"
    return action.action_type.value
