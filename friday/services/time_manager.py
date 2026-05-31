from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo


TimePeriod = Literal["morning", "afternoon", "evening", "night"]


class TimeManager:
    def __init__(self, timezone: str = "America/Chicago") -> None:
        self.timezone = timezone

    def get_local_time(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def get_time_period(self, dt: datetime | None = None) -> TimePeriod:
        current = dt or self.get_local_time()
        hour = current.hour
        if 5 <= hour <= 11:
            return "morning"
        if 12 <= hour <= 16:
            return "afternoon"
        if 17 <= hour <= 21:
            return "evening"
        return "night"

    def format_time_for_speech(self, dt: datetime) -> str:
        hour = dt.hour % 12 or 12
        minute = dt.minute
        suffix = "AM" if dt.hour < 12 else "PM"
        return f"{hour}:{minute:02d} {suffix}"
