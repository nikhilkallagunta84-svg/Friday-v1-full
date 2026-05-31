from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from friday.brain.safety_validator import SafetyValidator


@dataclass(frozen=True)
class VoiceIntent:
    raw_transcript: str
    cleaned_transcript: str
    intent: str
    confidence: float
    requires_confirmation: bool
    confirmation_reason: str
    tool: str
    action: str
    target: str
    parameters: Dict[str, Any]
    context_references: List[str] = field(default_factory=list)
    missing_required_fields: List[str] = field(default_factory=list)
    keep_session_open: bool = False
    response_to_user: str = ""


class IntentParser:
    def __init__(self, safety: SafetyValidator | None = None) -> None:
        self.safety = safety or SafetyValidator()

    def validate_legacy_intent(self, raw_transcript: str, cleaned_transcript: str, intent: Dict[str, Any]) -> Dict[str, Any]:
        command = str(intent.get("command", "none") or "none")
        parameters = intent.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
            intent["parameters"] = parameters
        name = str(intent.get("intent") or "conversation")
        safety = self.safety.validate(cleaned_transcript, intent)
        confidence = 0.95 if command != "none" else 0.78
        target = self._target_from_parameters(parameters)
        schema = VoiceIntent(
            raw_transcript=raw_transcript,
            cleaned_transcript=cleaned_transcript,
            intent=name,
            confidence=confidence,
            requires_confirmation=safety.requires_confirmation,
            confirmation_reason=safety.reason,
            tool=command,
            action=name,
            target=target,
            parameters=dict(parameters),
            context_references=self._context_references(cleaned_transcript),
            missing_required_fields=[],
            keep_session_open=bool(parameters.get("keep_session_open", False)),
            response_to_user=str(parameters.get("response_to_user", "")),
        )
        intent["voice_intent"] = asdict(schema)
        return intent

    def _target_from_parameters(self, parameters: Dict[str, Any]) -> str:
        for key in ("target", "app_name", "url", "query", "task", "file_path", "path"):
            value = str(parameters.get(key) or "").strip()
            if value:
                return value
        return ""

    def _context_references(self, text: str) -> List[str]:
        references: List[str] = []
        for word in ("it", "that", "this", "there"):
            if f" {word} " in f" {text.lower()} ":
                references.append(word)
        return references
