from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class VADSettings:
    sample_rate: int = 16000
    min_speech_ms: int = 250
    speech_pad_ms: int = 250
    silence_end_ms: int = 1500
    max_command_seconds: int = 60
    follow_up_timeout_seconds: int = 6
    wake_activation_window_seconds: int = 8


class VADManager:
    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        values = config or {}
        self.settings = VADSettings(
            sample_rate=int(values.get("sample_rate", 16000)),
            min_speech_ms=int(values.get("min_speech_ms", 250)),
            speech_pad_ms=int(values.get("speech_pad_ms", 250)),
            silence_end_ms=int(values.get("silence_end_ms", 1500)),
            max_command_seconds=int(values.get("max_command_seconds", 60)),
            follow_up_timeout_seconds=int(values.get("follow_up_timeout_seconds", 6)),
            wake_activation_window_seconds=int(values.get("wake_activation_window_seconds", 8)),
        )
        self.energy_threshold = float(values.get("energy_threshold", 0.008))

    def is_speech(self, audio: Any, numpy: Any) -> bool:
        try:
            rms = float(numpy.sqrt(numpy.mean(numpy.square(audio))))
        except Exception:
            rms = 0.0
        return rms >= self.energy_threshold

    def record_until_silence(self, mic: Any, timeout_seconds: float | None = None) -> bytes:
        timeout = timeout_seconds or self.settings.max_command_seconds
        started_at = time.monotonic()
        last_voice_at = 0.0
        heard_voice = False
        chunks: list[bytes] = []
        while time.monotonic() - started_at <= timeout:
            frame = mic.read_frame()
            if not frame:
                continue
            chunks.append(frame)
            if getattr(mic, "last_frame_was_speech", False):
                heard_voice = True
                last_voice_at = time.monotonic()
            if heard_voice and (time.monotonic() - last_voice_at) * 1000 >= self.settings.silence_end_ms:
                break
        return b"".join(chunks)
