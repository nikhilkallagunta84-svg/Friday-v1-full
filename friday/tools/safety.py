from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


BLOCKED_COMMAND_PATTERNS = [
    r"\brm\s+(-[^\s]*[rf][^\s]*|-r|-f|--recursive|--force)",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bdiskutil\b",
    r"\bmkfs\b",
    r"\bdd\s+",
    r":\s*\(\s*\)\s*\{",
    r"\bchmod\s+-R\b",
    r"\bchown\s+-R\b",
    r"\bkillall\b",
    r"\bpkill\b",
    r"\blaunchctl\b",
    r"\bwhile\s+true\b",
    r"\byes\s*(>|$)",
    r">\s*/(?:etc|bin|sbin|usr|System|Library)\b",
]

CONFIRMATION_COMMAND_PATTERNS = [
    r"\bnpm\s+install\b",
    r"\bpip(?:3)?\s+install\b",
    r"\bbrew\s+install\b",
    r"\bmv\s+",
    r"\bcp\s+",
    r"\bmkdir\s+",
    r"\btouch\s+",
    r"\bopen\s+",
]

PROTECTED_PATHS = [
    Path("/"),
    Path("/System"),
    Path("/Library"),
    Path("/bin"),
    Path("/sbin"),
    Path("/usr/bin"),
    Path("/usr/sbin"),
    Path("/etc"),
    Path.home(),
]


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str


class CommandSafety:
    def validate(self, command: str, confirmed: bool = False) -> SafetyDecision:
        normalized = command.strip()
        if not normalized:
            return SafetyDecision(False, False, "Command cannot be empty.")
        if len(normalized) > 500:
            return SafetyDecision(False, False, "Command is too long to run safely.")
        lowered = normalized.lower()
        for pattern in BLOCKED_COMMAND_PATTERNS:
            if re.search(pattern, lowered):
                return SafetyDecision(False, False, f"Blocked unsafe command pattern: {pattern}")
        for path in self._absolute_paths(normalized):
            if self._is_protected_path(path):
                return SafetyDecision(False, False, f"Command targets protected path: {path}")
        for pattern in CONFIRMATION_COMMAND_PATTERNS:
            if re.search(pattern, lowered) and not confirmed:
                return SafetyDecision(True, True, "Command needs confirmation before changing the system.")
        return SafetyDecision(True, False, "Command passed safety validation.")

    def _absolute_paths(self, command: str) -> List[Path]:
        matches = re.findall(r"(?<![\w.-])/(?:[^\s'\";|&<>]+)", command)
        return [Path(match).resolve() for match in matches]

    def _is_protected_path(self, path: Path) -> bool:
        for protected in PROTECTED_PATHS:
            try:
                if path == protected or protected in path.parents:
                    return True
            except RuntimeError:
                continue
        return False


class FileSafety:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()

    def resolve(self, requested_path: str) -> Path:
        clean = requested_path.strip()
        if not clean:
            raise ValueError("File path cannot be empty.")
        target = Path(clean)
        if target.is_absolute():
            resolved = target.resolve()
        else:
            resolved = (self.base_dir / target).resolve()
        if resolved != self.base_dir and self.base_dir not in resolved.parents:
            raise ValueError("File access is limited to the FRIDAY project folder.")
        return resolved
