from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from friday.local_intents import LocalIntentResolver
from friday.tools.maps import AppleMapsTool, MapPoint, RouteEstimate
from friday.tools.router import ToolRouter


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeRequester:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, request: Any, **_: Any) -> FakeResponse:
        url = request.full_url
        self.urls.append(url)
        page = (
            '<html><body data-token="fake-token">'
            '<img src="https://snapshot.apple-mapkit.com/api/v1/snapshot?'
            'annotations=%5B%7B%22point%22%3A%2236.3729%2C-94.2088%22%2C%22color%22%3A%22449944%22%7D%2C'
            '%7B%22point%22%3A%2236.3819%2C-94.2030%22%7D%5D&amp;size=450x300">'
            "</body></html>"
        )
        return FakeResponseText(page)


class FakeResponseText:
    def __init__(self, text: str) -> None:
        self.text = text

    def __enter__(self) -> "FakeResponseText":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self) -> bytes:
        return self.text.encode("utf-8")


class FakeOpener:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_: Any) -> object:
        self.calls.append(command)
        return object()


def fake_mapkit_router(origin: MapPoint, destination: MapPoint, mode: str, token: str) -> RouteEstimate:
    assert token == "fake-token"
    assert round(origin.latitude, 4) == 36.3729
    assert round(destination.latitude, 4) == 36.3819
    return RouteEstimate(distance_miles=1.0, duration_minutes=10, source="apple_mapkit")


class MapsDirectionsTests(unittest.TestCase):
    def test_walking_directions_intent_routes_to_maps_tool(self) -> None:
        intent = LocalIntentResolver().resolve("give me walking directions to Crystal Bridges")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "maps_directions")
        self.assertEqual(
            intent.intent["parameters"],
            {"destination": "crystal bridges", "transport_mode": "walking", "open_maps": True},
        )

    def test_distance_question_does_not_force_maps_to_open(self) -> None:
        intent = LocalIntentResolver().resolve("how far is Crystal Bridges by driving")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "maps_directions")
        self.assertEqual(intent.intent["parameters"]["destination"], "crystal bridges")
        self.assertEqual(intent.intent["parameters"]["transport_mode"], "driving")
        self.assertFalse(intent.intent["parameters"]["open_maps"])

    def test_from_to_distance_intent_keeps_origin(self) -> None:
        intent = LocalIntentResolver().resolve("distance from Bentonville High School to Crystal Bridges by walking")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "maps_directions")
        self.assertEqual(intent.intent["parameters"]["origin"], "bentonville high school")
        self.assertEqual(intent.intent["parameters"]["destination"], "crystal bridges")
        self.assertEqual(intent.intent["parameters"]["transport_mode"], "walking")
        self.assertFalse(intent.intent["parameters"]["open_maps"])

    def test_maps_tool_estimates_route_and_builds_apple_maps_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            requester = FakeRequester()
            opener = FakeOpener()
            tool = AppleMapsTool(Path(tmp), opener=opener, requester=requester, mapkit_router=fake_mapkit_router)

            result = tool.directions(
                {
                    "destination": "Crystal Bridges",
                    "origin": "36.3729,-94.2088",
                    "transport_mode": "walking",
                    "dry_run": True,
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual(opener.calls, [])
        self.assertEqual(result["data"]["distance_miles"], 1.0)
        self.assertEqual(result["data"]["duration_minutes"], 10)
        self.assertEqual(result["data"]["estimate_source"], "apple_mapkit")
        self.assertIn("dirflg=w", result["data"]["apple_maps_url"])
        self.assertIn("Apple Maps fastest route is 1.0 miles, about 10 minutes", result["message"])

    def test_maps_tool_caches_repeated_apple_route_estimates(self) -> None:
        calls: list[tuple[MapPoint, MapPoint, str, str]] = []

        def router(origin: MapPoint, destination: MapPoint, mode: str, token: str) -> RouteEstimate:
            calls.append((origin, destination, mode, token))
            return RouteEstimate(distance_miles=1.0, duration_minutes=10, source="apple_mapkit")

        with tempfile.TemporaryDirectory() as tmp:
            requester = FakeRequester()
            tool = AppleMapsTool(Path(tmp), requester=requester, mapkit_router=router)

            first = tool.directions(
                {
                    "destination": "Crystal Bridges",
                    "origin": "36.3729,-94.2088",
                    "transport_mode": "driving",
                    "dry_run": True,
                }
            )
            second = tool.directions(
                {
                    "destination": "crystal bridges",
                    "origin": "36.3729,-94.2088",
                    "transport_mode": "driving",
                    "dry_run": True,
                }
            )

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(requester.urls), 1)

    def test_maps_tool_does_not_estimate_from_config_when_origin_is_live_location(self) -> None:
        calls: list[tuple[MapPoint, MapPoint, str, str]] = []

        def router(origin: MapPoint, destination: MapPoint, mode: str, token: str) -> RouteEstimate:
            calls.append((origin, destination, mode, token))
            return RouteEstimate(distance_miles=4.1, duration_minutes=11, source="apple_mapkit")

        with tempfile.TemporaryDirectory() as tmp:
            requester = FakeRequester()
            tool = AppleMapsTool(Path(tmp), requester=requester, mapkit_router=router)

            result = tool.directions({"destination": "Applebees", "transport_mode": "driving", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(calls, [])
        self.assertNotIn("distance_miles", result["data"])
        self.assertIn("Apple Maps will calculate the live distance", result["message"])

    def test_maps_tool_parses_fastest_route_from_open_apple_maps_text(self) -> None:
        estimate = AppleMapsTool._fastest_route_from_text_values(
            [
                "Directions",
                "6 min",
                "11:51 ETA - 1.9 mi",
                "Fastest",
                "7 min",
                "11:52 ETA - 2.1 mi",
            ]
        )

        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertEqual(estimate.distance_miles, 1.9)
        self.assertEqual(estimate.duration_minutes, 6)
        self.assertEqual(estimate.source, "apple_maps_app")

    def test_maps_tool_uses_open_maps_fastest_route_for_live_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = AppleMapsTool(Path(tmp))
            tool._open_apple_maps = lambda maps_url: tool._success("Opened Apple Maps.", {"url": maps_url})  # type: ignore[method-assign]
            tool._read_open_maps_fastest_route = lambda: RouteEstimate(1.9, 6, "apple_maps_app")  # type: ignore[method-assign]

            result = tool.directions({"destination": "Applebees", "transport_mode": "driving"})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["distance_miles"], 1.9)
        self.assertEqual(result["data"]["duration_minutes"], 6)
        self.assertEqual(result["data"]["estimate_source"], "apple_maps_app")
        self.assertIn("Apple Maps fastest route is 1.9 miles, about 6 minutes", result["message"])

    def test_maps_tool_uses_fastest_apple_route_not_first_or_sum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = AppleMapsTool(Path(tmp))

            estimate = tool._route_estimate_from_mapkit_payload(
                {
                    "routes": [
                        {"distance": 8046.72, "expectedTravelTime": 2400, "name": "Longer route"},
                        {"distance": 3218.688, "expectedTravelTime": 540, "name": "Fastest route"},
                        {"distance": 1609.344, "expectedTravelTime": 900, "name": "Shortest route"},
                    ]
                }
            )

        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertEqual(round(estimate.distance_miles, 1), 2.0)
        self.assertEqual(round(estimate.duration_minutes, 0), 9)

    def test_maps_tool_opens_apple_maps_for_transit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            requester = FakeRequester()
            opener = FakeOpener()
            tool = AppleMapsTool(Path(tmp), opener=opener, requester=requester, mapkit_router=fake_mapkit_router)

            with patch("friday.tools.maps.shutil.which", return_value="/usr/bin/open"):
                result = tool.directions({"destination": "Bentonville Library", "transport_mode": "transit"})

        self.assertTrue(result["success"])
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0][0], "/usr/bin/open")
        self.assertIn("maps://?", opener.calls[0][1])
        self.assertIn("dirflg=r", opener.calls[0][1])

    def test_maps_tool_requires_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = AppleMapsTool(Path(tmp)).directions({"transport_mode": "driving", "dry_run": True})

        self.assertFalse(result["success"])
        self.assertIn("where you want directions", result["message"])

    def test_tool_router_dispatches_maps_directions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            fake_tool = AppleMapsTool(Path(tmp), opener=FakeOpener(), requester=FakeRequester(), mapkit_router=fake_mapkit_router)
            router.maps = fake_tool  # type: ignore[assignment]

            result = router._execute_one("maps_directions", {"destination": "Crystal Bridges", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertIn("Crystal Bridges", result["message"])


if __name__ == "__main__":
    unittest.main()
