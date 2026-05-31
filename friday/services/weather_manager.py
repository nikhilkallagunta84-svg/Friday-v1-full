from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from urllib.parse import urlencode

from friday.config import LocationConfig


@dataclass(frozen=True)
class WeatherResult:
    temperature_f: float | None
    condition: str | None
    wind_mph: float | None
    source: str
    fetched_at: datetime
    error: str | None = None


class WeatherManager:
    def __init__(self, location: LocationConfig, timeout_seconds: float = 2.5) -> None:
        self.location = location
        self.timeout_seconds = timeout_seconds
        self._cache: WeatherResult | None = None
        self._cache_ttl = timedelta(minutes=10)

    def get_current_weather(self) -> WeatherResult:
        now = datetime.now(timezone.utc)
        if self._cache and now - self._cache.fetched_at < self._cache_ttl:
            return self._cache
        if self.location.weather_provider != "open_meteo":
            return self._unavailable(f"Unsupported weather provider: {self.location.weather_provider}")
        query = urlencode(
            {
                "latitude": self.location.latitude,
                "longitude": self.location.longitude,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": self.location.timezone,
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{query}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = self._parse_open_meteo(payload)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            result = self._unavailable(str(exc))
        self._cache = result
        return result

    def format_weather_for_speech(self, result: WeatherResult) -> str:
        if result.error or result.temperature_f is None:
            return "Weather is currently unavailable"
        temperature = round(result.temperature_f)
        condition = result.condition or "conditions unavailable"
        return f"{temperature} degrees and {condition}"

    def _parse_open_meteo(self, payload: Dict[str, Any]) -> WeatherResult:
        current = payload.get("current", {})
        if not isinstance(current, dict):
            return self._unavailable("Open-Meteo response did not include current weather.")
        temperature = current.get("temperature_2m")
        wind = current.get("wind_speed_10m")
        code = current.get("weather_code")
        return WeatherResult(
            temperature_f=float(temperature) if temperature is not None else None,
            condition=self._condition_from_code(int(code)) if code is not None else None,
            wind_mph=float(wind) if wind is not None else None,
            source="open_meteo",
            fetched_at=datetime.now(timezone.utc),
        )

    def _unavailable(self, error: str) -> WeatherResult:
        return WeatherResult(
            temperature_f=None,
            condition=None,
            wind_mph=None,
            source="open_meteo",
            fetched_at=datetime.now(timezone.utc),
            error=error,
        )

    def _condition_from_code(self, code: int) -> str:
        if code == 0:
            return "clear"
        if code in {1, 2}:
            return "partly cloudy"
        if code == 3:
            return "overcast"
        if code in {45, 48}:
            return "foggy"
        if code in {51, 53, 55, 56, 57}:
            return "drizzling"
        if code in {61, 63, 65, 66, 67, 80, 81, 82}:
            return "rainy"
        if code in {71, 73, 75, 77, 85, 86}:
            return "snowy"
        if code in {95, 96, 99}:
            return "stormy"
        return "conditions unavailable"
