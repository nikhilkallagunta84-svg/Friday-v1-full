from __future__ import annotations

import json
import mimetypes
import os
import signal
import tempfile
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from friday.assistant import FridayAssistant
from friday.config import FridayConfig
from friday.events import Event, EventBus
from friday.model_manager import ModelManager
from friday.ollama_engine import OllamaClient, OllamaTimeout, OllamaUnavailable
from friday.phone.call_planner import CallPlanner
from friday.phone.drivers import SimulatedPhoneDriver, TwilioPhoneDriver
from friday.phone.manager import PhoneCallManager
from friday.services import TimeManager, VisionManager, VisualContextManager, WeatherManager
from friday.state import StateManager
from friday.tools import ToolRouter
from friday.transcript import TranscriptLogger
from friday.tts import MacOSTTS
from friday.voice.greeting_engine import GreetingEngine
from friday.voice.stt_manager import STTManager
from friday.voice import WakeWordService


class FridayRuntime:
    def __init__(self, config: FridayConfig) -> None:
        self.config = config
        self.events = EventBus()
        self.state = StateManager()
        self.tts = MacOSTTS(silent=config.silent_tts, config=config.voice_core.tts)
        self.stt = STTManager(config.voice_core.stt)
        self.transcript = TranscriptLogger(config.transcript_dir)
        self.ollama = OllamaClient(
            config.ollama_host,
            config.ollama_model,
            assistant_name=config.personality.assistant_name,
            assistant_acronym=config.personality.acronym,
        )
        self.model_manager = ModelManager(
            self.ollama,
            config.ollama_default_model,
            config.ollama_fast_model,
            config.ollama_vision_model,
            code_model=config.ollama_code_model,
        )
        self.phone_manager = self._build_phone_manager(config)
        self.tools = ToolRouter(
            config.root_dir,
            config.resend_api_key,
            default_model=config.ollama_default_model,
            vision_model=config.ollama_vision_model,
            code_model=config.ollama_code_model,
            ollama_host=config.ollama_host,
            ollama=self.ollama,
            phone_manager=self.phone_manager,
        )
        self.time_manager = TimeManager(config.location.timezone)
        self.weather_manager = WeatherManager(config.location)
        self.vision = VisionManager(self.ollama, preferred_vision_model=config.ollama_vision_model)
        self.visual_context = VisualContextManager()
        self.greeting_engine = GreetingEngine(config.personality, config.location, self.time_manager, self.weather_manager)
        self.assistant = FridayAssistant(
            self.state,
            self.tts,
            self.transcript,
            self.events,
            self.ollama,
            self.tools,
            assistant_name=config.personality.assistant_name,
            assistant_acronym=config.personality.acronym,
            personality=config.personality,
            publish_ready=False,
            model_manager=self.model_manager,
            timezone=config.location.timezone,
        )
        self.voice = WakeWordService(
            self.state,
            self.events,
            self.tts,
            on_command=self.assistant.submit_text,
            model_name=config.whisper_model,
            chunk_seconds=float(config.voice_core.vad.get("wake_chunk_seconds", 3.0)),
            wake_config=config.voice_core.wake_word,
            inactivity_timeout=float(config.voice_core.vad.get("wake_activation_window_seconds", 8)),
            command_silence_seconds=float(config.voice_core.vad.get("silence_end_ms", 800)) / 1000.0,
            beam_size=int(config.voice_core.stt.get("beam_size", 3)),
            initial_prompt=str(config.voice_core.stt.get("initial_prompt", "")),
            no_speech_threshold=float(config.voice_core.stt.get("no_speech_threshold", 0.45)),
        )
        self._last_greeting_text = ""
        self._last_greeting_at = 0.0
        self._greeting_lock = threading.RLock()
        for warning in self.model_manager.startup_check():
            print(f"[FRIDAY model check] {warning}")
        if config.voice_enabled:
            self.voice.start()
        self._announce_startup()
        
    def _announce_startup(self) -> None:
        self.announce_greeting("startup", force=True)

    def _build_phone_manager(self, config: FridayConfig) -> PhoneCallManager:
        """Construct the phone subsystem. Twilio activates when all 3 env vars are set."""
        planner = CallPlanner(
            self.ollama,
            model_manager=self.model_manager,
            default_persona=config.phone_persona,
        )
        if config.twilio_account_sid and config.twilio_auth_token and config.twilio_from_number:
            driver = TwilioPhoneDriver(
                account_sid=config.twilio_account_sid,
                auth_token=config.twilio_auth_token,
                from_number=config.twilio_from_number,
            )
            print("[FRIDAY phone] Twilio configured — live calls will require per-call confirmation.")
        else:
            driver = SimulatedPhoneDriver(self.ollama, model_manager=self.model_manager)
        log_path = config.root_dir / "logs" / "phone-calls.jsonl"
        return PhoneCallManager(
            planner=planner,
            driver=driver,
            events=self.events,
            logger_path=log_path,
            max_concurrent=config.phone_max_concurrent,
        )

    def announce_greeting(self, source: str, force: bool = False) -> Dict[str, Any]:
        with self._greeting_lock:
            now = time.time()
            if not force and self._last_greeting_text and now - self._last_greeting_at < 10:
                return {"message": self._last_greeting_text, "spoken": False}
            startup_text = self.greeting_engine.build_startup_briefing()
            self._last_greeting_text = startup_text
            self._last_greeting_at = now
        self.events.publish("assistant_ready", {"message": startup_text, "source": source})
        threading.Thread(target=self.tts.speak, args=(startup_text,), name=f"friday-{source}-tts", daemon=True).start()
        return {"message": startup_text, "spoken": True}


class FridayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler: type[BaseHTTPRequestHandler], runtime: FridayRuntime):
        super().__init__(server_address, handler)
        self.runtime = runtime


class FridayRequestHandler(BaseHTTPRequestHandler):
    server: FridayHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            status = self.server.runtime.assistant.status()
            status["voice"] = asdict(self.server.runtime.voice.status())
            self._send_json(status)
            return
        if parsed.path == "/api/events":
            query = parse_qs(parsed.query)
            last_seen = int(query.get("since", ["0"])[0])
            events = self.server.runtime.events.wait_after(last_seen)
            self._send_json({"events": [self._event_to_dict(event) for event in events]})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/message":
            payload = self._read_json()
            text = str(payload.get("text", ""))
            source = str(payload.get("source", "text"))
            try:
                if self.server.runtime.visual_context.should_use_for_prompt(text):
                    result = self._handle_visual_follow_up(text)
                else:
                    result = self.server.runtime.assistant.submit_text(text, source=source)
                self._send_json(asdict(result))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except OllamaTimeout as exc:
                # Gateway timeout — the model is alive but didn't finish in time.
                self._send_json(
                    {"error": str(exc), "kind": "timeout", "retryable": True},
                    HTTPStatus.GATEWAY_TIMEOUT,
                )
            except OllamaUnavailable as exc:
                # Service unavailable — Ollama isn't reachable or returned bad data.
                self._send_json(
                    {"error": str(exc), "kind": "ollama_unavailable", "retryable": True},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            except BaseException as exc:
                self._send_json(
                    {"error": f"FRIDAY failed to process input: {exc}", "kind": "internal"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if parsed.path == "/api/interrupt":
            stop_result = self.server.runtime.tools.emergency_stop.trigger_from_hotkey("ui stop button")
            interrupted = self.server.runtime.assistant.interrupt_tts()
            self._send_json({"interrupted": interrupted, "control": self.server.runtime.tools.control_status(), "message": stop_result.message})
            return
        if parsed.path == "/api/silent-tts":
            payload = self._read_json()
            silent = bool(payload.get("silent", False))
            self.server.runtime.tts.set_silent(silent)
            self._send_json({"tts": asdict(self.server.runtime.tts.status())})
            return
        if parsed.path == "/api/browser-greeting":
            self._send_json(self.server.runtime.announce_greeting("browser-open"))
            return
        if parsed.path == "/api/stt":
            self._handle_browser_stt()
            return
        if parsed.path == "/api/file-analysis":
            self._handle_file_analysis()
            return
        if parsed.path == "/api/voice/start":
            self.server.runtime.voice.start()
            self._send_json({"voice": asdict(self.server.runtime.voice.status())})
            return
        if parsed.path == "/api/voice/stop":
            self.server.runtime.voice.stop()
            self._send_json({"voice": asdict(self.server.runtime.voice.status())})
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        if not body.strip():
            return {}
        return json.loads(body)

    def _handle_browser_stt(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json({"error": "Audio body is empty."}, HTTPStatus.BAD_REQUEST)
            return
        if length > 12_000_000:
            self._send_json({"error": "Audio chunk is too large."}, HTTPStatus.BAD_REQUEST)
            return
        content_type = self.headers.get("Content-Type", "")
        client_level = self.headers.get("X-Friday-Audio-Level", "")
        if "webm" in content_type:
            suffix = ".webm"
        elif "mp4" in content_type or "m4a" in content_type:
            suffix = ".m4a"
        elif "ogg" in content_type:
            suffix = ".ogg"
        else:
            suffix = ".wav"
        audio_bytes = self.rfile.read(length)
        temp_path = None
        started_at = time.monotonic()
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
                audio_file.write(audio_bytes)
                temp_path = Path(audio_file.name)
            result = self.server.runtime.stt.transcribe_audio_file(temp_path)
            temp_path = None
            text = result.text
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            self._send_json({
                "text": text,
                "engine": result.engine,
                "bytes": length,
                "content_type": content_type,
                "client_audio_level": client_level,
                "elapsed_ms": elapsed_ms,
                "language": result.language,
            })
        except BaseException as exc:
            message = str(exc)
            if "Invalid data found" in message:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                self._send_json({
                    "text": "",
                    "engine": "browser-local-faster-whisper",
                    "bytes": length,
                    "content_type": content_type,
                    "client_audio_level": client_level,
                    "elapsed_ms": elapsed_ms,
                    "warning": "Ignored an invalid browser audio chunk.",
                })
                return
            self._send_json({"error": f"STT failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def _handle_file_analysis(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json({"error": "Upload payload is empty."}, HTTPStatus.BAD_REQUEST)
            return
        if length > 26_000_000:
            self._send_json({"error": "Upload is too large. Try a shorter video clip or a smaller screenshot."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = self._read_json()
        except BaseException as exc:
            self._send_json({"error": f"Could not read upload payload: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        file_name = str(payload.get("file_name") or "uploaded file").strip()
        mime_type = str(payload.get("mime_type") or "application/octet-stream").strip()
        prompt = str(payload.get("prompt") or "Analyze this file.").strip()
        image_data_urls = payload.get("image_data_urls", [])
        frame_labels = payload.get("frame_labels", [])
        if not isinstance(image_data_urls, list):
            image_data_urls = []
        if not isinstance(frame_labels, list):
            frame_labels = []
        if not (mime_type.startswith("image/") or mime_type.startswith("video/")):
            self._send_json({"error": "FRIDAY can analyze screenshots/images and videos only right now."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            vision_result = self.server.runtime.vision.analyze_file(
                file_name=file_name,
                mime_type=mime_type,
                prompt=prompt,
                image_data_urls=[str(item) for item in image_data_urls],
                frame_labels=[str(item) for item in frame_labels],
            )
            self.server.runtime.visual_context.store(
                file_name=vision_result.file_name,
                mime_type=vision_result.mime_type,
                image_data_urls=[str(item) for item in image_data_urls],
                frame_labels=[str(item) for item in frame_labels],
                analysis=vision_result.response,
                vision_model=vision_result.model,
            )
            result = self.server.runtime.assistant.submit_file_analysis(
                prompt=prompt,
                file_name=file_name,
                mime_type=mime_type,
                vision_model=vision_result.model,
                frame_count=vision_result.frame_count,
                analysis=vision_result.response,
            )
            self._send_json({
                **asdict(result),
                "file": {
                    "name": vision_result.file_name,
                    "mime_type": vision_result.mime_type,
                    "vision_model": vision_result.model,
                    "frame_count": vision_result.frame_count,
                },
            })
        except BaseException as exc:
            self._send_json({"error": f"FRIDAY could not analyze that file: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_visual_follow_up(self, text: str):
        context = self.server.runtime.visual_context.current()
        if not context:
            return self.server.runtime.assistant.submit_text(text, source="text")
        follow_up_prompt = self.server.runtime.visual_context.build_follow_up_prompt(text)
        vision_result = self.server.runtime.vision.analyze_file(
            file_name=context.file_name,
            mime_type=context.mime_type,
            prompt=follow_up_prompt,
            image_data_urls=context.image_data_urls,
            frame_labels=context.frame_labels,
        )
        self.server.runtime.visual_context.store(
            file_name=context.file_name,
            mime_type=context.mime_type,
            image_data_urls=context.image_data_urls,
            frame_labels=context.frame_labels,
            analysis=vision_result.response,
            vision_model=vision_result.model,
        )
        return self.server.runtime.assistant.submit_file_analysis(
            prompt=text,
            file_name=context.file_name,
            mime_type=context.mime_type,
            vision_model=vision_result.model,
            frame_count=vision_result.frame_count,
            analysis=vision_result.response,
        )

    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except BrokenPipeError:
            return

    def _serve_static(self, request_path: str) -> None:
        frontend_dir = self.server.runtime.config.frontend_dir
        relative = "index.html" if request_path in {"/", ""} else request_path.lstrip("/")
        target = (frontend_dir / relative).resolve()
        if frontend_dir.resolve() not in target.parents and target != frontend_dir.resolve():
            self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
            return
        if not target.exists() or not target.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return

    def _event_to_dict(self, event: Event) -> Dict[str, Any]:
        return {
            "id": event.id,
            "kind": event.kind,
            "payload": event.payload,
            "created_at": event.created_at,
        }


def run_server(config: FridayConfig) -> None:
    runtime = FridayRuntime(config)
    server = FridayHTTPServer((config.host, config.port), FridayRequestHandler, runtime)

    def stop_server(signum: int, frame: Any) -> None:
        runtime.voice.stop()
        runtime.tts.interrupt()
        threading.Thread(target=server.shutdown, name="friday-http-shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)

    print(f"FRIDAY is online at {config.base_url}")
    print("Run Ctrl-C to stop.")
    server.serve_forever()
