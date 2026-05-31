from __future__ import annotations

from datetime import datetime

from friday.config import LocationConfig, PersonalityConfig
from friday.services.time_manager import TimeManager
from friday.services.weather_manager import WeatherManager, WeatherResult
from friday.voice.personality_engine import PersonalityEngine


GREETING_PHRASES = {
    "morning": [
        "Good morning, sir.",
        "Morning boss.",
        "Good morning boss. What can I get started for you today?",
    ],
    "afternoon": [
        "Good afternoon, sir.",
        "Afternoon boss.",
        "Good afternoon boss. What can I help you knock out?",
    ],
    "evening": [
        "Good evening, sir.",
        "Evening boss.",
        "Good evening boss. What can I get started for you?",
    ],
    "night": [
        "Good night, sir.",
        "You're up late, sir.",
        "Late night work session, boss. What are we building?",
    ],
}


class GreetingEngine:
    def __init__(
        self,
        personality: PersonalityConfig,
        location: LocationConfig,
        time_manager: TimeManager,
        weather_manager: WeatherManager,
    ) -> None:
        self.personality = personality
        self.location = location
        self.time_manager = time_manager
        self.weather_manager = weather_manager
        self.personality_engine = PersonalityEngine(personality)

    def build_startup_briefing(self, now: datetime | None = None, weather: WeatherResult | None = None) -> str:
        current_time = now or self.time_manager.get_local_time()
        weather_result = weather or self.weather_manager.get_current_weather()
        intro = ""
        if self.personality.startup_intro_enabled:
            intro = f"Hello boss. My name is {self.personality.assistant_name} — {self.personality.acronym}."
        period_greeting = self.time_greeting(current_time)
        time_value = self.time_manager.format_time_for_speech(current_time) if self.personality.time_briefing_enabled else ""
        weather_value = ""
        weather_failed = False
        if self.personality.weather_briefing_enabled:
            formatted_weather = self.weather_manager.format_weather_for_speech(weather_result)
            weather_failed = bool(weather_result.error)
            weather_value = formatted_weather
        briefing_text = self._briefing_sentence(time_value, weather_value, weather_failed)
        closing = "What can I get started for you today?"
        return " ".join(part for part in [intro, period_greeting, briefing_text, closing] if part).strip()

    def _briefing_sentence(self, time_value: str, weather_value: str, weather_failed: bool) -> str:
        if time_value and weather_value and not weather_failed:
            return f"The time is {time_value}, and the weather in {self.location.city}, {self.location.state} is {weather_value}."
        if time_value and weather_value:
            return f"The time is {time_value}. {weather_value}."
        if time_value:
            return f"The time is {time_value}."
        if weather_value and not weather_failed:
            return f"The weather in {self.location.city}, {self.location.state} is {weather_value}."
        if weather_value:
            return f"{weather_value}."
        return ""

    def time_greeting(self, now: datetime | None = None) -> str:
        period = self.time_manager.get_time_period(now)
        phrases = GREETING_PHRASES[period]
        if period == "night":
            return phrases[1]
        return phrases[0]

    def short_acknowledgement(self) -> str:
        return self.personality_engine.polish("", context="wake") or "Yes boss?"

    def stop_response(self, text: str) -> str:
        lowered = text.lower()
        if "thank" in lowered or "thanks" in lowered or "appreciate" in lowered:
            return self.personality_engine.polish("", context="gratitude")
        if "night" in lowered or "sleep" in lowered:
            return self.personality_engine.polish("", context="night")
        return self.personality_engine.polish("", context="cancel")
