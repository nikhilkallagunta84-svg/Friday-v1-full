from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from friday.control.browser_controller import BrowserController
from friday.tools.browser import BrowserTool
from friday.tools.browser_control import BrowserControlTool
from friday.google_accounts import account_chooser_url, classroom_google_account, personal_google_account, preferred_google_url
from friday.tools.productivity import ProductivityDraftTool


PERSONAL = "personal@example.com"
SCHOOL = "student@example.edu"


class UrlCapturePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.goto_calls: list[str] = []

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.url = url
        self.goto_calls.append(url)

    def is_closed(self) -> bool:
        return False

    def wait_for_load_state(self, *_: object, **__: object) -> None:
        return None


class UrlCaptureContext:
    def __init__(self, page: UrlCapturePage) -> None:
        self.pages = [page]

    def is_closed(self) -> bool:
        return False


class GoogleAccountRoutingTests(unittest.TestCase):
    def test_personal_google_account_prefers_personal_env(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL, "FRIDAY_GOOGLE_ACCOUNT": "fallback@example.com"}):
            self.assertEqual(personal_google_account(), PERSONAL)

    def test_classroom_account_can_use_separate_env(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL, "FRIDAY_CLASSROOM_ACCOUNT": SCHOOL}):
            self.assertEqual(classroom_google_account(), SCHOOL)

    def test_google_app_url_is_wrapped_with_account_chooser(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL}):
            url = preferred_google_url("https://docs.google.com/document/u/0/create")

        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "accounts.google.com")
        self.assertEqual(parsed.path, "/AccountChooser")
        self.assertEqual(query["Email"], [PERSONAL])
        self.assertIn("authuser=personal%40example.com", query["continue"][0])

    def test_non_google_url_is_not_wrapped(self) -> None:
        with patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL}):
            self.assertEqual(preferred_google_url("https://open.spotify.com"), "https://open.spotify.com")

    def test_browser_tool_uses_personal_google_account_for_google_apps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL}):
            result = BrowserTool(Path(tmp)).open_page({"url": "https://drive.google.com", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertIn("accounts.google.com/AccountChooser", result["data"]["url"])
        self.assertIn("Email=personal%40example.com", result["data"]["url"])

    def test_browser_controller_uses_personal_google_account_for_google_apps(self) -> None:
        page = UrlCapturePage()
        context = UrlCaptureContext(page)
        with patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL}):
            controller = BrowserController(context=context, page=page)
            result = controller.open_url("https://docs.google.com")

        self.assertTrue(result.success)
        self.assertIn("accounts.google.com/AccountChooser", page.url)
        self.assertIn("Email=personal%40example.com", page.url)

    def test_productivity_tool_uses_personal_google_account_for_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL}):
            result = ProductivityDraftTool(Path(tmp)).write_report({"target": "google_docs", "document_type": "report", "prompt": "AI", "dry_run": True})

        self.assertTrue(result["success"])
        self.assertIn("accounts.google.com/AccountChooser", result["data"]["url"])
        self.assertIn("Email=personal%40example.com", result["data"]["url"])

    def test_browser_control_classroom_default_is_env_driven_not_hardcoded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"FRIDAY_PERSONAL_GOOGLE_ACCOUNT": PERSONAL, "FRIDAY_CLASSROOM_ACCOUNT": ""}):
            tool = BrowserControlTool(Path(tmp))

        self.assertEqual(tool.classroom_account, PERSONAL)
        self.assertNotEqual(tool.classroom_account, "kallaguntan@bentonvillek12.org")
        self.assertIn("accounts.google.com/AccountChooser", tool._classroom_account_chooser_url(tool.classroom_account))


if __name__ == "__main__":
    unittest.main()
