from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from friday.schemas.risk import RiskLevel
from friday.schemas.screen_action import ActionType, ScreenAction


BLOCKED_PATTERNS = [
    r"\b(password|passcode|login\s+code|recovery\s+code|two[-\s]?factor|2fa|mfa)\b",
    r"\b(captcha|recaptcha|hcaptcha)\b",
    r"\b(bypass|circumvent|evade|disable)\b.*\b(security|login|authentication|auth|firewall|antivirus|permission|restriction)\b",
    r"\b(hack|exploit|break\s+into|crack)\b",
    r"\b(hide|conceal|cover)\b.*\b(activity|tracks|history|logs?|evidence)\b",
    r"\b(clear|delete|erase|remove)\b.*\b(history|logs?|activity)\b",
    r"\b(delete|remove|erase|trash|wipe)\b.*\b(files?|folders?|directories?|documents?)\b",
    r"\brm\s+(-[^\s]*[rf][^\s]*|-r|-f|--recursive|--force)\b",
    r"\bsudo\s+rm\b",
    r"\bdiskutil\s+(erase|partition|zeroDisk|secureErase)\b",
    r"\b(mkfs|format\s+(?:the\s+)?(?:disk|drive)|factory\s+reset)\b",
    r"\bdd\s+if=",
    r"\bchmod\s+-R\b",
    r"\bchown\s+-R\b",
]


HIGH_RISK_PATTERNS = [
    r"\b(send|email|message|text|dm|reply)\b.*\b(email|message|text|dm|reply|recipient|to\s+)\b",
    r"\b(post|publish|tweet|share)\b.*\b(public|publicly|online|instagram|tiktok|youtube|reddit|x|twitter|facebook)\b",
    r"\b(submit|turn\s+in|hand\s+in|file)\b.*\b(form|application|assignment|homework|quiz|test|exam|claim|request)\b",
    r"\b(form|application|assignment|homework|quiz|test|exam)\b.*\b(submit|turn\s+in|hand\s+in|send)\b",
    r"\b(apply|application)\b.*\b(job|college|school|program|loan|account)\b",
    r"\b(buy|purchase|checkout|pay|payment|order|subscribe|book|reserve)\b",
    r"\b(delete|close|deactivate|cancel|transfer|change)\b.*\b(account|profile|subscription|plan|ownership|email\s+address|username)\b",
]


LOW_RISK_ACTION_TYPES = {
    ActionType.BROWSER_OPEN_URL,
    ActionType.BROWSER_SEARCH,
    ActionType.BROWSER_CLICK,
    ActionType.BROWSER_NAVIGATE,
    ActionType.DESKTOP_OPEN_APP,
    ActionType.DESKTOP_FOCUS_APP,
}

SAFE_ACTION_TYPES = {
    ActionType.SYSTEM_WAIT,
    ActionType.SYSTEM_STOP,
}

MEDIUM_RISK_ACTION_TYPES = {
    ActionType.BROWSER_TYPE,
    ActionType.BROWSER_EXTRACT,
    ActionType.DESKTOP_TYPE,
    ActionType.DESKTOP_HOTKEY,
    ActionType.SYSTEM_ASK_CONFIRMATION,
}


def classify_action(action: ScreenAction) -> ScreenAction:
    text = _action_text(action)
    if _matches_any(BLOCKED_PATTERNS, text):
        return _with_risk(action, RiskLevel.BLOCKED)
    if _matches_any(HIGH_RISK_PATTERNS, text):
        return _with_risk(action, RiskLevel.HIGH)
    if action.action_type in SAFE_ACTION_TYPES:
        return _with_risk(action, RiskLevel.SAFE)
    if action.action_type in LOW_RISK_ACTION_TYPES:
        return _with_risk(action, RiskLevel.LOW)
    if action.action_type in MEDIUM_RISK_ACTION_TYPES:
        return _with_risk(action, RiskLevel.MEDIUM)
    return _with_risk(action, action.risk_level)


def _action_text(action: ScreenAction) -> str:
    parts = [
        action.action_type.value,
        action.target,
        action.value,
        action.source_command,
    ]
    return " ".join(part for part in parts if part).lower()


def _matches_any(patterns: Iterable[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _with_risk(action: ScreenAction, risk_level: RiskLevel) -> ScreenAction:
    return replace(
        action,
        risk_level=risk_level,
        requires_confirmation=risk_level in {RiskLevel.HIGH, RiskLevel.BLOCKED},
    )
