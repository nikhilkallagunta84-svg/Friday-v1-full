from __future__ import annotations

import unittest

from friday.config import FridayConfig
from friday.services.weather_manager import WeatherManager


class WeatherManagerTests(unittest.TestCase):
    def test_open_meteo_weather_codes_are_spoken_naturally(self) -> None:
        config = FridayConfig.load(silent_tts=True)
        manager = WeatherManager(config.location)
        result = manager._parse_open_meteo({"current": {"temperature_2m": 72.4, "weather_code": 0, "wind_speed_10m": 3.2}})

        self.assertEqual(manager.format_weather_for_speech(result), "72 degrees and clear")

    def test_unavailable_weather_speech(self) -> None:
        config = FridayConfig.load(silent_tts=True)
        manager = WeatherManager(config.location)
        result = manager._unavailable("offline")

        self.assertEqual(manager.format_weather_for_speech(result), "Weather is currently unavailable")


if __name__ == "__main__":
    unittest.main()
