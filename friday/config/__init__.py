from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


def _safe_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(str(value).strip()) if value is not None and str(value).strip() != "" else default
    except (TypeError, ValueError):
        return default
    return max(low, min(parsed, high))


def _load_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _load_json(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fallback, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return dict(fallback)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    if not isinstance(parsed, dict):
        return dict(fallback)
    merged = dict(fallback)
    merged.update(parsed)
    return merged


DEFAULT_PERSONALITY_CONFIG: Dict[str, Any] = {
    "assistant_name": "FRIDAY",
    "acronym": "Fast Responsive Intelligent Digital Assistant, Year-round",
    "default_address_terms": ["boss", "sir"],
    "tone": "respectful_energetic",
    "formality": "semi_formal",
    "humor": "light",
    "verbosity": "concise",
    "style": "Jarvis-like but natural",
    "startup_intro_enabled": True,
    "weather_briefing_enabled": True,
    "time_briefing_enabled": True,
}

DEFAULT_VOICE_CONFIG: Dict[str, Any] = {
    "always_on_mic": True,
    "wake_word": {
        "enabled": True,
        "primary": "friday",
        "alternates": ["hey friday", "yo friday", "okay friday", "jarvis", "hey jarvis"],
        "confidence_threshold": 0.65,
        "use_openwakeword": True,
        "use_stt_fallback": True,
        "cooldown_ms": 1500,
        "activation_timeout_seconds": 8,
    },
    "stt": {
        "engine": "faster-whisper",
        "model": "base.en",
        "fallback_engine": "whisper.cpp",
        "delete_temp_audio": True,
        "beam_size": 5,
        "best_of": 5,
        "patience": 1.15,
        "no_speech_threshold": 0.45,
        "vad_min_silence_ms": 900,
        "vad_speech_pad_ms": 300,
        "initial_prompt": "Friday Jarvis open close switch search Google YouTube Spotify Instagram browser tab app stop cancel pause solve explain upload screenshot answer question math",
    },
    "tts": {
        "engine": "macos_say",
        "fallback_engine": "pyttsx3",
        "premium_free_engine": "piper",
        "print_before_speak": True,
        "allow_interruption": True,
        "prevent_overlap": True,
        "rate": 185,
        "voice_name": "",
    },
    "vad": {
        "sample_rate": 16000,
        "min_speech_ms": 250,
        "speech_pad_ms": 250,
        "silence_end_ms": 2000,
        "max_command_seconds": 60,
        "follow_up_timeout_seconds": 6,
        "wake_activation_window_seconds": 12,
        "wake_chunk_seconds": 3.0,
    },
}

DEFAULT_LOCATION_CONFIG: Dict[str, Any] = {
    "city": "Bentonville",
    "state": "Arkansas",
    "latitude": 36.3729,
    "longitude": -94.2088,
    "timezone": "America/Chicago",
    "weather_provider": "open_meteo",
}


@dataclass(frozen=True)
class PersonalityConfig:
    assistant_name: str
    acronym: str
    default_address_terms: List[str]
    tone: str
    formality: str
    humor: str
    verbosity: str
    style: str
    startup_intro_enabled: bool
    weather_briefing_enabled: bool
    time_briefing_enabled: bool

    @classmethod
    def from_dict(cls, values: Dict[str, Any]) -> "PersonalityConfig":
        terms = values.get("default_address_terms", ["boss", "sir"])
        if not isinstance(terms, list):
            terms = ["boss", "sir"]
        return cls(
            assistant_name=str(values.get("assistant_name") or "FRIDAY"),
            acronym=str(values.get("acronym") or DEFAULT_PERSONALITY_CONFIG["acronym"]),
            default_address_terms=[str(term) for term in terms if str(term).strip()],
            tone=str(values.get("tone") or "respectful_energetic"),
            formality=str(values.get("formality") or "semi_formal"),
            humor=str(values.get("humor") or "light"),
            verbosity=str(values.get("verbosity") or "concise"),
            style=str(values.get("style") or "Jarvis-like but natural"),
            startup_intro_enabled=bool(values.get("startup_intro_enabled", True)),
            weather_briefing_enabled=bool(values.get("weather_briefing_enabled", True)),
            time_briefing_enabled=bool(values.get("time_briefing_enabled", True)),
        )


@dataclass(frozen=True)
class VoiceCoreConfig:
    values: Dict[str, Any]

    @property
    def wake_word(self) -> Dict[str, Any]:
        value = self.values.get("wake_word", {})
        return value if isinstance(value, dict) else {}

    @property
    def stt(self) -> Dict[str, Any]:
        value = self.values.get("stt", {})
        return value if isinstance(value, dict) else {}

    @property
    def tts(self) -> Dict[str, Any]:
        value = self.values.get("tts", {})
        return value if isinstance(value, dict) else {}

    @property
    def vad(self) -> Dict[str, Any]:
        value = self.values.get("vad", {})
        return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class LocationConfig:
    city: str
    state: str
    latitude: float
    longitude: float
    timezone: str
    weather_provider: str

    @classmethod
    def from_dict(cls, values: Dict[str, Any]) -> "LocationConfig":
        return cls(
            city=str(values.get("city") or "Bentonville"),
            state=str(values.get("state") or "Arkansas"),
            latitude=float(values.get("latitude", 36.3729)),
            longitude=float(values.get("longitude", -94.2088)),
            timezone=str(values.get("timezone") or "America/Chicago"),
            weather_provider=str(values.get("weather_provider") or "open_meteo"),
        )


@dataclass(frozen=True)
class FridayConfig:
    root_dir: Path
    frontend_dir: Path
    transcript_dir: Path
    host: str
    port: int
    silent_tts: bool
    ollama_host: str
    ollama_model: str
    ollama_fast_model: str
    ollama_vision_model: str
    ollama_code_model: str
    resend_api_key: str
    voice_enabled: bool
    whisper_model: str
    personality: PersonalityConfig
    voice_core: VoiceCoreConfig
    location: LocationConfig
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    phone_max_concurrent: int = 5
    phone_persona: str = "respectful"

    @property
    def ollama_default_model(self) -> str:
        return self.ollama_model

    @classmethod
    def load(cls, host: str = "127.0.0.1", port: int = 8765, silent_tts: bool = False) -> "FridayConfig":
        root_dir = Path(__file__).resolve().parents[2]
        dotenv = _load_dotenv(root_dir / ".env")
        for key, value in dotenv.items():
            os.environ.setdefault(key, value)

        config_dir = Path(__file__).resolve().parent
        personality_values = _load_json(config_dir / "personality_config.json", DEFAULT_PERSONALITY_CONFIG)
        voice_values = _load_json(config_dir / "voice_config.json", DEFAULT_VOICE_CONFIG)
        location_values = _load_json(config_dir / "location_config.json", DEFAULT_LOCATION_CONFIG)
        personality = PersonalityConfig.from_dict(personality_values)
        voice_core = VoiceCoreConfig(voice_values)
        location = LocationConfig.from_dict(location_values)
        stt_config = voice_core.stt

        return cls(
            root_dir=root_dir,
            frontend_dir=root_dir / "frontend",
            transcript_dir=root_dir / "transcripts",
            host=host,
            port=port,
            silent_tts=silent_tts or os.environ.get("FRIDAY_SILENT_TTS", "").lower() in {"1", "true", "yes"},
            ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            ollama_model=os.environ.get("FRIDAY_OLLAMA_MODEL", os.environ.get("OLLAMA_MODEL", "qwen3:4b")),
            ollama_fast_model=os.environ.get("FRIDAY_FAST_MODEL", "qwen3:1.7b"),
            ollama_vision_model=os.environ.get("FRIDAY_VISION_MODEL", "llama3.2-vision:11b"),
            ollama_code_model=os.environ.get("FRIDAY_CODE_MODEL", "qwen2.5-coder:7b"),
            resend_api_key=os.environ.get("RESEND_API_KEY", ""),
            voice_enabled=os.environ.get("FRIDAY_ENABLE_VOICE", "1").lower() not in {"0", "false", "no"},
            whisper_model=os.environ.get("FRIDAY_WHISPER_MODEL", str(stt_config.get("model") or "base.en")),
            personality=personality,
            voice_core=voice_core,
            location=location,
            twilio_account_sid=os.environ.get("FRIDAY_TWILIO_ACCOUNT_SID", "").strip(),
            twilio_auth_token=os.environ.get("FRIDAY_TWILIO_AUTH_TOKEN", "").strip(),
            twilio_from_number=os.environ.get("FRIDAY_TWILIO_FROM_NUMBER", "").strip(),
            phone_max_concurrent=_safe_int(os.environ.get("FRIDAY_PHONE_MAX_CONCURRENT"), 5, low=1, high=20),
            phone_persona=os.environ.get("FRIDAY_PHONE_PERSONA", "respectful").strip() or "respectful",
        )

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
