from __future__ import annotations

import importlib.util
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from friday.events import EventBus
from friday.state import StateManager
from friday.voice.echo_guard import EchoGuard
from friday.voice.stop_phrase_detector import StopPhraseDetector
from friday.voice.tts_manager import MacOSTTS
from friday.voice.wake_word import WakeWordManager


@dataclass(frozen=True)
class VoiceStatus:
    available: bool
    running: bool
    model_loaded: bool
    last_text: str
    last_error: str
    wake_count: int
    listening_for_command: bool
    audio_level: float
    microphone_stream_open: bool
    input_device: int | None


class WakeWordService:
    def __init__(
        self,
        state: StateManager,
        events: EventBus,
        tts: MacOSTTS,
        on_command: Callable[[str, str], Any] | None = None,
        model_name: str = "base.en",
        chunk_seconds: float = 3.0,
        sample_rate: int = 16000,
        inactivity_timeout: float = 8.0,
        command_silence_seconds: float = 1.5,
        wake_config: dict[str, Any] | None = None,
        beam_size: int = 3,
        initial_prompt: str = "",
        no_speech_threshold: float = 0.45,
    ) -> None:
        self.state = state
        self.events = events
        self.tts = tts
        self.on_command = on_command
        self.model_name = model_name
        self.chunk_seconds = chunk_seconds
        self.sample_rate = sample_rate
        self.inactivity_timeout = inactivity_timeout
        self.command_silence_seconds = command_silence_seconds
        self.beam_size = max(1, int(beam_size))
        self.initial_prompt = (
            initial_prompt.strip()
            or "Friday Jarvis open close switch search Google YouTube Spotify Instagram browser tab app stop cancel pause solve explain upload screenshot answer question"
        )
        self.no_speech_threshold = max(0.1, min(float(no_speech_threshold), 0.95))
        self.echo_guard = EchoGuard()
        self.stop_phrases = StopPhraseDetector()
        self.wake_words = WakeWordManager(wake_config, self.echo_guard)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._model: Any = None
        self._model_lock = threading.RLock()
        self._transcribe_lock = threading.RLock()
        self._model_loaded = False
        self._last_text = ""
        self._last_error = ""
        self._wake_count = 0
        self._last_wake_at = 0.0
        self._listening_for_command = False
        self._audio_level = 0.0
        self._stream_open = False
        self._last_nonzero_audio_at = 0.0
        self._stream_started_at = 0.0
        self._input_device: int | None = None

    @property
    def available(self) -> bool:
        required = ["faster_whisper", "sounddevice", "numpy"]
        return all(importlib.util.find_spec(name) is not None for name in required)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if not self.available:
                self._last_error = "Voice dependencies are not installed."
                self.events.publish("voice_unavailable", {"message": self._last_error})
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="friday-wake-word", daemon=True)
            self._thread.start()
            self.events.publish("voice_started", {"model": self.model_name})

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self.events.publish("voice_stopped", {})

    def status(self) -> VoiceStatus:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return VoiceStatus(
                available=self.available,
                running=running,
                model_loaded=self._model_loaded,
                last_text=self._last_text,
                last_error=self._last_error,
                wake_count=self._wake_count,
                listening_for_command=self._listening_for_command,
                audio_level=self._audio_level,
                microphone_stream_open=self._stream_open,
                input_device=self._input_device,
            )

    def _run(self) -> None:
        try:
            sounddevice, numpy, _WhisperModel = self._imports()
            model = self._ensure_model()
            restart_delay = 0.35
            while not self._stop_event.is_set():
                try:
                    self._run_microphone_stream(sounddevice, numpy, model)
                    restart_delay = 0.35
                except BaseException as exc:
                    if self._stop_event.is_set():
                        break
                    with self._lock:
                        self._last_error = f"Mic stream restarted: {exc}"
                        self._stream_open = False
                    self.events.publish("voice_error", {"message": self._last_error})
                    time.sleep(restart_delay)
                    restart_delay = min(restart_delay * 1.8, 4.0)
        finally:
            with self._lock:
                self._stream_open = False

    def _run_microphone_stream(self, sounddevice: Any, numpy: Any, model: Any) -> None:
        try:
            frames = int(self.sample_rate * self.chunk_seconds)
            audio_queue: queue.Queue[Any] = queue.Queue(maxsize=max(24, int(self.chunk_seconds * 20)))
            blocksize = max(1024, int(self.sample_rate * 0.12))
            input_device = self._default_input_device(sounddevice)
            with self._lock:
                self._input_device = input_device

            def on_audio(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
                if self._stop_event.is_set():
                    return
                try:
                    audio_block = self._sanitize_audio(indata, numpy).copy()
                    if self._audio_peak(audio_block, numpy) > 1e-7:
                        with self._lock:
                            self._last_nonzero_audio_at = time.time()
                    self._set_audio_level(self._calculate_audio_level(audio_block, numpy), publish=False)
                    audio_queue.put_nowait(audio_block)
                except queue.Full:
                    self._drop_oldest_audio_block(audio_queue)
                    try:
                        audio_queue.put_nowait(audio_block)
                    except queue.Full:
                        return
                except Exception:
                    return

            with sounddevice.InputStream(
                device=input_device,
                samplerate=self.sample_rate,
                blocksize=blocksize,
                channels=1,
                dtype="float32",
                callback=on_audio,
            ):
                with self._lock:
                    self._last_error = ""
                    self._stream_open = True
                    self._stream_started_at = time.time()
                    self._last_nonzero_audio_at = self._stream_started_at
                self.events.publish(
                    "voice_microphone_stream_open",
                    {"sample_rate": self.sample_rate, "blocksize": blocksize, "device": input_device},
                )
                while not self._stop_event.is_set():
                    audio_array = self._read_stream_chunk(audio_queue, numpy, frames)
                    if audio_array.size == 0:
                        self._reset_after_timeout()
                        continue
                    self._publish_audio_level(audio_array, numpy)
                    self._raise_if_stream_is_stale(numpy)
                    if self._is_probably_silence(audio_array, numpy):
                        self._reset_after_timeout()
                        continue
                    text = self._transcribe(model, audio_array)
                    self._store_text(text)
                    if self.tts.status().speaking and self._is_interrupt_command(text):
                        self.tts.interrupt()
                        self.events.publish("tts_interrupted", {"interrupted": True, "source": "voice"})
                        self._return_to_idle()
                        continue
                    if text and self.stop_phrases.category(text) and self._should_accept_active_command():
                        self._submit_command(text)
                        continue
                    spoken_text = self._recent_or_current_spoken_text()
                    if self.echo_guard.is_echo(text, spoken_text):
                        self._reset_after_timeout()
                        continue
                    wake_result = self.wake_words.detect_text(text, spoken_text)
                    if wake_result.detected:
                        command = wake_result.trailing_text
                        if self._handle_tts_echo_or_interrupt(text, command):
                            continue
                        self._activate(text, command)
                        if not command:
                            captured_command = self._capture_command_after_wake(
                                sounddevice,
                                numpy,
                                model,
                                audio_queue=audio_queue,
                            )
                            if captured_command:
                                self._submit_command(captured_command)
                    elif text and self._should_accept_active_command():
                        self._submit_command(text)
                    self._reset_after_timeout()
        finally:
            with self._lock:
                self._stream_open = False

    def transcribe_file(self, audio_path: Path) -> str:
        model = self._ensure_model()
        clean_text = self._transcribe_path(model, audio_path, vad_filter=True)
        if not clean_text:
            clean_text = self._transcribe_path(model, audio_path, vad_filter=False)
        self._store_text(clean_text)
        return clean_text

    def _transcribe_path(self, model: Any, audio_path: Path, vad_filter: bool) -> str:
        with self._transcribe_lock:
            segments, _info = model.transcribe(
                str(audio_path),
                language="en",
                beam_size=self.beam_size,
                best_of=max(1, self.beam_size),
                patience=1.15,
                vad_filter=vad_filter,
                vad_parameters={"min_silence_duration_ms": 900, "speech_pad_ms": 300} if vad_filter else None,
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt,
                no_speech_threshold=self.no_speech_threshold,
            )
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return " ".join(text.lower().split())

    def _imports(self) -> tuple[Any, Any, Callable[..., Any]]:
        import numpy
        import sounddevice
        from faster_whisper import WhisperModel

        return sounddevice, numpy, WhisperModel

    def _ensure_model(self) -> Any:
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            with self._lock:
                self._model_loaded = True
                self._last_error = ""
            return self._model

    def _transcribe(self, model: Any, audio: Any) -> str:
        clean_text = self._transcribe_array(model, audio, vad_filter=True)
        if not clean_text:
            clean_text = self._transcribe_array(model, audio, vad_filter=False)
        return clean_text

    def _transcribe_array(self, model: Any, audio: Any, vad_filter: bool) -> str:
        with self._transcribe_lock:
            segments, _info = model.transcribe(
                audio,
                language="en",
                beam_size=self.beam_size,
                best_of=max(1, self.beam_size),
                patience=1.15,
                vad_filter=vad_filter,
                vad_parameters={"min_silence_duration_ms": 900, "speech_pad_ms": 300} if vad_filter else None,
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt,
                no_speech_threshold=self.no_speech_threshold,
            )
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return " ".join(text.lower().split())

    def _store_text(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._last_text = text
        self.events.publish("wake_chunk_transcribed", {"text": text})

    def _handle_tts_echo_or_interrupt(self, text: str, command: str) -> bool:
        if not self.tts.status().speaking:
            return False
        if self.echo_guard.is_echo(text, self._recent_or_current_spoken_text()):
            return True
        clean_command = command.lower().strip()
        if not clean_command:
            return True
        if self._is_interrupt_command(clean_command):
            self.tts.interrupt()
            self.events.publish("tts_interrupted", {"interrupted": True, "source": "voice"})
            self._return_to_idle()
            return True
        if re.search(r"\b(open|launch|start|close|search|google|look up|what|when|where|who|why|how|tell|show|check|send|write|read|create|run|explain|summarize|set|turn)\b", clean_command):
            self.tts.interrupt()
            return False
        return True

    def _recent_or_current_spoken_text(self) -> str | None:
        current = self.tts.get_current_spoken_text()
        if current:
            return current
        get_recent = getattr(self.tts, "get_recent_spoken_text", None)
        if callable(get_recent):
            return get_recent(8.0)
        return None

    def _is_interrupt_command(self, text: str) -> bool:
        return self.stop_phrases.is_tts_interrupt(text) or re.search(
            r"\b(stop|stopped|stop it|stop now|stop speaking|stop talking|stahp|interrupt|cancel|nevermind|never mind|go idle|stop listening|sleep friday|be quiet|mute|pause|enough|hold on|shut up|cut it|cut off|silence|hush|shush|quit talking)\b",
            text.lower(),
        ) is not None

    def _return_to_idle(self) -> None:
        self.state.mute()
        with self._lock:
            self._last_wake_at = 0.0
            self._listening_for_command = False

    def _activate(self, text: str, command: str = "") -> None:
        with self._lock:
            self._wake_count += 1
            self._last_wake_at = time.time()
            self._listening_for_command = not bool(command)
        self.state.activate()
        if command:
            self.events.publish("wake_word_detected", {"text": text, "message": "FRIDAY: Heard you."})
            self._submit_command(command)
        else:
            message = "Yes boss?"
            self.events.publish("wake_word_detected", {"text": text, "message": message})

    def _should_accept_active_command(self) -> bool:
        with self._lock:
            return self._listening_for_command and bool(self._last_wake_at)

    def _submit_command(self, command: str) -> None:
        clean_command = " ".join(command.strip().split())
        if not clean_command or not self.on_command:
            return
        with self._lock:
            self._listening_for_command = False
            self._last_wake_at = time.time()
        self.events.publish("voice_command_detected", {"text": clean_command})
        threading.Thread(
            target=self._run_command_callback,
            args=(clean_command, "voice"),
            name="friday-voice-command",
            daemon=True,
        ).start()

    def _run_command_callback(self, command: str, source: str) -> None:
        try:
            if self.on_command:
                self.on_command(command, source)
        except BaseException as exc:
            with self._lock:
                self._last_error = str(exc)
            self.events.publish("voice_error", {"message": str(exc)})

    def _publish_audio_level(self, audio: Any, numpy: Any) -> None:
        level = self._calculate_audio_level(audio, numpy)
        self._set_audio_level(level, publish=True)

    def _calculate_audio_level(self, audio: Any, numpy: Any) -> float:
        try:
            safe_audio = self._sanitize_audio(audio, numpy).astype("float64", copy=False)
            rms = float(numpy.sqrt(numpy.mean(numpy.square(safe_audio))))
        except Exception:
            rms = 0.0
        return max(0.0, min(rms * 14.0, 1.0))

    def _set_audio_level(self, level: float, publish: bool) -> None:
        with self._lock:
            self._audio_level = level
        if publish:
            self.events.publish("voice_level", {"level": level})

    def _sanitize_audio(self, audio: Any, numpy: Any) -> Any:
        safe_audio = numpy.asarray(audio, dtype=numpy.float32).reshape(-1)
        safe_audio = numpy.nan_to_num(safe_audio, nan=0.0, posinf=0.0, neginf=0.0)
        return numpy.clip(safe_audio, -1.0, 1.0)

    def _audio_peak(self, audio: Any, numpy: Any) -> float:
        try:
            safe_audio = self._sanitize_audio(audio, numpy)
            if safe_audio.size == 0:
                return 0.0
            return float(numpy.max(numpy.abs(safe_audio)))
        except Exception:
            return 0.0

    def _is_probably_silence(self, audio: Any, numpy: Any) -> bool:
        try:
            safe_audio = self._sanitize_audio(audio, numpy).astype("float64", copy=False)
            if safe_audio.size == 0:
                return True
            rms = float(numpy.sqrt(numpy.mean(numpy.square(safe_audio))))
            peak = float(numpy.max(numpy.abs(safe_audio)))
        except Exception:
            return True
        return rms < 0.00035 and peak < 0.007

    def _raise_if_stream_is_stale(self, numpy: Any) -> None:
        with self._lock:
            stream_started_at = self._stream_started_at
            last_nonzero_audio_at = self._last_nonzero_audio_at
        now = time.time()
        if stream_started_at and now - stream_started_at > 12 and now - last_nonzero_audio_at > 12:
            raise RuntimeError("microphone stream is open but receiving only zero audio")

    def _default_input_device(self, sounddevice: Any) -> int | None:
        try:
            default_device = sounddevice.default.device
            if isinstance(default_device, (list, tuple)) and default_device:
                input_device = default_device[0]
            else:
                input_device = default_device
            if input_device is None or int(input_device) < 0:
                raise ValueError("no default input device")
            return int(input_device)
        except Exception:
            pass
        try:
            devices = sounddevice.query_devices()
        except Exception:
            return None
        first_input: int | None = None
        for index, device in enumerate(devices):
            try:
                if int(device.get("max_input_channels", 0)) <= 0:
                    continue
            except AttributeError:
                continue
            if first_input is None:
                first_input = index
            name = str(device.get("name", "")).lower()
            if "microphone" in name or "mic" in name:
                return index
        return first_input

    def _read_stream_chunk(self, audio_queue: queue.Queue[Any], numpy: Any, frames: int) -> Any:
        chunks: list[Any] = []
        collected = 0
        deadline = time.time() + max(self.chunk_seconds + 1.0, 1.5)
        while collected < frames and not self._stop_event.is_set():
            remaining = max(0.05, deadline - time.time())
            if remaining <= 0.05 and not chunks:
                break
            try:
                chunk = audio_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if time.time() >= deadline:
                    break
                continue
            audio_array = self._sanitize_audio(chunk, numpy)
            if audio_array.size == 0:
                continue
            chunks.append(audio_array)
            collected += int(audio_array.size)
        if not chunks:
            return numpy.asarray([], dtype=numpy.float32)
        combined = numpy.concatenate(chunks)
        if combined.size > frames:
            return combined[:frames]
        return combined

    def _drop_oldest_audio_block(self, audio_queue: queue.Queue[Any]) -> None:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            return

    def _drain_audio_queue(self, audio_queue: queue.Queue[Any]) -> None:
        while True:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                return

    def _capture_command_after_wake(
        self,
        sounddevice: Any,
        numpy: Any,
        model: Any,
        audio_queue: queue.Queue[Any] | None = None,
    ) -> str:
        frame_seconds = 0.35
        frames = int(self.sample_rate * frame_seconds)
        started_at = time.time()
        last_voice_at = 0.0
        heard_voice = False
        chunks: list[Any] = []
        if audio_queue is not None:
            self._drain_audio_queue(audio_queue)
        while not self._stop_event.is_set():
            if audio_queue is None:
                audio = sounddevice.rec(frames, samplerate=self.sample_rate, channels=1, dtype="float32")
                sounddevice.wait()
                audio_array = numpy.asarray(audio).reshape(-1)
                audio_array = self._sanitize_audio(audio_array, numpy)
            else:
                audio_array = self._read_stream_chunk(audio_queue, numpy, frames)
                if audio_array.size == 0:
                    continue
            self._publish_audio_level(audio_array, numpy)
            try:
                rms = float(numpy.sqrt(numpy.mean(numpy.square(audio_array.astype("float64", copy=False)))))
            except Exception:
                rms = 0.0
            now = time.time()
            if rms > 0.008:
                heard_voice = True
                last_voice_at = now
                chunks.append(audio_array)
            elif heard_voice:
                chunks.append(audio_array)
            if heard_voice and now - last_voice_at >= self.command_silence_seconds:
                break
            if now - started_at >= self.inactivity_timeout:
                break
        if not chunks:
            return ""
        combined = numpy.concatenate(chunks)
        text = self._transcribe(model, combined)
        self._store_text(text)
        return text

    def _reset_after_timeout(self) -> None:
        with self._lock:
            last_wake_at = self._last_wake_at
        if last_wake_at and time.time() - last_wake_at > self.inactivity_timeout:
            self._return_to_idle()
            self.events.publish("wake_timeout", {"mode": "muted"})
