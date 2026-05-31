from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from friday.local_intents import LocalIntentResolver
from friday.tools.music import SpotifyMusicTool, _chromium_spotify_web_play_script, _safari_spotify_web_play_script
from friday.tools.router import ToolRouter


class FakeMusicTool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def play(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(parameters))
        return {
            "success": True,
            "requires_confirmation": False,
            "message": f"Playing {parameters['query']} on Spotify.",
            "data": dict(parameters),
        }


class FakeRunner:
    def __init__(self, fail_commands: set[str] | None = None, stdout_by_command: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_commands = fail_commands or set()
        self.stdout_by_command = stdout_by_command or {}

    def __call__(self, command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        command_name = command[0] if command else ""
        if command_name in self.fail_commands:
            return subprocess.CompletedProcess(command, 1, "", f"{command_name} failed")
        stdout = self.stdout_by_command.get(command_name)
        if stdout is None and command_name == "osascript":
            stdout = "playing\n"
        return subprocess.CompletedProcess(command, 0, stdout or "", "")


class FakeOpener:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], **_: Any) -> object:
        self.calls.append(command)
        return object()


class SpotifyPlayTests(unittest.TestCase):
    def test_open_spotify_and_play_routes_to_music_tool(self) -> None:
        intent = LocalIntentResolver().resolve("open Spotify and play Lil Baby")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "music_play")
        self.assertEqual(intent.intent["parameters"], {"service": "spotify", "query": "lil baby"})

    def test_play_on_spotify_routes_to_music_tool(self) -> None:
        intent = LocalIntentResolver().resolve("play Drake on Spotify")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "music_play")
        self.assertEqual(intent.intent["parameters"]["query"], "drake")

    def test_plain_play_command_defaults_to_spotify(self) -> None:
        intent = LocalIntentResolver().resolve("play Mannequin Challenge by Young Thug")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "music_play")
        self.assertEqual(intent.intent["parameters"], {"service": "spotify", "query": "mannequin challenge by young thug"})

    def test_common_spotify_misspelling_still_routes(self) -> None:
        intent = LocalIntentResolver().resolve("open spotufy and play Travis Scott")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "music_play")
        self.assertEqual(intent.intent["parameters"]["query"], "travis scott")

    def test_open_youtube_and_play_routes_to_media_tool(self) -> None:
        intent = LocalIntentResolver().resolve("open YouTube and play Sum 2 Prove by Lil Baby")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "music_play")
        self.assertEqual(intent.intent["parameters"], {"service": "youtube", "query": "sum 2 prove by lil baby"})

    def test_open_spotify_without_play_still_opens_app(self) -> None:
        intent = LocalIntentResolver().resolve("open Spotify")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "open_app")

    def test_open_spotify_and_play_without_query_asks_follow_up(self) -> None:
        intent = LocalIntentResolver().resolve("open Spotify and play")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "ask_follow_up")
        self.assertIn("What should I play", intent.intent["parameters"]["question"])

    def test_open_spotify_and_search_still_uses_search(self) -> None:
        intent = LocalIntentResolver().resolve("open Spotify and search Lil Baby")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"], {"engine": "spotify", "query": "lil baby"})

    def test_open_youtube_and_search_still_uses_search(self) -> None:
        intent = LocalIntentResolver().resolve("open YouTube and search Lil Baby")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"], {"engine": "youtube", "query": "lil baby"})

    def test_spotify_tool_dry_run_does_not_launch_app(self) -> None:
        result = SpotifyMusicTool(system_name="Darwin").play({"service": "spotify", "query": "Lil Baby", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["search_uri"], "spotify:search:Lil%20Baby")
        self.assertEqual(result["data"]["web_url"], "https://open.spotify.com/search/Lil%20Baby")

    def test_spotify_tool_uses_spotify_app_not_automation_browser(self) -> None:
        runner = FakeRunner()

        with patch("friday.tools.music.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"open", "osascript"} else None):
            result = SpotifyMusicTool(
                system_name="Darwin",
                runner=runner,
                sleeper=lambda _: None,
            ).play({"service": "spotify", "query": "Mannequin Challenge by Young Thug"})

        self.assertTrue(result["success"])
        self.assertEqual(runner.calls[0], ["open", "-a", "Spotify"])
        self.assertEqual(runner.calls[1][0], "osascript")
        self.assertEqual(result["data"]["fallback"], "spotify_app_keyboard")
        self.assertTrue(result["data"]["autoplay_succeeded"])

    def test_spotify_keyboard_must_verify_playing_before_success(self) -> None:
        runner = FakeRunner(stdout_by_command={"osascript": "not_playing\n"})
        opener = FakeOpener()

        with patch("friday.tools.music.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"open", "osascript"} else None):
            result = SpotifyMusicTool(
                system_name="Darwin",
                runner=runner,
                opener=opener,
                sleeper=lambda _: None,
            ).play({"service": "spotify", "query": "Mannequin Challenge by Young Thug"})

        self.assertFalse(result["success"])
        self.assertFalse(result["data"]["autoplay_succeeded"])
        self.assertEqual(result["data"]["fallback"], "spotify_real_browser_search")
        self.assertIn("did not start playing", result["data"]["autoplay_error"])
        self.assertEqual(opener.calls, [["open", "-a", "Google Chrome", "https://open.spotify.com/search/Mannequin%20Challenge%20by%20Young%20Thug"]])

    def test_spotify_web_click_path_runs_when_app_is_missing(self) -> None:
        runner = FakeRunner(fail_commands={"open"}, stdout_by_command={"osascript": "clicked_button:first result\n"})

        with patch("friday.tools.music.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"open", "osascript"} else None):
            result = SpotifyMusicTool(
                system_name="Darwin",
                runner=runner,
                sleeper=lambda _: None,
            ).play({"service": "spotify", "query": "Mannequin Challenge by Young Thug"})

        self.assertTrue(result["success"])
        self.assertEqual(runner.calls[0], ["open", "-a", "Spotify"])
        self.assertEqual(runner.calls[1][0], "osascript")
        self.assertEqual(result["data"]["fallback"], "spotify_web_real_browser_click")
        self.assertTrue(result["data"]["autoplay_succeeded"])

    def test_spotify_web_chrome_script_uses_new_tab_not_friday_tab(self) -> None:
        script = _chromium_spotify_web_play_script(
            "Google Chrome",
            "https://open.spotify.com/search/Lil%20Baby",
            "Lil Baby",
        )

        self.assertIn("make new tab at end of tabs", script)
        self.assertIn("set active tab index to (count of tabs)", script)
        self.assertNotIn("set targetTab to active tab", script)
        self.assertNotIn("set URL of targetTab to targetUrl", script)

    def test_spotify_web_safari_script_uses_new_tab_not_friday_tab(self) -> None:
        script = _safari_spotify_web_play_script(
            "https://open.spotify.com/search/Lil%20Baby",
            "Lil Baby",
        )

        self.assertIn("make new tab with properties", script)
        self.assertIn("set current tab to targetTab", script)
        self.assertNotIn("set URL of current tab", script)

    def test_spotify_tool_falls_back_to_spotify_uri_after_accessibility_failure(self) -> None:
        runner = FakeRunner(fail_commands={"osascript"})
        opener = FakeOpener()

        with patch("friday.tools.music.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"open", "osascript"} else None):
            result = SpotifyMusicTool(
                system_name="Darwin",
                runner=runner,
                opener=opener,
                sleeper=lambda _: None,
            ).play({"service": "spotify", "query": "Mannequin Challenge by Young Thug"})

        self.assertEqual(
            runner.calls,
            [
                ["open", "-a", "Spotify"],
                runner.calls[1],
                ["open", "spotify:search:Mannequin%20Challenge%20by%20Young%20Thug"],
                runner.calls[3],
            ],
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["data"]["autoplay_succeeded"])
        self.assertTrue(result["data"]["spotify_uri_opened"])
        self.assertEqual(result["data"]["fallback"], "spotify_real_browser_search")
        self.assertIn("couldn't click play automatically", result["message"])

    def test_major_media_sites_use_real_browser_not_playwright_profile(self) -> None:
        cases = {
            "soundcloud": "https://soundcloud.com/search?q=Lil+Baby",
            "tiktok": "https://www.tiktok.com/search?q=Lil+Baby",
            "twitch": "https://www.twitch.tv/search?term=Lil+Baby",
        }
        for service, expected_url in cases.items():
            with self.subTest(service=service):
                opener = FakeOpener()

                with patch("friday.tools.music.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "open" else None):
                    result = SpotifyMusicTool(system_name="Darwin", opener=opener).play(
                        {"service": service, "query": "Lil Baby"}
                    )

                self.assertTrue(result["success"])
                self.assertEqual(opener.calls, [["open", "-a", "Google Chrome", expected_url]])
                self.assertEqual(result["data"]["fallback"], "real_browser_search")

    def test_youtube_tool_opens_resolved_first_video_in_existing_chrome(self) -> None:
        opener = FakeOpener()

        result = SpotifyMusicTool(
            system_name="Darwin",
            opener=opener,
            youtube_resolver=lambda query: "https://www.youtube.com/watch?v=xOjy0tL5EuA",
        ).play({"service": "youtube", "query": "sum 2 prove by lil baby"})

        self.assertTrue(result["success"])
        self.assertEqual(opener.calls, [["open", "-a", "Google Chrome", "https://www.youtube.com/watch?v=xOjy0tL5EuA"]])
        self.assertEqual(result["message"], "Playing sum 2 prove by lil baby on YouTube.")
        self.assertEqual(result["data"]["resolved_url"], "https://www.youtube.com/watch?v=xOjy0tL5EuA")

    def test_tool_router_dispatches_music_play(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            fake = FakeMusicTool()
            router.music = fake  # type: ignore[assignment]

            result = router._execute_one("music_play", {"service": "spotify", "query": "lil baby"})

        self.assertTrue(result["success"])
        self.assertEqual(fake.calls, [{"service": "spotify", "query": "lil baby"}])


if __name__ == "__main__":
    unittest.main()
