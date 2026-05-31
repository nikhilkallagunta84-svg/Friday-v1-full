from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from friday.config import FridayConfig
from friday.services.time_manager import TimeManager
from friday.services.weather_manager import WeatherManager, WeatherResult
from friday.voice.greeting_engine import GreetingEngine


class GreetingEngineTests(unittest.TestCase):
    def test_startup_briefing_uses_configured_acronym_time_and_weather(self) -> None:
        config = FridayConfig.load(silent_tts=True)
        time_manager = TimeManager(config.location.timezone)
        weather_manager = WeatherManager(config.location)
        engine = GreetingEngine(config.personality, config.location, time_manager, weather_manager)
        now = datetime(2026, 5, 8, 20, 42, tzinfo=ZoneInfo(config.location.timezone))
        weather = WeatherResult(temperature_f=63, condition="clear", wind_mph=4, source="test", fetched_at=now)

        briefing = engine.build_startup_briefing(now, weather)

        self.assertIn("Fast Responsive Intelligent Digital Assistant, Year-round", briefing)
        self.assertIn("Good evening, sir.", briefing)
        self.assertIn("The time is 8:42 PM, and the weather in Bentonville, Arkansas is 63 degrees and clear.", briefing)

    def test_weather_failure_keeps_startup_briefing_usable(self) -> None:
        config = FridayConfig.load(silent_tts=True)
        time_manager = TimeManager(config.location.timezone)
        weather_manager = WeatherManager(config.location)
        engine = GreetingEngine(config.personality, config.location, time_manager, weather_manager)
        now = datetime(2026, 5, 8, 15, 14, tzinfo=ZoneInfo(config.location.timezone))
        weather = WeatherResult(None, None, None, "test", now, error="offline")

        briefing = engine.build_startup_briefing(now, weather)

        self.assertIn("Good afternoon, sir.", briefing)
        self.assertIn("Weather is currently unavailable.", briefing)


if __name__ == "__main__":
    unittest.main()
