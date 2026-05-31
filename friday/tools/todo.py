from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class TodoTask:
    id: str
    title: str
    created_at: str
    due_at: str = ""
    time_limit_minutes: int | None = None
    completed_at: str = ""

    @classmethod
    def from_dict(cls, values: Dict[str, Any]) -> "TodoTask":
        limit = values.get("time_limit_minutes")
        try:
            parsed_limit = int(limit) if limit not in {None, ""} else None
        except (TypeError, ValueError):
            parsed_limit = None
        return cls(
            id=str(values.get("id") or uuid.uuid4().hex[:10]),
            title=str(values.get("title") or "").strip(),
            created_at=str(values.get("created_at") or _now().isoformat()),
            due_at=str(values.get("due_at") or ""),
            time_limit_minutes=parsed_limit,
            completed_at=str(values.get("completed_at") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TodoListTool:
    def __init__(self, root_dir: Path, clock: Any | None = None) -> None:
        self.root_dir = root_dir
        self.path = root_dir / ".friday" / "todos.json"
        self._clock = clock or _now

    def add_task(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        raw_title = str(parameters.get("task") or parameters.get("title") or parameters.get("text") or "").strip()
        if not raw_title:
            return self._failure("Tell me what task to add, boss.", {})
        parsed = self._parse_task_details(raw_title)
        title = parsed["title"]
        if not title:
            return self._failure("Tell me what task to add, boss.", {})

        tasks = self._load()
        task = TodoTask(
            id=uuid.uuid4().hex[:10],
            title=title,
            created_at=self._clock().isoformat(),
            due_at=parsed["due_at"],
            time_limit_minutes=parsed["time_limit_minutes"],
        )
        tasks.append(task)
        self._save(tasks)
        return self._success(self._added_message(task), {"task": task.to_dict(), "todos": self.snapshot()["active"]})

    def complete_task(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        target = str(parameters.get("task") or parameters.get("title") or parameters.get("target") or "").strip()
        if not target:
            return self._failure("Which task did you finish, boss?", {"todos": self.snapshot()["active"]})

        tasks = self._load()
        match = self._find_active_task(tasks, target)
        if not match:
            return self._failure(f"I couldn't find {target} on your todo list, sir.", {"todos": self.snapshot()["active"]})

        updated: List[TodoTask] = []
        completed = None
        completed_at = self._clock().isoformat()
        for task in tasks:
            if task.id == match.id:
                completed = TodoTask(
                    id=task.id,
                    title=task.title,
                    created_at=task.created_at,
                    due_at=task.due_at,
                    time_limit_minutes=task.time_limit_minutes,
                    completed_at=completed_at,
                )
                updated.append(completed)
            else:
                updated.append(task)
        self._save(updated)
        assert completed is not None
        return self._success(
            f"Removed {completed.title} from your todo list, boss.",
            {"task": completed.to_dict(), "todos": self.snapshot()["active"]},
        )

    def clear_tasks(self, parameters: Dict[str, Any] | None = None) -> Dict[str, Any]:
        parameters = parameters or {}
        mode = str(parameters.get("mode") or "active").strip().lower()
        tasks = self._load()
        now = self._clock().isoformat()

        if mode == "completed":
            remaining = [task for task in tasks if not task.completed_at]
            cleared = len(tasks) - len(remaining)
            self._save(remaining)
            message = "Cleared completed todo history, boss." if cleared else "There are no completed tasks to clear, boss."
            return self._success(message, {"cleared_count": cleared, "todos": self.snapshot()["active"]})

        if mode == "all":
            cleared = len(tasks)
            self._save([])
            message = f"Cleared {cleared} task{'s' if cleared != 1 else ''} from your todo list, boss." if cleared else "Your todo list is already clear, boss."
            return self._success(message, {"cleared_count": cleared, "todos": []})

        updated: List[TodoTask] = []
        cleared = 0
        for task in tasks:
            if task.completed_at:
                updated.append(task)
                continue
            cleared += 1
            updated.append(
                TodoTask(
                    id=task.id,
                    title=task.title,
                    created_at=task.created_at,
                    due_at=task.due_at,
                    time_limit_minutes=task.time_limit_minutes,
                    completed_at=now,
                )
            )
        self._save(updated)
        message = f"Cleared {cleared} active task{'s' if cleared != 1 else ''} from your todo list, boss." if cleared else "Your todo list is already clear, boss."
        return self._success(message, {"cleared_count": cleared, "todos": self.snapshot()["active"]})

    def list_tasks(self, parameters: Dict[str, Any] | None = None) -> Dict[str, Any]:
        active = self.snapshot()["active"]
        if not active:
            return self._success("Your todo list is clear, boss.", {"todos": active})
        lines = ["Here's your todo list, boss:"]
        for index, task in enumerate(active, start=1):
            lines.append(f"{index}. {self._format_task_summary(task)}")
        return self._success("\n".join(lines), {"todos": active})

    def snapshot(self) -> Dict[str, Any]:
        tasks = self._load()
        active = [task.to_dict() for task in tasks if not task.completed_at]
        completed = [task.to_dict() for task in tasks if task.completed_at]
        active.sort(key=self._sort_key)
        return {"active": active, "completed_count": len(completed), "count": len(active)}

    def _parse_task_details(self, text: str) -> Dict[str, Any]:
        clean = " ".join(text.strip(" .?!").split())
        time_limit = self._extract_time_limit(clean)
        if time_limit:
            clean = time_limit["text"]
        due = self._extract_due(clean)
        if due:
            clean = due["text"]
        clean = re.sub(r"\b(?:task|todo|to-do)\b$", "", clean, flags=re.I).strip(" .")
        return {
            "title": clean,
            "due_at": due["due_at"] if due else "",
            "time_limit_minutes": time_limit["minutes"] if time_limit else None,
        }

    def _extract_time_limit(self, text: str) -> Dict[str, Any] | None:
        patterns = [
            r"\b(?:with\s+)?(?:a\s+)?(?:time\s+limit|limit|timer)\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b",
            r"\b(?:for|take)\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if not match:
                continue
            minutes = _duration_to_minutes(match.group(1), match.group(2))
            stripped = " ".join((text[: match.start()] + text[match.end() :]).split())
            return {"minutes": minutes, "text": stripped}
        return None

    def _extract_due(self, text: str) -> Dict[str, Any] | None:
        now = self._clock()
        relative = re.search(r"\b(?:due\s+)?(?:in|within)\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?|days?)\b", text, flags=re.I)
        if relative:
            minutes = _duration_to_minutes(relative.group(1), relative.group(2))
            due_at = now + timedelta(minutes=minutes)
            stripped = " ".join((text[: relative.start()] + text[relative.end() :]).split())
            return {"due_at": due_at.isoformat(), "text": stripped}

        due_match = re.search(
            r"\b(?:by|before|due(?:\s+by|\s+at)?|at)\s+((?:today|tomorrow|tonight)\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b",
            text,
            flags=re.I,
        )
        if due_match:
            day_word = (due_match.group(1) or "").strip().lower()
            hour = int(due_match.group(2))
            minute = int(due_match.group(3) or 0)
            meridiem = (due_match.group(4) or "").replace(".", "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if day_word == "tomorrow" or due_at <= now:
                due_at += timedelta(days=1)
            stripped = " ".join((text[: due_match.start()] + text[due_match.end() :]).split())
            return {"due_at": due_at.isoformat(), "text": stripped}

        day_match = re.search(r"\b(?:due\s+)?(?:by\s+)?(today|tomorrow|tonight)\b", text, flags=re.I)
        if day_match:
            day_word = day_match.group(1).lower()
            due_at = now.replace(hour=23, minute=59, second=0, microsecond=0)
            if day_word == "tomorrow":
                due_at += timedelta(days=1)
            if day_word == "tonight":
                due_at = now.replace(hour=21, minute=0, second=0, microsecond=0)
                if due_at <= now:
                    due_at += timedelta(days=1)
            stripped = " ".join((text[: day_match.start()] + text[day_match.end() :]).split())
            return {"due_at": due_at.isoformat(), "text": stripped}
        return None

    def _find_active_task(self, tasks: List[TodoTask], target: str) -> TodoTask | None:
        normalized_target = _normalize_match_text(target)
        scored: list[tuple[float, TodoTask]] = []
        for task in tasks:
            if task.completed_at:
                continue
            normalized_title = _normalize_match_text(task.title)
            if normalized_target == normalized_title:
                return task
            if normalized_target in normalized_title or normalized_title in normalized_target:
                scored.append((0.92, task))
                continue
            overlap = _token_overlap(normalized_target, normalized_title)
            ratio = SequenceMatcher(None, normalized_target, normalized_title).ratio()
            score = max(overlap, ratio)
            if score >= 0.52:
                scored.append((score, task))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _load(self) -> List[TodoTask]:
        if not self.path.exists():
            return []
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [task for item in parsed if isinstance(item, dict) for task in [TodoTask.from_dict(item)] if task.title]

    def _save(self, tasks: List[TodoTask]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([task.to_dict() for task in tasks], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _sort_key(self, task: Dict[str, Any]) -> tuple[str, str]:
        due = str(task.get("due_at") or "")
        created = str(task.get("created_at") or "")
        return (due or "9999", created)

    def _format_task_summary(self, task: Dict[str, Any]) -> str:
        title = str(task.get("title") or "Untitled task")
        bits = [title]
        due_at = str(task.get("due_at") or "")
        if due_at:
            bits.append(f"due {_format_due_for_speech(due_at, self._clock())}")
        limit = task.get("time_limit_minutes")
        if isinstance(limit, int) and limit > 0:
            bits.append(f"{_format_minutes(limit)} limit")
        return " - ".join(bits)

    def _added_message(self, task: TodoTask) -> str:
        bits = [f"Added {task.title} to your todo list, boss."]
        if task.due_at:
            bits.append(f"Due {_format_due_for_speech(task.due_at, self._clock())}.")
        if task.time_limit_minutes:
            bits.append(f"Time limit: {_format_minutes(task.time_limit_minutes)}.")
        return " ".join(bits)

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}


def _now() -> datetime:
    return datetime.now().astimezone()


def _duration_to_minutes(amount: str, unit: str) -> int:
    value = float(amount)
    clean_unit = unit.lower()
    if clean_unit.startswith("hour") or clean_unit.startswith("hr"):
        value *= 60
    elif clean_unit.startswith("day"):
        value *= 24 * 60
    return max(1, int(round(value)))


def _normalize_match_text(value: str) -> str:
    clean = value.lower().replace("’", "'")
    clean = re.sub(r"\b(?:task|todo|to-do|the|my|a|an)\b", " ", clean)
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return " ".join(clean.split())


def _token_overlap(a: str, b: str) -> float:
    left = set(a.split())
    right = set(b.split())
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def _format_due_for_speech(value: str, now: datetime | None = None) -> str:
    try:
        due = datetime.fromisoformat(value)
    except ValueError:
        return value
    now = now or _now()
    time_text = due.strftime("%I:%M %p").lstrip("0")
    if due.date() == now.date():
        return f"today at {time_text}"
    if due.date() == (now + timedelta(days=1)).date():
        return f"tomorrow at {time_text}"
    return due.strftime("%b %-d at %-I:%M %p")


def _format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {mins} minutes"
