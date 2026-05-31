from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


SECRET_PATTERNS = [
    re.compile(r"re_[A-Za-z0-9_]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
]


def redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[redacted]", redacted)
        return redacted
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


@dataclass(frozen=True)
class TranscriptEntry:
    created_at: float
    source: str
    raw_input: str
    filtered_input: str
    intent: Dict[str, Any]
    executed_commands: List[Dict[str, Any]]
    final_output: str
    task_classification: str = ""
    selected_model: str = ""
    model_type: str = ""


class TranscriptLogger:
    def __init__(self, transcript_dir: Path) -> None:
        self.transcript_dir = transcript_dir
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        session_stamp = time.strftime("%Y%m%d-%H%M%S")
        self.jsonl_path = self.transcript_dir / f"session-{session_stamp}.jsonl"
        self.markdown_path = self.transcript_dir / f"session-{session_stamp}.md"
        self.markdown_path.write_text("# FRIDAY Session Transcript\n\n", encoding="utf-8")

    def log(self, entry: TranscriptEntry) -> None:
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        if not self.markdown_path.exists():
            self.markdown_path.write_text("# FRIDAY Session Transcript\n\n", encoding="utf-8")
        safe_entry = redact(asdict(entry))
        with self.jsonl_path.open("a", encoding="utf-8") as jsonl_file:
            jsonl_file.write(json.dumps(safe_entry, sort_keys=True) + "\n")

        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.created_at))
        markdown = [
            f"## {created} - {entry.source}",
            "",
            f"Raw input: {redact(entry.raw_input)}",
            "",
            f"Filtered input: {redact(entry.filtered_input)}",
            "",
            "Intent:",
            "```json",
            json.dumps(redact(entry.intent), indent=2, sort_keys=True),
            "```",
            "",
            "Executed commands:",
            "```json",
            json.dumps(redact(entry.executed_commands), indent=2, sort_keys=True),
            "```",
            "",
            f"Final output: {redact(entry.final_output)}",
            "",
        ]
        if entry.task_classification or entry.selected_model:
            markdown.insert(-1, f"Task classification: {entry.task_classification}")
            markdown.insert(-1, f"Selected model: {entry.selected_model}")
            markdown.insert(-1, f"Model type: {entry.model_type}")
            markdown.insert(-1, "")
        with self.markdown_path.open("a", encoding="utf-8") as md_file:
            md_file.write("\n".join(markdown))
