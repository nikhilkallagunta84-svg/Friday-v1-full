"""Turn natural-language call requests into structured :class:`CallBrief`.

The planner asks Ollama for strict JSON, then validates it. Falls back to a
keyword-extracted brief (with ``confidence=0.0`` and empty number) when Ollama
is unreachable or returns junk — the caller can then ask the user for the
missing number rather than silently failing.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from friday.ollama_engine import OllamaClient, OllamaUnavailable

try:  # ModelManager is optional so this module stays importable in light tests.
    from friday.model_manager import ModelManager
except ImportError:  # pragma: no cover - defensive
    ModelManager = None  # type: ignore[assignment]

from friday.schemas.phone_call import CallBrief


# A reasonable cap so the planner can't accept a 60-page transcript as a brief.
_MAX_REQUEST_LENGTH = 4000


class CallPlanner:
    """Extract a structured :class:`CallBrief` from natural language."""

    def __init__(
        self,
        ollama: OllamaClient,
        model_manager: "ModelManager | None" = None,
        default_persona: str = "respectful",
        default_max_minutes: int = 5,
    ) -> None:
        self.ollama = ollama
        self.model_manager = model_manager
        self.default_persona = default_persona.strip() or "respectful"
        self.default_max_minutes = max(1, min(int(default_max_minutes), 60))

    def plan(self, user_request: str) -> Tuple[CallBrief, float]:
        cleaned = self._clean_request(user_request)
        if not cleaned:
            raise ValueError("user_request is empty.")

        try:
            payload = self._ollama_brief(cleaned)
        except OllamaUnavailable:
            payload = {}
        except Exception:  # noqa: BLE001 — defensive: planner never crashes the caller
            payload = {}

        brief, confidence = self._build_brief(payload, cleaned)
        return brief, confidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clean_request(self, user_request: str) -> str:
        clean = " ".join(str(user_request or "").split()).strip()
        if not clean:
            return ""
        if len(clean) > _MAX_REQUEST_LENGTH:
            clean = clean[:_MAX_REQUEST_LENGTH]
        return clean

    def _ollama_brief(self, request: str) -> Dict[str, Any]:
        prompt = self._prompt(request)
        model = self._select_model()
        response = self.ollama.generate_json(prompt, model=model)
        text = response.text.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _select_model(self) -> "str | None":
        if not self.model_manager:
            return None
        try:
            chosen = self.model_manager.select_model_for_task("simple")
        except Exception:  # noqa: BLE001
            return None
        return chosen or None

    def _prompt(self, request: str) -> str:
        return (
            "You are FRIDAY's phone-call brief extractor.\n"
            "Return strict JSON only with this exact shape:\n"
            '{"recipient_name":"","recipient_number":"","objective":"",'
            '"talking_points":[],"success_criteria":[],"max_minutes":5,'
            '"persona":"respectful"}\n\n'
            "Rules:\n"
            "- recipient_name: the person, business, or department the user wants called. "
            "Required. If only a number is given, use the number as the name.\n"
            "- recipient_number: a phone number if explicitly stated. Empty string if not. "
            "Never invent a number.\n"
            "- objective: one short sentence describing the goal of the call.\n"
            "- talking_points: 1-5 short bullets the assistant must mention "
            "(reference numbers, names, dates, the user's preferences).\n"
            "- success_criteria: 1-3 short bullets describing what counts as success.\n"
            "- max_minutes: integer between 1 and 30. Default 5.\n"
            "- persona: one of 'respectful', 'formal', 'casual', 'firm'. Default 'respectful'.\n"
            "- Return ONLY the JSON. No prose, no markdown fences, no <think> tags.\n\n"
            f"User request: {request}\n"
        )

    def _build_brief(self, payload: Dict[str, Any], request: str) -> Tuple[CallBrief, float]:
        recipient_name = _coerce_str(payload.get("recipient_name")) or _guess_recipient(request)
        recipient_number = _coerce_phone(payload.get("recipient_number")) or _extract_phone(request)
        objective = _coerce_str(payload.get("objective")) or _guess_objective(request)
        talking_points = _coerce_str_list(payload.get("talking_points"))
        success_criteria = _coerce_str_list(payload.get("success_criteria"))
        max_minutes = _coerce_int(payload.get("max_minutes"), self.default_max_minutes, low=1, high=30)
        persona = _coerce_str(payload.get("persona")) or self.default_persona

        if not recipient_name:
            recipient_name = "the recipient"
        if not objective:
            objective = "have the conversation the user requested"

        brief = CallBrief(
            call_id=f"call-{uuid.uuid4().hex[:12]}",
            recipient_name=recipient_name,
            recipient_number=recipient_number,
            objective=objective,
            talking_points=talking_points,
            success_criteria=success_criteria,
            max_minutes=max_minutes,
            persona=persona,
            source_command=request,
            created_at=datetime.now(timezone.utc),
        )
        confidence = self._confidence(brief, payload)
        return brief, confidence

    @staticmethod
    def _confidence(brief: CallBrief, payload: Dict[str, Any]) -> float:
        score = 0.0
        if payload:
            score += 0.4  # Ollama returned a usable JSON blob
        if brief.recipient_number:
            score += 0.4
        if brief.recipient_name and brief.recipient_name != "the recipient":
            score += 0.1
        if brief.talking_points:
            score += 0.1
        return min(score, 1.0)


# ----------------------------------------------------------------------
# Pure helpers — easy to unit-test, also reused by the fallback path
# ----------------------------------------------------------------------


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_coerce_str(entry) for entry in value) if item]
    if isinstance(value, str):
        item = _coerce_str(value)
        return [item] if item else []
    return []


def _coerce_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


_PHONE_DIGIT_RE = re.compile(r"[\d+()\-\s]+")


def _coerce_phone(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text if _has_enough_digits(text) else ""


def _extract_phone(text: str) -> str:
    """Pull a phone number out of free-form text, if any."""
    if not text:
        return ""
    best = ""
    for chunk in _PHONE_DIGIT_RE.findall(text):
        candidate = chunk.strip()
        if not candidate:
            continue
        digits = re.sub(r"\D+", "", candidate)
        if len(digits) >= 10 and len(digits) > len(re.sub(r"\D+", "", best)):
            best = candidate
    return best.strip() if _has_enough_digits(best) else ""


def _has_enough_digits(text: str) -> bool:
    return len(re.sub(r"\D+", "", text)) >= 10


_RECIPIENT_HINT_RE = re.compile(
    r"^(?:call|phone|ring(?:\s+up)?|dial)\s+(?:up\s+)?(.+?)(?:\s+(?:and|to|about|for|on)\b|[.,?!]|$)",
    re.IGNORECASE,
)


def _guess_recipient(text: str) -> str:
    match = _RECIPIENT_HINT_RE.search(text or "")
    if not match:
        return ""
    candidate = match.group(1).strip(" .,?!'\"")
    # Strip trailing "at <number>" or pure number-only matches.
    candidate = re.sub(r"\s+at\s+\+?\d[\d\s\-().]{6,}.*$", "", candidate, flags=re.IGNORECASE).strip()
    if not candidate or candidate.lower() in {"me", "back", "later"}:
        return ""
    return candidate


_OBJECTIVE_HINT_RE = re.compile(
    r"\b(?:and|to)\s+(ask|tell|request|inquire|check|find\s+out|see\s+if|confirm|cancel)\s+(.+?)$",
    re.IGNORECASE,
)


def _guess_objective(text: str) -> str:
    match = _OBJECTIVE_HINT_RE.search(text or "")
    if not match:
        return ""
    verb = match.group(1).lower().replace("  ", " ")
    rest = match.group(2).strip(" .,?!")
    return f"{verb} {rest}".strip()
