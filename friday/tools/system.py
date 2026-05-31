from __future__ import annotations

from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo


class SystemInfoTool:
    def get_time(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        zone_name = str(parameters.get("timezone", ""))
        if not zone_name:
            now = datetime.now().astimezone()
            zone_name = str(now.tzinfo)
        else:
            try:
                zone = ZoneInfo(zone_name)
            except Exception:
                zone = ZoneInfo("UTC")
                zone_name = "UTC"
            now = datetime.now(zone)
        time_text = now.strftime("%-I:%M %p")
        date_text = now.strftime("%A, %B %-d, %Y")
        abbreviation = now.tzname() or zone_name
        return {
            "success": True,
            "requires_confirmation": False,
            "message": "Current time retrieved.",
            "data": {
                "timezone": zone_name,
                "time": time_text,
                "date": date_text,
                "abbreviation": abbreviation,
                "spoken": f"It is {time_text} {abbreviation} on {date_text}.",
            },
        }
