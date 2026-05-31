from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from friday.control.sensitive_text import redact_sensitive_text
from friday.memory.task_history import TaskHistory, TaskLogEntry


_SCREENSHOT_TERMS = ("screenshot", "screen shot", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic")
_PRIVATE_VALUE_TERMS = ("password", "passcode", "token", "secret", "api key", "credit card", "ssn")
_MAX_TEXT_LENGTH = 240


class ActionLogger:
    def __init__(self, log_path: Path | str | None = None, history: TaskHistory | None = None) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.history = history or TaskHistory()
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_task(
        self,
        source_command: str,
        planned_actions: Iterable[Any],
        results: Iterable[Any],
        timestamp: datetime | None = None,
    ) -> TaskLogEntry:
        safe_actions = [_sanitize_action(_to_plain_dict(action)) for action in planned_actions]
        safe_results = [_sanitize_result(_to_plain_dict(result)) for result in results]
        controllers_used = _controllers_used(safe_results)
        error = _combined_error(safe_results)
        entry = TaskLogEntry(
            timestamp=(timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            source_command=sanitize_text(source_command),
            planned_actions=safe_actions,
            results=safe_results,
            controllers_used=controllers_used,
            success=bool(safe_results) and all(bool(result.get("success", False)) for result in safe_results),
            error=error,
        )
        self.history.add(entry)
        if self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
        return entry

    def get_recent_actions(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.history.get_recent_actions(limit=limit)

    def summarize_last_task(self) -> str:
        return self.history.summarize_last_task()


def sanitize_text(value: Any) -> str:
    text = " ".join(str(value).split())
    if _looks_like_screenshot(text):
        return "[REDACTED_IMAGE]"
    text = redact_sensitive_text(text)
    if len(text) > _MAX_TEXT_LENGTH:
        text = f"{text[:_MAX_TEXT_LENGTH].rstrip()}..."
    return text


def _sanitize_action(action: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    action_type = str(action.get("action_type", ""))
    for key in ("action_id", "action_type", "target", "value", "risk_level", "requires_confirmation", "source_command", "created_at"):
        if key not in action:
            continue
        value = action.get(key)
        if key == "value" and _is_private_action_value(action_type, action):
            safe[key] = "[REDACTED]"
        elif key in {"target", "value", "source_command"}:
            safe[key] = sanitize_text(value)
        else:
            safe[key] = _sanitize_scalar(value)
    return safe


def _sanitize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key in ("action_id", "success", "message", "error", "started_at", "finished_at", "controller_used"):
        if key not in result:
            continue
        value = result.get(key)
        if key in {"message", "error"}:
            safe[key] = sanitize_text(value)
        else:
            safe[key] = _sanitize_scalar(value)
    return safe


def _sanitize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return sanitize_text(value)


def _to_plain_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
    elif is_dataclass(value):
        payload = asdict(value)
    elif isinstance(value, dict):
        payload = dict(value)
    else:
        payload = {"value": value}
    return _json_ready(payload)


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return str(value)


def _controllers_used(results: List[Dict[str, Any]]) -> List[str]:
    controllers: List[str] = []
    for result in results:
        controller = str(result.get("controller_used", "")).strip()
        if controller and controller not in controllers:
            controllers.append(controller)
    return controllers


def _combined_error(results: List[Dict[str, Any]]) -> str:
    errors = [str(result.get("error", "")).strip() for result in results if str(result.get("error", "")).strip()]
    if not errors:
        return ""
    return sanitize_text(" ".join(errors))


def _is_private_action_value(action_type: str, action: Dict[str, Any]) -> bool:
    text = f"{action_type} {action.get('target', '')} {action.get('source_command', '')} {action.get('value', '')}".lower()
    if action_type == "browser.extract":
        return True
    return any(term in text for term in _PRIVATE_VALUE_TERMS)


def _looks_like_screenshot(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _SCREENSHOT_TERMS)
