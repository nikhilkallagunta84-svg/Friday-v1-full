from __future__ import annotations

import importlib.util
import queue
from typing import Any


class MicrophoneStream:
    def __init__(self, sample_rate: int = 16000, blocksize: int = 4096, always_on: bool = True) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.always_on = always_on
        self.last_frame_was_speech = False
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._stream: Any = None

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("sounddevice") is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        if not self.available:
            raise RuntimeError("sounddevice is not installed.")
        import sounddevice

        self._stream = sounddevice.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            channels=1,
            dtype="int16",
            callback=self._on_audio,
        )
        self._stream.start()

    def stop(self) -> None:
        stream = self._stream
        if stream is None:
            return
        stream.stop()
        stream.close()
        self._stream = None

    def read_frame(self, timeout: float = 0.5) -> bytes:
        if self._stream is None and self.always_on:
            self.start()
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return b""

    def _on_audio(self, indata: bytes, frames: int, time_info: Any, status: Any) -> None:
        self._queue.put(bytes(indata))
