from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class SafetyDecision:
    requires_confirmation: bool
    reason: str


class SafetyValidator:
    RISKY_PATTERNS = [
        (r"\b(send|email|message|post|publish)\b", "sending or posting information"),
        (r"\b(delete|remove|erase|overwrite)\b", "deleting or overwriting data"),
        (r"\b(buy|purchase|checkout|pay|book|reserve)\b", "spending money or booking something"),
        (r"\b(submit|turn\s+in|hand\s+in|mark\s+as\s+done)\b", "submitting schoolwork or forms"),
        (r"\b(install|pip\s+install|npm\s+install|brew\s+install)\b", "installing software"),
        (r"\b(password|api\s*key|secret|token|credit\s*card|social\s*security)\b", "handling sensitive information"),
    ]

    def validate(self, command_text: str, intent: Dict[str, Any]) -> SafetyDecision:
        params = intent.get("parameters", {})
        param_text = " ".join(str(v) for v in params.values() if isinstance(v, str)) if isinstance(params, dict) else ""
        merged = f"{command_text} {intent.get('intent', '')} {intent.get('command', '')} {param_text}".lower()
        for pattern, reason in self.RISKY_PATTERNS:
            if re.search(pattern, merged):
                parameters = intent.get("parameters", {})
                confirmed = isinstance(parameters, dict) and bool(parameters.get("confirmed", False))
                return SafetyDecision(not confirmed, reason)
        return SafetyDecision(False, "")
