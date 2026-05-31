from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.local_intents import LocalIntentResolver
from friday.tools.browser import BrowserTool
from friday.tools.router import ToolRouter


class BrowserSwitchTabTests(unittest.TestCase):
    def test_switch_specific_website_tab_routes_to_browser_switch(self) -> None:
        intent = LocalIntentResolver().resolve("switch to youtube tab")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_switch_tab")
        self.assertEqual(intent.intent["parameters"]["target"], "youtube")
        self.assertEqual(intent.intent["parameters"]["url"], "https://www.youtube.com/")

    def test_switch_tabs_to_major_website_routes_to_browser_switch(self) -> None:
        intent = LocalIntentResolver().resolve("switch tabs to google classroom")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_switch_tab")
        self.assertEqual(intent.intent["parameters"]["url"], "https://classroom.google.com/")

    def test_switch_to_major_website_without_tab_word_still_switches_tab(self) -> None:
        intent = LocalIntentResolver().resolve("switch to instagram")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_switch_tab")
        self.assertEqual(intent.intent["parameters"]["url"], "https://www.instagram.com/")

    def test_open_precedence_is_unchanged(self) -> None:
        intent = LocalIntentResolver().resolve("open youtube")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_open")

    def test_tool_router_knows_browser_switch_tab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            self.assertIn("browser_switch_tab", router.TOOL_COMMANDS)

    def test_browser_switch_tab_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = BrowserTool(Path(tmp)).switch_tab({"target": "youtube", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["dry_run"])


if __name__ == "__main__":
    unittest.main()
