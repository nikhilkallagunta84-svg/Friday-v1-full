from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.control.browser_controller import BrowserController
from friday.schemas.action_result import ActionResult


class FakeLocator:
    def __init__(self, name: str, should_succeed: bool = False, nth_success_indexes: set[int] | None = None) -> None:
        self.name = name
        self.should_succeed = should_succeed
        self.nth_success_indexes = nth_success_indexes or set()
        self.clicked = False
        self.filled = ""

    @property
    def first(self) -> "FakeLocator":
        return self

    def click(self, timeout: int = 0) -> None:
        if not self.should_succeed:
            raise RuntimeError(f"{self.name} was not found")
        self.clicked = True

    def nth(self, index: int) -> "FakeLocator":
        return FakeLocator(f"{self.name}.nth({index})", self.should_succeed or index in self.nth_success_indexes)

    def fill(self, text: str, timeout: int = 0) -> None:
        if not self.should_succeed:
            raise RuntimeError(f"{self.name} was not editable")
        self.filled = text


class FakeKeyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []
        self.typed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def type(self, text: str) -> None:
        self.typed.append(text)


class FakePage:
    def __init__(
        self,
        clickable_targets: set[str] | None = None,
        editable_targets: set[str] | None = None,
        clickable_link_indexes: set[int] | None = None,
        title_value: str = "Fake Browser Page",
        url: str = "about:blank",
    ) -> None:
        self.url = url
        self.title_value = title_value
        self.closed = False
        self.fronted = False
        self.goto_calls: list[str] = []
        self.clickable_targets = clickable_targets or set()
        self.editable_targets = editable_targets or set()
        self.clickable_link_indexes = clickable_link_indexes or set()
        self.keyboard = FakeKeyboard()

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        self.url = url
        self.goto_calls.append(url)

    def get_by_role(self, role: str, name: str = "", exact: bool = False) -> FakeLocator:
        if role == "link" and not name:
            return FakeLocator("role=link", nth_success_indexes=self.clickable_link_indexes)
        return FakeLocator(f"role={role}:{name}", name.lower() in self.clickable_targets or name.lower() in self.editable_targets)

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocator:
        return FakeLocator(f"text={text}", text.lower() in self.clickable_targets)

    def get_by_label(self, text: str, exact: bool = False) -> FakeLocator:
        return FakeLocator(f"label={text}", text.lower() in self.editable_targets)

    def get_by_placeholder(self, text: str, exact: bool = False) -> FakeLocator:
        return FakeLocator(f"placeholder={text}", text.lower() in self.editable_targets)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(f"selector={selector}", selector.lower() in self.clickable_targets or selector.lower() in self.editable_targets)

    def go_back(self, wait_until: str = "", timeout: int = 0) -> None:
        self.url = "about:blank"

    def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed

    def title(self) -> str:
        return self.title_value

    def bring_to_front(self) -> None:
        self.fronted = True


class FakeContext:
    def __init__(self, page: FakePage | None = None) -> None:
        self.closed = False
        self.pages: list[FakePage] = [page or FakePage()]

    def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


class BrowserControllerTests(unittest.TestCase):
    def test_controller_can_be_instantiated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            controller = BrowserController(root_dir=Path(tmp))

        self.assertIsInstance(controller, BrowserController)

    def test_invalid_url_fails_cleanly(self) -> None:
        controller = BrowserController()

        result = controller.open_url("not a url")

        self.assertIsInstance(result, ActionResult)
        self.assertFalse(result.success)
        self.assertIn("Invalid URL", result.message)

    def test_open_url_returns_action_result(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.open_url("https://example.com")

        self.assertIsInstance(result, ActionResult)
        self.assertTrue(result.success)
        self.assertEqual(page.url, "https://example.com")

    def test_open_url_recovers_when_cached_page_is_closed(self) -> None:
        closed_page = FakePage()
        closed_page.close()
        context = FakeContext(closed_page)
        controller = BrowserController(context=context, page=closed_page)

        result = controller.open_url("https://example.com")

        self.assertTrue(result.success)
        self.assertIsNot(controller._page, closed_page)
        self.assertEqual(controller._page.url, "https://example.com")

    def test_search_returns_action_result(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.search("AP Calculus")

        self.assertIsInstance(result, ActionResult)
        self.assertTrue(result.success)
        self.assertIn("https://www.google.com/search?q=AP+Calculus", page.url)

    def test_search_uses_instagram_site_search_when_on_instagram(self) -> None:
        page = FakePage(url="https://www.instagram.com/")
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.search("AI engineering")

        self.assertTrue(result.success)
        self.assertEqual(page.url, "https://www.instagram.com/explore/search/keyword/?q=AI+engineering")

    def test_search_uses_amazon_site_search_when_on_amazon(self) -> None:
        page = FakePage(url="https://www.amazon.com/")
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.search("laptop stand")

        self.assertTrue(result.success)
        self.assertEqual(page.url, "https://www.amazon.com/s?k=laptop+stand")

    def test_failed_click_returns_action_result_not_exception(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("Definitely Missing Button")

        self.assertIsInstance(result, ActionResult)
        self.assertFalse(result.success)
        self.assertIn("Could not click", result.message)

    def test_click_search_bar_uses_search_field_locators(self) -> None:
        page = FakePage(editable_targets={"search"})
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("search bar")

        self.assertTrue(result.success)
        self.assertIn("Clicked search bar", result.message)

    def test_click_first_link_uses_first_link_locator(self) -> None:
        page = FakePage(clickable_link_indexes={0})
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("first link")

        self.assertTrue(result.success)
        self.assertIn("Clicked first link", result.message)

    def test_click_first_playable_result_uses_spotify_play_button_locator(self) -> None:
        page = FakePage(clickable_targets={'button[aria-label^="play" i]'}, url="https://open.spotify.com/search/mannequin")
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("first playable result")

        self.assertTrue(result.success)
        self.assertIn("Clicked first playable result", result.message)

    def test_click_first_playable_result_on_youtube_uses_first_video_locator(self) -> None:
        page = FakePage(clickable_targets={"ytd-video-renderer a#video-title"}, url="https://www.youtube.com/results?search_query=sum+2+prove")
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("first playable result")

        self.assertTrue(result.success)
        self.assertIn("Clicked first playable result", result.message)

    def test_click_first_video_result_on_youtube_uses_video_locator(self) -> None:
        page = FakePage(clickable_targets={"ytd-video-renderer a#video-title"}, url="https://www.youtube.com/results?search_query=sum+2+prove")
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("first video result")

        self.assertTrue(result.success)
        self.assertIn("Clicked first video result", result.message)

    def test_click_third_result_uses_third_link_locator(self) -> None:
        page = FakePage(clickable_link_indexes={2})
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.click("third result")

        self.assertTrue(result.success)
        self.assertIn("Clicked third result", result.message)

    def test_click_first_link_on_named_tab_strips_tab_context(self) -> None:
        blank_page = FakePage(title_value="Blank")
        search_page = FakePage(clickable_link_indexes={0}, title_value="AI engineering - Google Search", url="https://www.google.com/search?q=AI+engineering")
        context = FakeContext(blank_page)
        context.pages.append(search_page)
        controller = BrowserController(context=context, page=blank_page)

        result = controller.click("first link on the AI engineering tab")

        self.assertTrue(result.success)
        self.assertTrue(search_page.fronted)
        self.assertIs(controller._page, search_page)
        self.assertIn("Clicked first link", result.message)

    def test_type_text_into_current_field_uses_keyboard(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.type_text("current field", "Lil Baby")

        self.assertTrue(result.success)
        self.assertEqual(page.keyboard.typed, ["Lil Baby"])

    def test_type_text_into_search_bar_uses_search_field_locators(self) -> None:
        page = FakePage(editable_targets={"search"})
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.type_text("search bar", "AP Calculus")

        self.assertTrue(result.success)
        self.assertIn("Typed text into search bar", result.message)

    def test_stop_closes_browser_session_cleanly(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        controller = BrowserController(context=context, page=page)

        result = controller.stop()

        self.assertTrue(result.success)
        self.assertTrue(context.closed)
        self.assertEqual(controller.get_current_url(), "")


if __name__ == "__main__":
    unittest.main()
