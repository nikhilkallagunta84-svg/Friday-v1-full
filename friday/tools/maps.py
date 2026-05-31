from __future__ import annotations

import json
import html
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen


TRANSPORT_MODES = {
    "car": "driving",
    "drive": "driving",
    "driving": "driving",
    "walk": "walking",
    "walking": "walking",
    "foot": "walking",
    "bike": "cycling",
    "biking": "cycling",
    "bicycle": "cycling",
    "cycling": "cycling",
    "bus": "transit",
    "train": "transit",
    "public transit": "transit",
    "transit": "transit",
}

APPLE_MAPS_DIRFLAGS = {
    "driving": "d",
    "walking": "w",
    "transit": "r",
}

MAPKIT_TRANSPORT = {
    "driving": "Automobile",
    "walking": "Walking",
    "cycling": "Cycling",
}

_DISTANCE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mi|mile|miles|ft|feet)\b", re.IGNORECASE)
_HOUR_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", re.IGNORECASE)
_MINUTE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)\b", re.IGNORECASE)


@dataclass(frozen=True)
class MapPoint:
    latitude: float
    longitude: float
    label: str


@dataclass(frozen=True)
class RouteEstimate:
    distance_miles: float
    duration_minutes: float | None
    source: str


class AppleMapsTool:
    def __init__(
        self,
        root_dir: Path,
        opener: Callable[..., subprocess.Popen[str]] | None = None,
        requester: Callable[..., Any] | None = None,
        mapkit_router: Callable[[MapPoint, MapPoint, str, str], RouteEstimate | None] | None = None,
    ) -> None:
        self.root_dir = root_dir
        self._opener = opener or subprocess.Popen
        self._requester = requester or urlopen
        self._mapkit_router = mapkit_router
        self._location = self._load_default_location()
        self._route_cache: Dict[tuple[str, str, str], RouteEstimate | None] = {}

    def directions(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        destination = str(parameters.get("destination") or parameters.get("place") or parameters.get("target") or "").strip()
        origin = str(parameters.get("origin") or parameters.get("from") or "").strip()
        mode = _normalize_transport_mode(str(parameters.get("transport_mode") or parameters.get("mode") or parameters.get("transport") or "driving"))
        open_maps = bool(parameters.get("open_maps", True))
        dry_run = bool(parameters.get("dry_run", False))
        if not destination:
            return self._failure("Tell me where you want directions to, sir.", {"transport_mode": mode})

        maps_url = self._apple_maps_url(destination, origin, mode)
        data: Dict[str, Any] = {
            "destination": destination,
            "origin": origin,
            "transport_mode": mode,
            "apple_maps_url": maps_url,
            "open_maps": open_maps,
            "dry_run": dry_run,
        }
        estimate = self._estimate_route(destination, origin, mode)

        opened_maps = False
        if open_maps and not dry_run:
            opened = self._open_apple_maps(maps_url)
            data["opened"] = opened["success"]
            if not opened["success"]:
                return self._failure(f"I found the route, but couldn't open Apple Maps: {opened['message']}", data)
            opened_maps = True
            if not origin:
                estimate = self._read_open_maps_fastest_route()
        else:
            data["opened"] = False

        if estimate:
            data.update(
                {
                    "distance_miles": round(estimate.distance_miles, 1),
                    "duration_minutes": round(estimate.duration_minutes, 0) if estimate.duration_minutes is not None else None,
                    "estimate_source": estimate.source,
                }
            )

        return self._success(self._message(destination, mode, open_maps, opened_maps, estimate), data)

    def _apple_maps_url(self, destination: str, origin: str, mode: str) -> str:
        query: Dict[str, str] = {"daddr": destination}
        if origin:
            query["saddr"] = origin
        dirflag = APPLE_MAPS_DIRFLAGS.get(mode)
        if dirflag:
            query["dirflg"] = dirflag
        return "maps://?" + urlencode(query)

    def _open_apple_maps(self, maps_url: str) -> Dict[str, Any]:
        opener = shutil.which("open")
        if not opener:
            return self._failure("macOS open command is unavailable.", {"url": maps_url})
        try:
            self._opener([opener, maps_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return self._failure(str(exc), {"url": maps_url})
        return self._success("Opened Apple Maps.", {"url": maps_url})

    def _estimate_route(self, destination: str, origin: str, mode: str) -> RouteEstimate | None:
        if mode == "transit" or not origin.strip():
            return None
        cache_key = (" ".join(destination.lower().split()), " ".join(origin.lower().split()), mode)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]
        context = self._apple_directions_context(destination, origin, mode)
        if not context:
            self._route_cache[cache_key] = None
            return None
        token = self._extract_mapkit_token(context)
        points = self._parse_apple_direction_points(context)
        if not token or len(points) < 2:
            self._route_cache[cache_key] = None
            return None
        origin_point, destination_point = points[0], points[-1]
        router = self._mapkit_router or self._mapkit_route
        estimate = router(origin_point, destination_point, mode, token)
        self._route_cache[cache_key] = estimate
        return estimate

    def _apple_directions_context(self, destination: str, origin: str, mode: str) -> str:
        query: Dict[str, str] = {"daddr": destination}
        if origin:
            query["saddr"] = origin
        dirflag = APPLE_MAPS_DIRFLAGS.get(mode)
        if dirflag:
            query["dirflg"] = dirflag
        url = "https://maps.apple.com/?" + urlencode(query)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"})
        try:
            with self._requester(request, timeout=8) as response:
                return response.read().decode("utf-8", errors="ignore")
        except BaseException:
            return ""

    def _extract_mapkit_token(self, page_html: str) -> str:
        match = re.search(r'data-token="([^"]+)"', page_html)
        return html.unescape(match.group(1)) if match else ""

    def _parse_apple_direction_points(self, page_html: str) -> list[MapPoint]:
        decoded = html.unescape(page_html)
        annotation_match = re.search(r"annotations=([^&]+)", decoded)
        if not annotation_match:
            return []
        try:
            annotations = json.loads(unquote(annotation_match.group(1)))
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        points: list[MapPoint] = []
        if not isinstance(annotations, list):
            return points
        for index, item in enumerate(annotations):
            if not isinstance(item, dict):
                continue
            raw_point = str(item.get("point") or "")
            try:
                lat_text, lon_text = raw_point.split(",", 1)
                points.append(MapPoint(latitude=float(lat_text), longitude=float(lon_text), label=f"apple_maps_point_{index}"))
            except ValueError:
                continue
        return points

    def _mapkit_route(self, origin: MapPoint, destination: MapPoint, mode: str, token: str) -> RouteEstimate | None:
        transport = MAPKIT_TRANSPORT.get(mode)
        if not transport:
            return None
        try:
            from playwright.sync_api import sync_playwright
        except BaseException:
            return None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto("https://maps.apple.com/", wait_until="domcontentloaded", timeout=20000)
                    result = page.evaluate(
                        """
                        async ({ token, origin, destination, transport }) => {
                          mapkit.init({ authorizationCallback: done => done(token) });
                          await new Promise(resolve => setTimeout(resolve, 750));
                          const directions = new mapkit.Directions();
                          const request = {
                            origin: new mapkit.Coordinate(origin.latitude, origin.longitude),
                            destination: new mapkit.Coordinate(destination.latitude, destination.longitude),
                            transportType: mapkit.Directions.Transport[transport]
                          };
                          return await new Promise((resolve, reject) => {
                            directions.route(request, (error, data) => {
                              if (error) {
                                reject(String(error.message || error));
                                return;
                              }
                              const routes = Array.isArray(data.routes) ? data.routes : [];
                              if (!routes.length) {
                                reject("Apple Maps returned no routes.");
                                return;
                              }
                              resolve({
                                routes: routes.map((route, index) => ({
                                  index,
                                  distance: route.distance,
                                  expectedTravelTime: route.expectedTravelTime,
                                  name: route.name || "",
                                  transportType: route.transportType || ""
                                }))
                              });
                            });
                          });
                        }
                        """,
                        {
                            "token": token,
                            "origin": {"latitude": origin.latitude, "longitude": origin.longitude},
                            "destination": {"latitude": destination.latitude, "longitude": destination.longitude},
                            "transport": transport,
                        },
                    )
                finally:
                    browser.close()
        except BaseException:
            return None
        return self._route_estimate_from_mapkit_payload(result)

    def _route_estimate_from_mapkit_payload(self, payload: Any) -> RouteEstimate | None:
        if not isinstance(payload, dict):
            return None
        selected_route = self._select_fastest_route(payload.get("routes"))
        if not selected_route:
            return None
        try:
            meters = float(selected_route["distance"])
        except (KeyError, TypeError, ValueError):
            return None
        seconds = _coerce_positive_number(selected_route.get("expectedTravelTime"))
        duration_minutes = seconds / 60 if seconds is not None else None
        return RouteEstimate(distance_miles=meters / 1609.344, duration_minutes=duration_minutes, source="apple_mapkit")

    @staticmethod
    def _select_fastest_route(routes: Any) -> Dict[str, Any] | None:
        if not isinstance(routes, list):
            return None

        candidates: list[tuple[float, float, Dict[str, Any]]] = []
        for route in routes:
            if not isinstance(route, dict):
                continue
            distance = _coerce_positive_number(route.get("distance"))
            if distance is None:
                continue
            duration = _coerce_positive_number(route.get("expectedTravelTime"))
            duration_sort = duration if duration is not None else float("inf")
            candidates.append((duration_sort, distance, route))

        if not candidates:
            return None
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
        return candidates[0][2]

    def _read_open_maps_fastest_route(self) -> RouteEstimate | None:
        time.sleep(1.0)
        script = """
        set outputLines to {}
        tell application "System Events"
          if not (exists process "Maps") then return ""
          tell process "Maps"
            if not (exists window 1) then return ""
            set uiItems to entire contents of window 1
            repeat with uiItem in uiItems
              try
                if class of uiItem is static text then
                  set itemValue to value of uiItem as text
                  if itemValue is not "" then set end of outputLines to itemValue
                end if
              end try
            end repeat
          end tell
        end tell
        set AppleScript's text item delimiters to linefeed
        return outputLines as text
        """
        try:
            completed = subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        values = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        return self._fastest_route_from_text_values(values)

    @staticmethod
    def _fastest_route_from_text_values(values: list[str]) -> RouteEstimate | None:
        candidates: list[tuple[int, float, float, RouteEstimate]] = []
        for index, value in enumerate(values):
            duration = _parse_route_duration_minutes(value)
            if duration is None:
                continue
            window = values[index : index + 5]
            distance = None
            for item in window:
                distance = _parse_route_distance_miles(item)
                if distance is not None:
                    break
            if distance is None:
                continue
            fastest_rank = 0 if any("fastest" in item.lower() for item in window) else 1
            estimate = RouteEstimate(distance_miles=distance, duration_minutes=duration, source="apple_maps_app")
            candidates.append((fastest_rank, duration, distance, estimate))

        if not candidates:
            return None
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1], candidate[2]))
        return candidates[0][3]

    def _load_default_location(self) -> Dict[str, Any]:
        path = self.root_dir / "friday" / "config" / "location_config.json"
        fallback = {"city": "Bentonville", "state": "Arkansas", "latitude": 36.3729, "longitude": -94.2088}
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback
        if not isinstance(parsed, dict):
            return fallback
        values = dict(fallback)
        values.update(parsed)
        return values

    def _message(self, destination: str, mode: str, open_maps: bool, opened_maps: bool, estimate: RouteEstimate | None) -> str:
        mode_label = _transport_label(mode)
        if opened_maps:
            action = "Opened Apple Maps"
        elif open_maps:
            action = "Prepared Apple Maps directions"
        else:
            action = "Checked the route"
        if estimate:
            distance = f"{estimate.distance_miles:.1f} miles"
            if estimate.duration_minutes is not None:
                duration = _format_duration(estimate.duration_minutes)
                source = "Apple Maps fastest route" if estimate.source in {"apple_mapkit", "apple_maps_app"} else "Estimated distance"
                return f"{action} to {destination} by {mode_label}. {source} is {distance}, about {duration}."
            source = "Apple Maps fastest route" if estimate.source in {"apple_mapkit", "apple_maps_app"} else "Estimated distance"
            return f"{action} to {destination} by {mode_label}. {source} is {distance}."
        if opened_maps:
            return f"{action} to {destination} by {mode_label}. Use the fastest route shown in Apple Maps for the live distance and ETA."
        return f"{action} to {destination} by {mode_label}. Apple Maps will calculate the live distance and ETA."

    def _success(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "requires_confirmation": False, "message": message, "data": data}

    def _failure(self, message: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "requires_confirmation": False, "message": message, "data": data}


def _normalize_transport_mode(value: str) -> str:
    clean = " ".join(value.lower().strip().split())
    return TRANSPORT_MODES.get(clean, clean if clean in {"driving", "walking", "cycling", "transit"} else "driving")


def _transport_label(mode: str) -> str:
    return {
        "driving": "driving",
        "walking": "walking",
        "cycling": "cycling",
        "transit": "transit",
    }.get(mode, "driving")


def _coerce_positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _parse_route_distance_miles(value: str) -> float | None:
    match = _DISTANCE_RE.search(value)
    if not match:
        return None
    amount = _coerce_positive_number(match.group(1))
    if amount is None:
        return None
    unit = match.group(2).lower()
    if unit in {"ft", "feet"}:
        return amount / 5280
    return amount


def _parse_route_duration_minutes(value: str) -> float | None:
    hours = 0.0
    minutes = 0.0
    hour_match = _HOUR_RE.search(value)
    minute_match = _MINUTE_RE.search(value)
    if hour_match:
        parsed_hours = _coerce_positive_number(hour_match.group(1))
        if parsed_hours is not None:
            hours = parsed_hours
    if minute_match:
        parsed_minutes = _coerce_positive_number(minute_match.group(1))
        if parsed_minutes is not None:
            minutes = parsed_minutes
    if not hour_match and not minute_match:
        return None
    return hours * 60 + minutes


def _format_duration(minutes: float) -> str:
    rounded = max(1, int(round(minutes)))
    if rounded < 60:
        return f"{rounded} minute{'s' if rounded != 1 else ''}"
    hours, mins = divmod(rounded, 60)
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {mins} minutes"
