from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List


@dataclass(frozen=True)
class TaskLogEntry:
    timestamp: str
    source_command: str
    planned_actions: List[Dict[str, Any]]
    results: List[Dict[str, Any]]
    controllers_used: List[str]
    success: bool
    error: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source_command": self.source_command,
            "planned_actions": self.planned_actions,
            "results": self.results,
            "controllers_used": self.controllers_used,
            "success": self.success,
            "error": self.error,
        }


class TaskHistory:
    def __init__(self, max_entries: int = 200) -> None:
        self._entries: Deque[TaskLogEntry] = deque(maxlen=max_entries)

    def add(self, entry: TaskLogEntry) -> TaskLogEntry:
        self._entries.append(entry)
        return entry

    def get_recent_actions(self, limit: int = 10) -> List[Dict[str, Any]]:
        safe_limit = max(0, int(limit))
        if safe_limit == 0:
            return []
        return [entry.to_dict() for entry in list(self._entries)[-safe_limit:]]

    def summarize_last_task(self) -> str:
        if not self._entries:
            return "I do not have a recent screen-control task logged yet, sir."
        return _summarize_entry(self._entries[-1])


def _summarize_entry(entry: TaskLogEntry) -> str:
    action_phrase = _action_phrase(entry.planned_actions)
    if entry.success:
        completion = _success_phrase(entry.planned_actions)
        return f"I {action_phrase}. {completion}"
    error = entry.error.strip()
    if error:
        return f"I tried to {action_phrase}, but it did not finish. {error}"
    return f"I tried to {action_phrase}, but it did not finish successfully."


def _action_phrase(actions: List[Dict[str, Any]]) -> str:
    if not actions:
        return "checked the screen-control request"

    open_action = next((action for action in actions if action.get("action_type") == "browser.open_url"), None)
    search_action = next((action for action in actions if action.get("action_type") == "browser.search"), None)
    click_action = next((action for action in actions if action.get("action_type") == "browser.click"), None)
    type_action = next((action for action in actions if action.get("action_type") in {"browser.type", "desktop.type"}), None)

    if open_action and search_action:
        return f"opened {_display_target(open_action)} and searched for {_display_value(search_action.get('value', 'that'))}"
    if search_action:
        target = _display_target(search_action)
        if target and target != "the browser":
            return f"searched {target} for {_display_value(search_action.get('value', 'that'))}"
        return f"searched for {_display_value(search_action.get('value', 'that'))}"
    if open_action:
        return f"opened {_display_target(open_action)}"
    if click_action:
        return f"clicked {_display_value(click_action.get('target', 'that'))}"
    if type_action:
        return "typed the requested text"

    first = actions[0]
    action_type = str(first.get("action_type", "screen action")).replace(".", " ")
    target = _display_value(first.get("target", "") or first.get("value", ""))
    return f"ran {action_type}{f' on {target}' if target else ''}"


def _success_phrase(actions: List[Dict[str, Any]]) -> str:
    if any(action.get("action_type") == "browser.search" for action in actions):
        return "The search completed successfully."
    if any(action.get("action_type") == "browser.open_url" for action in actions):
        return "The page opened successfully."
    return "The task completed successfully."


def _display_target(action: Dict[str, Any]) -> str:
    target = _display_value(action.get("target", ""))
    if target.endswith(" search"):
        target = target[: -len(" search")].strip()
    if not target:
        value = str(action.get("value", "")).lower()
        for marker, label in (
            ("youtube", "YouTube"),
            ("spotify", "Spotify"),
            ("instagram", "Instagram"),
            ("google", "Google"),
            ("chatgpt", "ChatGPT"),
        ):
            if marker in value:
                return label
        return "the browser"
    special = {
        "chatgpt": "ChatGPT",
        "chat gpt": "ChatGPT",
        "youtube": "YouTube",
        "spotify": "Spotify",
        "instagram": "Instagram",
        "google": "Google",
    }
    return special.get(target.lower(), target.title())


def _display_value(value: Any) -> str:
    text = " ".join(str(value).split()).strip()
    return text or "that"
