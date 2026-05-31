from __future__ import annotations

import importlib.util
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Dict


@dataclass(frozen=True)
class STTResult:
    text: str
    confidence: float | None
    language: str | None
    duration_ms: int
    engine: str


class STTManager:
    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        values = config or {}
        self.engine = str(values.get("engine") or "faster-whisper")
        self.model_name = str(values.get("model") or "base.en")
        self.delete_temp_audio = bool(values.get("delete_temp_audio", True))
        self.beam_size = max(1, int(values.get("beam_size", 3)))
        self.best_of = max(1, int(values.get("best_of", 3)))
        self.patience = max(1.0, float(values.get("patience", 1.15)))
        self.no_speech_threshold = max(0.1, min(float(values.get("no_speech_threshold", 0.45)), 0.95))
        self.vad_min_silence_ms = max(200, int(values.get("vad_min_silence_ms", 900)))
        self.vad_speech_pad_ms = max(0, int(values.get("vad_speech_pad_ms", 300)))
        self.initial_prompt = str(values.get("initial_prompt") or "").strip() or None
        self._model: Any = None
        self._model_lock = RLock()
        self._transcribe_lock = RLock()

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def warmup(self) -> None:
        if self.available:
            self._ensure_model()

    def set_model(self, model_name: str) -> None:
        clean = model_name.strip()
        if not clean:
            return
        with self._model_lock:
            if clean != self.model_name:
                self.model_name = clean
                self._model = None

    def transcribe_audio_file(self, path: str | Path) -> STTResult:
        audio_path = Path(path)
        started_at = time.monotonic()
        try:
            text, language = self._transcribe_path(audio_path, vad_filter=True)
            if not text:
                text, language = self._transcribe_path(audio_path, vad_filter=False)
            return STTResult(
                text=self._normalize_text(text),
                confidence=None,
                language=language,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                engine=self.engine,
            )
        finally:
            if self.delete_temp_audio:
                audio_path.unlink(missing_ok=True)

    def transcribe_microphone_chunk(self, audio_bytes: bytes) -> STTResult:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
            audio_file.write(audio_bytes)
            temp_path = Path(audio_file.name)
        return self.transcribe_audio_file(temp_path)

    def _ensure_model(self) -> Any:
        if not self.available:
            raise RuntimeError("faster-whisper is not installed.")
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            return self._model

    def _transcribe_path(self, audio_path: Path, vad_filter: bool) -> tuple[str, str | None]:
        model = self._ensure_model()
        with self._transcribe_lock:
            segments, info = model.transcribe(
                str(audio_path),
                language="en",
                beam_size=self.beam_size,
                best_of=self.best_of,
                patience=self.patience,
                vad_filter=vad_filter,
                vad_parameters={
                    "min_silence_duration_ms": self.vad_min_silence_ms,
                    "speech_pad_ms": self.vad_speech_pad_ms,
                } if vad_filter else None,
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt,
                no_speech_threshold=self.no_speech_threshold,
            )
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return text, getattr(info, "language", None)

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.lower().replace("’", "'").split())
