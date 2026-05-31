from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class TTSStatus:
    available: bool
    speaking: bool
    silent: bool


class TTSManager:
    def __init__(self, silent: bool = False, config: Dict[str, Any] | None = None) -> None:
        values = config or {}
        self._say_path = shutil.which("say")
        self._silent = silent
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._current_text: str | None = None
        self._recent_text: str | None = None
        self._recent_text_at = 0.0
        self._voice_name = self._resolve_voice_name(str(values.get("voice_name") or ""))
        self._rate = int(values.get("rate") or 172)
        self._print_before_speak = bool(values.get("print_before_speak", True))

    @property
    def available(self) -> bool:
        return self._say_path is not None

    @property
    def silent(self) -> bool:
        with self._lock:
            return self._silent

    def warmup(self) -> None:
        return

    def set_silent(self, silent: bool) -> None:
        self.set_silent_mode(silent)

    def set_silent_mode(self, enabled: bool) -> None:
        with self._lock:
            self._silent = enabled
            if enabled:
                self._interrupt_locked()

    def set_voice(self, voice_name: str) -> None:
        with self._lock:
            self._voice_name = voice_name.strip()

    def set_rate(self, rate: int) -> None:
        with self._lock:
            self._rate = max(80, min(int(rate), 360))

    def status(self) -> TTSStatus:
        with self._lock:
            return TTSStatus(available=self.available, speaking=self.is_speaking(), silent=self._silent)

    def is_speaking(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def get_current_spoken_text(self) -> str | None:
        with self._lock:
            return self._current_text

    def get_recent_spoken_text(self, max_age_seconds: float = 8.0) -> str | None:
        with self._lock:
            if not self._recent_text:
                return None
            if time.time() - self._recent_text_at > max_age_seconds:
                return None
            return self._recent_text

    def interrupt(self) -> bool:
        return self.stop()

    def stop(self) -> bool:
        with self._lock:
            return self._interrupt_locked()

    def clear_queue(self) -> None:
        self.stop()

    def speak(self, text: str, priority: str = "normal") -> None:
        clean_text = self._clean_spoken_text(text)
        if not clean_text:
            return
        with self._lock:
            if self._silent or not self._say_path:
                self._current_text = None
                return
            if self._print_before_speak:
                print(clean_text, flush=True)
            self._interrupt_locked()
            command = [self._say_path, "-r", str(self._rate)]
            if self._voice_name:
                command.extend(["-v", self._voice_name])
            command.append(clean_text)
            process = subprocess.Popen(command, text=True)
            self._process = process
            self._current_text = clean_text
            self._recent_text = clean_text
            self._recent_text_at = time.time()

        process.wait()

        with self._lock:
            if self._process is process:
                self._process = None
                self._current_text = None
                self._recent_text = clean_text
                self._recent_text_at = time.time()

    def _interrupt_locked(self) -> bool:
        process = self._process
        if self._current_text:
            self._recent_text = self._current_text
            self._recent_text_at = time.time()
        self._current_text = None
        if process is None or process.poll() is not None:
            self._process = None
            return False
        process.terminate()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)
        self._process = None
        return True

    def _clean_spoken_text(self, text: str) -> str:
        clean = " ".join(str(text).split()).strip()
        if not clean:
            return ""
        if clean.startswith(("{", "[")) and clean.endswith(("}", "]")):
            return ""
        if re.search(r"\b(traceback|stack trace|system prompt)\b", clean, re.I):
            return "I hit an internal issue, boss."
        clean = re.sub(r"(?i)(api[_ -]?key|password|secret|token)\s*[:=]\s*\S+", r"\1 redacted", clean)
        clean = re.sub(r"```.*?```", "I included the code in the transcript.", clean, flags=re.S)
        clean = re.sub(r"`([^`]+)`", r"\1", clean)
        clean = re.sub(r"\[([^\]]+)\]\((?:https?://|mailto:)[^)]+\)", r"\1", clean)
        clean = re.sub(r"\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?", ". ", clean)
        clean = re.sub(r"\s*\|\s*", ", ", clean)
        clean = re.sub(r"\s*,\s*\.\s*,?\s*", ". ", clean)
        clean = re.sub(r"^\s*,\s*", "", clean)
        clean = re.sub(r"\s*,\s*$", "", clean)
        clean = re.sub(r"#{1,6}\s+", "", clean)
        clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)
        clean = re.sub(r"__([^_]+)__", r"\1", clean)
        clean = re.sub(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)", r"\1", clean)
        clean = re.sub(r"(?<!_)_([^_\s][^_]*?)_(?!_)", r"\1", clean)
        clean = re.sub(r"https?://(?:www\.)?([^\s/]+)[^\s]*", r"\1", clean)
        clean = re.sub(r"(?<=\d)\s*/\s*(?=\d)", " divided by ", clean)
        clean = re.sub(r"(?<=\d)\s*=\s*(?=\d)", " equals ", clean)
        clean = re.sub(r"(?<=\d)\s*\+\s*(?=\d)", " plus ", clean)
        clean = re.sub(r"\bFRIDAY\b", "Friday", clean)
        replacements = {
            "TTS": "text to speech",
            "STT": "speech to text",
            "JSON": "J son",
            "API": "A P I",
            "URL": "U R L",
            "UI": "U I",
            "CPU": "C P U",
            "RAM": "R A M",
        }
        for term, spoken in replacements.items():
            clean = re.sub(rf"\b{term}\b", spoken, clean)
        clean = clean.replace("localhost", "local host")
        clean = re.sub(r"\s*[-*]\s+", ". ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _resolve_voice_name(self, preferred: str) -> str:
        clean_preferred = preferred.strip()
        if not clean_preferred or not self._say_path:
            return clean_preferred
        try:
            voices = subprocess.run(
                [self._say_path, "-v", "?"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            ).stdout
        except Exception:
            return clean_preferred
        available = {line.split(maxsplit=1)[0] for line in voices.splitlines() if line.strip()}
        if clean_preferred in available:
            return clean_preferred
        for fallback in ("Samantha", "Alex", "Victoria", "Daniel"):
            if fallback in available:
                return fallback
        return ""


MacOSTTS = TTSManager
