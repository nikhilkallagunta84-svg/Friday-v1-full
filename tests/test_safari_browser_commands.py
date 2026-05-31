from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from friday.local_intents import LocalIntentResolver
from friday.tools.browser import BrowserTool
from friday.tools.router import ToolRouter


class FakeBrowserTool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Dict[str, Any]]] = []

    def open_page(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(("open_page", dict(parameters)))
        return {"success": True, "requires_confirmation": False, "message": "Opened URL in Safari.", "data": dict(parameters)}

    def search(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(("search", dict(parameters)))
        return {"success": True, "requires_confirmation": False, "message": "Opened google search results in Safari.", "data": dict(parameters)}


class SafariBrowserCommandTests(unittest.TestCase):
    def test_open_website_in_safari_preserves_browser_hint(self) -> None:
        intent = LocalIntentResolver().resolve("open youtube in safari")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_open")
        self.assertEqual(intent.intent["parameters"]["url"], "https://www.youtube.com/")
        self.assertEqual(intent.intent["parameters"]["browser"], "safari")

    def test_search_google_in_safari_preserves_browser_hint(self) -> None:
        intent = LocalIntentResolver().resolve("search for AI engineering in safari")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "google")
        self.assertEqual(intent.intent["parameters"]["query"], "ai engineering")
        self.assertEqual(intent.intent["parameters"]["browser"], "safari")

    def test_search_major_site_in_safari_preserves_site_engine(self) -> None:
        intent = LocalIntentResolver().resolve("search instagram for AI engineering in safari")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "instagram")
        self.assertEqual(intent.intent["parameters"]["query"], "ai engineering")
        self.assertEqual(intent.intent["parameters"]["browser"], "safari")

    def test_close_tab_in_safari_preserves_browser_hint(self) -> None:
        intent = LocalIntentResolver().resolve("close youtube tab in safari")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_close_tab")
        self.assertEqual(intent.intent["parameters"]["target"], "youtube")
        self.assertEqual(intent.intent["parameters"]["browser"], "safari")

    def test_browser_tool_search_dry_run_uses_safari(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = BrowserTool(Path(tmp)).search({"engine": "instagram", "query": "AI engineering", "browser": "safari", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["browser"], "Safari")
        self.assertEqual(result["data"]["url"], "https://www.instagram.com/explore/search/keyword/?q=AI+engineering")

    def test_tool_router_uses_browser_tool_for_safari_open_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = ToolRouter(Path(tmp), "")
            fake_browser = FakeBrowserTool()
            router.browser = fake_browser  # type: ignore[assignment]

            open_result = router._execute_one("browser_open", {"url": "https://www.youtube.com/", "browser": "safari"})
            search_result = router._execute_one("browser_search", {"engine": "google", "query": "AI engineering", "browser": "safari"})

        self.assertTrue(open_result["success"])
        self.assertTrue(search_result["success"])
        self.assertEqual(fake_browser.calls[0], ("open_page", {"url": "https://www.youtube.com/", "browser": "safari"}))
        self.assertEqual(fake_browser.calls[1], ("search", {"engine": "google", "query": "AI engineering", "browser": "safari"}))


if __name__ == "__main__":
    unittest.main()
