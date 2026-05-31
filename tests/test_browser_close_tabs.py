from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.local_intents import LocalIntentResolver
from friday.tools.browser import BrowserTool
from friday.tools.router import ToolRouter


class BrowserCloseTabTests(unittest.TestCase):
    def test_close_specific_website_tab_routes_to_browser_close(self) -> None:
        intent = LocalIntentResolver().resolve("close youtube tab")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertEqual(intent.intent["parameters"]["target"], "youtube")
        self.assertEqual(intent.intent["parameters"]["url"], "https://www.youtube.com/")

    def test_close_website_without_app_match_routes_to_browser_close(self) -> None:
        intent = LocalIntentResolver().resolve("close instagram")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertEqual(intent.intent["parameters"]["url"], "https://www.instagram.com/")

    def test_close_app_precedence_still_wins_for_apps(self) -> None:
        intent = LocalIntentResolver().resolve("close chrome")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "close_app")

    def test_close_current_tab_routes_to_browser_close(self) -> None:
        intent = LocalIntentResolver().resolve("close current tab")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertTrue(intent.intent["parameters"]["current"])

    def test_close_plain_tab_routes_to_current_browser_tab(self) -> None:
        intent = LocalIntentResolver().resolve("close tab")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertTrue(intent.intent["parameters"]["current"])

    def test_close_all_matching_tabs_routes_to_browser_close_all(self) -> None:
        intent = LocalIntentResolver().resolve("close all youtube tabs")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertEqual(intent.intent["parameters"]["target"], "youtube")
        self.assertEqual(intent.intent["parameters"]["url"], "https://www.youtube.com/")
        self.assertTrue(intent.intent["parameters"]["all"])

    def test_close_tab_in_specific_browser_keeps_browser_hint(self) -> None:
        intent = LocalIntentResolver().resolve("close youtube tab in chrome")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertEqual(intent.intent["parameters"]["browser"], "chrome")
        self.assertEqual(intent.intent["parameters"]["target"], "youtube")

    def test_tool_router_knows_browser_close_tab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            self.assertIn("browser_close_tab", router.TOOL_COMMANDS)

    def test_browser_close_tab_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = BrowserTool(Path(tmp)).close_tab({"target": "youtube", "all": True, "dry_run": True})

        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["dry_run"])
        self.assertTrue(result["data"]["all"])


if __name__ == "__main__":
    unittest.main()
