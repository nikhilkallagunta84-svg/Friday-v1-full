from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.local_intents import LocalIntentResolver
from friday.tools.browser import BrowserTool


class SiteSpecificSearchIntentTests(unittest.TestCase):
    def test_search_query_in_youtube_uses_youtube_engine(self) -> None:
        intent = LocalIntentResolver().resolve("search LeBron highlights in YouTube")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "youtube")
        self.assertEqual(intent.intent["parameters"]["query"], "lebron highlights")

    def test_search_for_query_on_instagram_uses_instagram_engine(self) -> None:
        intent = LocalIntentResolver().resolve("search for AI engineering on Instagram")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "instagram")
        self.assertEqual(intent.intent["parameters"]["query"], "ai engineering")

    def test_search_in_site_for_query_uses_site_engine(self) -> None:
        intent = LocalIntentResolver().resolve("search in YouTube for calculus tutorials")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "youtube")
        self.assertEqual(intent.intent["parameters"]["query"], "calculus tutorials")

    def test_browser_hint_and_site_target_can_both_be_present(self) -> None:
        intent = LocalIntentResolver().resolve("search LeBron highlights in YouTube in Safari")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "youtube")
        self.assertEqual(intent.intent["parameters"]["query"], "lebron highlights")
        self.assertEqual(intent.intent["parameters"]["browser"], "safari")

    def test_unknown_in_phrase_stays_google_search(self) -> None:
        intent = LocalIntentResolver().resolve("search AI engineering in 2026")

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent["command"], "browser_search")
        self.assertEqual(intent.intent["parameters"]["engine"], "google")
        self.assertEqual(intent.intent["parameters"]["query"], "ai engineering in 2026")

    def test_major_site_search_url_is_not_google_when_native_route_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = BrowserTool(Path(tmp)).search({"engine": "khan academy", "query": "derivatives", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["url"], "https://www.khanacademy.org/search?page_search_query=derivatives")

    def test_unknown_domain_uses_site_restricted_google_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = BrowserTool(Path(tmp)).search({"engine": "example.com", "query": "docs", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["url"], "https://www.google.com/search?q=site%3Aexample.com+docs")


if __name__ == "__main__":
    unittest.main()
