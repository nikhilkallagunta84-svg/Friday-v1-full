from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

from friday.schemas.action_result import ActionResult
from friday.google_accounts import preferred_google_url


class BrowserController:
    """Playwright-first browser control.

    FRIDAY's browser automation policy is semantic first: role, label,
    placeholder, text, and stable DOM-pattern locators before any visual or
    coordinate fallback. Screenshot/vision control lives outside this class so
    ordinary websites stay ref/locator-driven and safer to automate.
    """

    def __init__(
        self,
        root_dir: Path | str | None = None,
        headless: bool = False,
        timeout_ms: int = 5000,
        browser_channel: str | None = None,
        playwright_factory: Callable[[], Any] | None = None,
        context: Any | None = None,
        page: Any | None = None,
    ) -> None:
        self.root_dir = Path(root_dir) if root_dir is not None else Path.cwd()
        self.profile_dir = self.root_dir / ".friday" / "browser-profile"
        self.headless = headless
        self.timeout_ms = max(500, int(timeout_ms))
        self.browser_channel = (browser_channel if browser_channel is not None else os.environ.get("FRIDAY_BROWSER_CHANNEL", "chrome")).strip()
        self._playwright_factory = playwright_factory
        self._playwright_manager: Any | None = None
        self._playwright: Any | None = None
        self._context: Any | None = context
        self._page: Any | None = page

    def start(self) -> ActionResult:
        started_at = _now()
        if self._context is not None and self._page is not None:
            return _result("browser.start", True, "Browser controller is already started.", "", started_at)
        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            factory = self._playwright_factory or _default_playwright_factory
            self._playwright_manager = factory()
            self._playwright = self._playwright_manager.start()
            self._context = self._launch_context(self._playwright)
            self._set_default_timeout(self._context)
            pages = list(getattr(self._context, "pages", []) or [])
            self._page = pages[0] if pages else self._context.new_page()
        except BaseException as exc:
            self._cleanup_after_failed_start()
            return _result("browser.start", False, "Browser controller failed to start.", str(exc), started_at)
        return _result("browser.start", True, "Browser controller started.", "", started_at)

    def stop(self) -> ActionResult:
        started_at = _now()
        errors = self._teardown()
        if errors:
            return _result("browser.stop", False, "Browser controller shutdown had errors.", "; ".join(errors), started_at)
        return _result("browser.stop", True, "Browser controller stopped.", "", started_at)

    def open_url(self, url: str) -> ActionResult:
        started_at = _now()
        clean_url = preferred_google_url(url.strip())
        if not _is_valid_http_url(clean_url):
            return _result("browser.open_url", False, "Invalid URL.", f"Expected a full http or https URL, got {url!r}.", started_at)
        page = self._ensure_page_result(started_at, "browser.open_url")
        if isinstance(page, ActionResult):
            return page
        try:
            page.goto(clean_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._soft_verify_state(page)
        except BaseException as exc:
            if _looks_like_closed_browser_error(exc):
                page = self._restart_page_after_close(started_at, "browser.open_url")
                if isinstance(page, ActionResult):
                    return page
                try:
                    page.goto(clean_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    self._soft_verify_state(page)
                    return _result("browser.open_url", True, f"Opened {clean_url}.", "", started_at)
                except BaseException as retry_exc:
                    return _result("browser.open_url", False, f"Could not open {clean_url}.", str(retry_exc), started_at)
            return _result("browser.open_url", False, f"Could not open {clean_url}.", str(exc), started_at)
        return _result("browser.open_url", True, f"Opened {clean_url}.", "", started_at)

    def search(self, query: str) -> ActionResult:
        started_at = _now()
        clean_query = " ".join(query.strip().split())
        if not clean_query:
            return _result("browser.search", False, "Search query is empty.", "Search query cannot be empty.", started_at)
        page = self._ensure_page_result(started_at, "browser.search")
        if isinstance(page, ActionResult):
            return page
        url = _site_search_url(self.get_current_url(), clean_query)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._soft_verify_state(page)
        except BaseException as exc:
            if _looks_like_closed_browser_error(exc):
                page = self._restart_page_after_close(started_at, "browser.search")
                if isinstance(page, ActionResult):
                    return page
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    self._soft_verify_state(page)
                    return _result("browser.search", True, f"Searched for {clean_query}.", "", started_at)
                except BaseException as retry_exc:
                    return _result("browser.search", False, f"Could not search for {clean_query}.", str(retry_exc), started_at)
            return _result("browser.search", False, f"Could not search for {clean_query}.", str(exc), started_at)
        return _result("browser.search", True, f"Searched for {clean_query}.", "", started_at)

    def click(self, target: str) -> ActionResult:
        started_at = _now()
        clean_target = target.strip()
        if not clean_target:
            return _result("browser.click", False, "Click target is empty.", "Click target cannot be empty.", started_at)
        page = self._ensure_page_result(started_at, "browser.click")
        if isinstance(page, ActionResult):
            return page
        clean_target, tab_hint = _split_tab_context(clean_target)
        if tab_hint:
            page = self._page_matching_tab_hint(tab_hint) or page
        errors: list[str] = []
        for locator in self._click_locators(page, clean_target):
            try:
                locator.first.click(timeout=self.timeout_ms)
                self._soft_verify_state(page)
                return _result("browser.click", True, f"Clicked {clean_target}.", "", started_at)
            except BaseException as exc:
                errors.append(str(exc))
        error = "; ".join(error for error in errors if error) or "No matching locator found."
        return _result("browser.click", False, f"Could not click {clean_target}.", error, started_at)

    def type_text(self, target: str, text: str) -> ActionResult:
        started_at = _now()
        clean_target = target.strip()
        if not clean_target:
            return _result("browser.type", False, "Type target is empty.", "Type target cannot be empty.", started_at)
        page = self._ensure_page_result(started_at, "browser.type")
        if isinstance(page, ActionResult):
            return page
        if _is_current_field_target(clean_target):
            try:
                page.keyboard.type(text)
                self._soft_verify_state(page)
                return _result("browser.type", True, "Typed text into the current field.", "", started_at)
            except BaseException as exc:
                return _result("browser.type", False, "Could not type into the current field.", str(exc), started_at)
        errors: list[str] = []
        for locator in self._typing_locators(page, clean_target):
            try:
                locator.first.fill(text, timeout=self.timeout_ms)
                self._soft_verify_state(page)
                return _result("browser.type", True, f"Typed text into {clean_target}.", "", started_at)
            except BaseException as exc:
                errors.append(str(exc))
        error = "; ".join(error for error in errors if error) or "No editable locator found."
        return _result("browser.type", False, f"Could not type into {clean_target}.", error, started_at)

    def press_key(self, key: str) -> ActionResult:
        started_at = _now()
        clean_key = key.strip()
        if not clean_key:
            return _result("browser.press_key", False, "Key is empty.", "Key cannot be empty.", started_at)
        page = self._ensure_page_result(started_at, "browser.press_key")
        if isinstance(page, ActionResult):
            return page
        try:
            page.keyboard.press(clean_key)
            self._soft_verify_state(page)
        except BaseException as exc:
            return _result("browser.press_key", False, f"Could not press {clean_key}.", str(exc), started_at)
        return _result("browser.press_key", True, f"Pressed {clean_key}.", "", started_at)

    def go_back(self) -> ActionResult:
        started_at = _now()
        page = self._ensure_page_result(started_at, "browser.go_back")
        if isinstance(page, ActionResult):
            return page
        try:
            page.go_back(wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._soft_verify_state(page)
        except BaseException as exc:
            return _result("browser.go_back", False, "Could not go back.", str(exc), started_at)
        return _result("browser.go_back", True, "Went back.", "", started_at)

    def new_tab(self) -> ActionResult:
        started_at = _now()
        context = self._ensure_context_result(started_at, "browser.new_tab")
        if isinstance(context, ActionResult):
            return context
        try:
            self._page = context.new_page()
        except BaseException as exc:
            return _result("browser.new_tab", False, "Could not open a new tab.", str(exc), started_at)
        return _result("browser.new_tab", True, "Opened a new tab.", "", started_at)

    def close_tab(self) -> ActionResult:
        started_at = _now()
        page = self._ensure_page_result(started_at, "browser.close_tab")
        if isinstance(page, ActionResult):
            return page
        try:
            page.close()
            pages = list(getattr(self._context, "pages", []) or []) if self._context is not None else []
            self._page = pages[-1] if pages else None
        except BaseException as exc:
            return _result("browser.close_tab", False, "Could not close the current tab.", str(exc), started_at)
        return _result("browser.close_tab", True, "Closed the current tab.", "", started_at)

    def get_page_title(self) -> str:
        if self._page is None:
            return ""
        try:
            return str(self._page.title())
        except BaseException:
            return ""

    def get_current_url(self) -> str:
        if self._page is None:
            return ""
        try:
            return str(getattr(self._page, "url", ""))
        except BaseException:
            return ""

    def _launch_context(self, playwright: Any) -> Any:
        kwargs = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.headless,
            "accept_downloads": False,
            "viewport": {"width": 1440, "height": 900},
        }
        chromium = playwright.chromium
        if self.browser_channel and self.browser_channel.lower() not in {"chromium", "default", "none"}:
            try:
                return chromium.launch_persistent_context(channel=self.browser_channel, **kwargs)
            except BaseException:
                pass
        return chromium.launch_persistent_context(**kwargs)

    def _ensure_context_result(self, started_at: datetime, action_id: str) -> Any | ActionResult:
        if self._context is not None and not _is_closed_playwright_object(self._context):
            return self._context
        if self._context is not None:
            self._cleanup_after_failed_start()
        result = self.start()
        if not result.success:
            return _result(action_id, False, "Browser controller is not available.", result.error, started_at)
        return self._context

    def _ensure_page_result(self, started_at: datetime, action_id: str) -> Any | ActionResult:
        context = self._ensure_context_result(started_at, action_id)
        if isinstance(context, ActionResult):
            return context
        if self._page is not None and not _is_closed_playwright_object(self._page):
            return self._page
        if self._page is not None:
            self._page = None
        try:
            pages = list(getattr(context, "pages", []) or [])
            live_pages = [page for page in pages if not _is_closed_playwright_object(page)]
            self._page = live_pages[0] if live_pages else context.new_page()
        except BaseException as exc:
            if _looks_like_closed_browser_error(exc):
                self._cleanup_after_failed_start()
                context = self._ensure_context_result(started_at, action_id)
                if isinstance(context, ActionResult):
                    return context
                try:
                    self._page = context.new_page()
                    return self._page
                except BaseException as retry_exc:
                    return _result(action_id, False, "Could not create browser page.", str(retry_exc), started_at)
            return _result(action_id, False, "Could not create browser page.", str(exc), started_at)
        return self._page

    def _restart_page_after_close(self, started_at: datetime, action_id: str) -> Any | ActionResult:
        self._cleanup_after_failed_start()
        return self._ensure_page_result(started_at, action_id)

    def _page_matching_tab_hint(self, tab_hint: str) -> Any | None:
        context = self._context
        if context is None:
            return None
        hint = _normalize_match_text(tab_hint)
        if not hint:
            return None
        pages = list(getattr(context, "pages", []) or [])
        for page in reversed(pages):
            page_text = _normalize_match_text(f"{_safe_page_title(page)} {getattr(page, 'url', '')}")
            if hint in page_text or all(word in page_text for word in hint.split()):
                self._page = page
                try:
                    page.bring_to_front()
                except BaseException:
                    pass
                return page
        return None

    def _click_locators(self, page: Any, target: str) -> list[Any]:
        locators: list[Any] = []
        variants = _click_target_variants(target)
        ordinal_link_index = _ordinal_link_index(target)
        if ordinal_link_index is not None:
            locators.extend(self._ordinal_result_locators(page, ordinal_link_index))
        if _is_media_playable_target(target):
            locators.extend(self._media_play_locators(page))
        if _is_spotify_playable_target(target):
            locators.extend(self._spotify_play_locators(page))
        for variant in variants:
            if _is_search_field_target(variant):
                locators.extend(self._search_field_locators(page))
            for role in ("button", "link", "menuitem", "tab", "checkbox", "radio"):
                locators.append(page.get_by_role(role, name=variant, exact=False))
            locators.append(page.get_by_text(variant, exact=False))
            if _looks_like_selector(variant):
                locators.append(page.locator(variant))
            locators.append(page.locator(f"text={variant}"))
        return locators

    def _ordinal_result_locators(self, page: Any, index: int) -> list[Any]:
        return [
            page.locator("a:has(h3)").nth(index),
            page.locator("#search a:has(h3)").nth(index),
            page.locator('a[data-testid="result-title-a"]').nth(index),
            page.locator('a[href*="/url?"]').nth(index),
            page.locator("a#video-title").nth(index),
            page.get_by_role("link").nth(index),
        ]

    def _spotify_play_locators(self, page: Any) -> list[Any]:
        return [
            page.locator('button[aria-label^="Play" i]'),
            page.locator('[data-testid="play-button"]'),
            page.locator('button:has-text("Play")'),
            page.get_by_role("button", name="Play", exact=False),
        ]

    def _media_play_locators(self, page: Any) -> list[Any]:
        current_url = str(getattr(page, "url", "") or "").lower()
        locators: list[Any] = []
        if "youtube.com" in current_url or "youtu.be" in current_url:
            locators.extend(
                [
                    page.locator("ytd-video-renderer a#video-title").nth(0),
                    page.locator("a#video-title").nth(0),
                    page.locator("ytd-video-renderer a#thumbnail").nth(0),
                    page.locator('a[href*="/watch"]').nth(0),
                ]
            )
        if "open.spotify.com" in current_url or "spotify.com" in current_url:
            locators.extend(self._spotify_play_locators(page))
        if "soundcloud.com" in current_url:
            locators.extend(
                [
                    page.locator('button[aria-label^="Play" i]').nth(0),
                    page.locator('button[title^="Play" i]').nth(0),
                    page.locator(".playButton").nth(0),
                    page.locator("a.soundTitle__title").nth(0),
                    page.locator('a[href*="/"]').nth(0),
                ]
            )
        if "tiktok.com" in current_url:
            locators.extend(
                [
                    page.locator('a[href*="/video/"]').nth(0),
                    page.locator('[data-e2e*="video"]').nth(0),
                ]
            )
        if "twitch.tv" in current_url:
            locators.extend(
                [
                    page.locator('a[href*="/videos/"]').nth(0),
                    page.locator('a[href*="/clip/"]').nth(0),
                    page.locator('a[href*="/directory"]').nth(0),
                ]
            )
        locators.extend(
            [
                page.locator('a[href*="/watch"]').nth(0),
                page.locator('a[href*="/video"]').nth(0),
                page.locator('button[aria-label^="Play" i]').nth(0),
                page.get_by_role("button", name="Play", exact=False),
            ]
        )
        return locators

    def _typing_locators(self, page: Any, target: str) -> list[Any]:
        locators: list[Any] = []
        if _is_search_field_target(target):
            locators.extend(self._search_field_locators(page))
        locators.extend([
            page.get_by_label(target, exact=False),
            page.get_by_placeholder(target, exact=False),
            page.get_by_role("textbox", name=target, exact=False),
        ])
        if _looks_like_selector(target):
            locators.append(page.locator(target))
        escaped = target.replace('"', '\\"')
        locators.extend(
            [
                page.locator(f'input[aria-label*="{escaped}" i]'),
                page.locator(f'textarea[aria-label*="{escaped}" i]'),
                page.locator(f'[contenteditable="true"][aria-label*="{escaped}" i]'),
            ]
        )
        return locators

    def _search_field_locators(self, page: Any) -> list[Any]:
        return [
            page.get_by_role("searchbox", name="", exact=False),
            page.get_by_role("textbox", name="search", exact=False),
            page.get_by_label("search", exact=False),
            page.get_by_placeholder("search", exact=False),
            page.locator('input[type="search"]'),
            page.locator('input[name="q"]'),
            page.locator('textarea[name="q"]'),
            page.locator('[role="searchbox"]'),
            page.locator('[aria-label*="search" i]'),
            page.locator('[placeholder*="search" i]'),
            page.locator('[contenteditable="true"][aria-label*="search" i]'),
        ]

    def _soft_verify_state(self, page: Any) -> None:
        """Let a state-changing browser action settle without making tests brittle."""
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        try:
            wait_for_load_state("domcontentloaded", timeout=min(1000, self.timeout_ms))
        except BaseException:
            return

    def _set_default_timeout(self, context: Any) -> None:
        try:
            context.set_default_timeout(self.timeout_ms)
        except BaseException:
            pass

    def _teardown(self) -> list[str]:
        errors: list[str] = []
        if self._context is not None:
            try:
                self._context.close()
            except BaseException as exc:
                errors.append(str(exc))
        if self._playwright_manager is not None:
            try:
                self._playwright_manager.stop()
            except BaseException as exc:
                errors.append(str(exc))
        self._context = None
        self._page = None
        self._playwright = None
        self._playwright_manager = None
        return errors

    def _cleanup_after_failed_start(self) -> None:
        self._teardown()


def _default_playwright_factory() -> Any:
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def _is_valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _site_search_url(current_url: str, query: str) -> str:
    encoded = quote_plus(query)
    lowered = current_url.lower()
    routes = [
        (("youtube.com", "youtu.be"), f"https://www.youtube.com/results?search_query={encoded}"),
        (("open.spotify.com", "spotify.com"), f"https://open.spotify.com/search/{encoded}"),
        (("reddit.com",), f"https://www.reddit.com/search/?q={encoded}"),
        (("instagram.com",), f"https://www.instagram.com/explore/search/keyword/?q={encoded}"),
        (("tiktok.com",), f"https://www.tiktok.com/search?q={encoded}"),
        (("x.com", "twitter.com"), f"https://x.com/search?q={encoded}&src=typed_query"),
        (("facebook.com",), f"https://www.facebook.com/search/top?q={encoded}"),
        (("linkedin.com",), f"https://www.linkedin.com/search/results/all/?keywords={encoded}"),
        (("github.com",), f"https://github.com/search?q={encoded}"),
        (("amazon.com",), f"https://www.amazon.com/s?k={encoded}"),
        (("walmart.com",), f"https://www.walmart.com/search?q={encoded}"),
        (("target.com",), f"https://www.target.com/s?searchTerm={encoded}"),
        (("wikipedia.org",), f"https://www.wikipedia.org/search-redirect.php?search={encoded}"),
        (("stackoverflow.com",), f"https://stackoverflow.com/search?q={encoded}"),
        (("pinterest.com",), f"https://www.pinterest.com/search/pins/?q={encoded}"),
        (("soundcloud.com",), f"https://soundcloud.com/search?q={encoded}"),
        (("twitch.tv",), f"https://www.twitch.tv/search?term={encoded}"),
        (("medium.com",), f"https://medium.com/search?q={encoded}"),
        (("canva.com",), f"https://www.canva.com/search/templates?q={encoded}"),
        (("figma.com",), f"https://www.figma.com/community/search?query={encoded}"),
        (("google.com",), f"https://www.google.com/search?q={encoded}"),
        (("bing.com",), f"https://www.bing.com/search?q={encoded}"),
        (("duckduckgo.com",), f"https://duckduckgo.com/?q={encoded}"),
        (("yahoo.com",), f"https://search.yahoo.com/search?p={encoded}"),
    ]
    for domains, search_url in routes:
        if any(domain in lowered for domain in domains):
            return search_url
    return f"https://www.google.com/search?q={encoded}"


def _looks_like_selector(target: str) -> bool:
    return bool(re.match(r"^(#|\.|\[|//|xpath=|css=|[a-zA-Z][\w-]*(?:\[|\.|#|:|\s))", target.strip()))


def _is_search_field_target(target: str) -> bool:
    clean = " ".join(target.lower().strip().split())
    return clean in {"search", "search bar", "search box", "search field", "search input"}


def _is_current_field_target(target: str) -> bool:
    clean = " ".join(target.lower().strip().split())
    return clean in {"current field", "active field", "focused field", "focused input", "current input"}


def _is_spotify_playable_target(target: str) -> bool:
    clean = " ".join(target.lower().strip().split())
    return clean in {
        "first playable result",
        "first applicable option",
        "first spotify result",
        "first song",
        "top song",
        "play first result",
        "play first song",
    }


def _is_media_playable_target(target: str) -> bool:
    clean = " ".join(target.lower().strip().split())
    return clean in {
        "first playable result",
        "first applicable option",
        "first video",
        "first video result",
        "first song",
        "first track",
        "first result",
        "top result",
        "top video",
        "play first result",
        "play first video",
        "play first song",
    }


def _click_target_variants(target: str) -> list[str]:
    clean = " ".join(target.strip().split())
    variants = [clean] if clean else []
    without_article = re.sub(r"^(?:on\s+)?(?:a|an|the)\s+", "", clean, flags=re.I).strip()
    if without_article and without_article not in variants:
        variants.append(without_article)
    if _ordinal_link_index(without_article or clean) is None:
        stripped_kind = re.sub(r"\s+(?:button|link|tab|menu|icon|field)$", "", without_article or clean, flags=re.I).strip()
        if stripped_kind and stripped_kind not in variants:
            variants.append(stripped_kind)
    return variants


def _split_tab_context(target: str) -> tuple[str, str]:
    clean = " ".join(target.strip().split())
    patterns = [
        r"^(?P<target>.+?)\s+(?:on|in|from)\s+(?:the\s+)?(?P<hint>.+?)\s+(?:browser\s+)?(?:tab|page|window)$",
        r"^(?P<target>.+?)\s+(?:on|in|from)\s+(?:the\s+)?(?P<hint>.+?)\s+(?:search\s+)?results?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, clean, flags=re.I)
        if match:
            action_target = match.group("target").strip(" .'\"")
            hint = match.group("hint").strip(" .'\"")
            if action_target and hint:
                return action_target, hint
    clean = re.sub(r"\s+(?:on|in|from)\s+(?:the\s+)?(?:current|active|this)\s+(?:browser\s+)?(?:tab|page|window)$", "", clean, flags=re.I)
    return clean.strip(), ""


def _normalize_match_text(value: str) -> str:
    clean = value.lower()
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return " ".join(clean.split())


def _safe_page_title(page: Any) -> str:
    try:
        return str(page.title())
    except BaseException:
        return ""


ORDINAL_INDEXES = {
    "first": 0,
    "one": 0,
    "top": 0,
    "1": 0,
    "1st": 0,
    "second": 1,
    "two": 1,
    "2": 1,
    "2nd": 1,
    "third": 2,
    "three": 2,
    "3": 2,
    "3rd": 2,
    "fourth": 3,
    "four": 3,
    "4": 3,
    "4th": 3,
    "fifth": 4,
    "five": 4,
    "5": 4,
    "5th": 4,
    "sixth": 5,
    "six": 5,
    "6": 5,
    "6th": 5,
    "seventh": 6,
    "seven": 6,
    "7": 6,
    "7th": 6,
    "eighth": 7,
    "eight": 7,
    "8": 7,
    "8th": 7,
    "ninth": 8,
    "nine": 8,
    "9": 8,
    "9th": 8,
    "tenth": 9,
    "ten": 9,
    "10": 9,
    "10th": 9,
}


def _ordinal_link_index(target: str) -> int | None:
    clean = " ".join(target.lower().strip().split())
    clean = re.sub(r"^(?:a|an|the)\s+", "", clean)
    clean = re.sub(r"\b(?:google|web|search)\s+(?=result|results|link|links)", "", clean)
    clean = clean.replace("results", "result").replace("links", "link")
    patterns = [
        r"^(top|first)\s+(?:link|result)$",
        r"^(top|first)\s+(?:video|song|track)(?:\s+result)?$",
        r"^([a-z0-9]+(?:st|nd|rd|th)?)\s+(?:link|result|video|song|track)(?:\s+result)?$",
        r"^(?:link|result|video|song|track)\s+(?:number\s+)?([a-z0-9]+(?:st|nd|rd|th)?)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, clean)
        if match:
            return _ordinal_to_index(match.group(1))
    return None


def _ordinal_to_index(value: str) -> int | None:
    clean = value.lower().strip()
    if clean in ORDINAL_INDEXES:
        return ORDINAL_INDEXES[clean]
    match = re.match(r"^(\d+)(?:st|nd|rd|th)?$", clean)
    if match:
        number = int(match.group(1))
        if 1 <= number <= 50:
            return number - 1
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_closed_playwright_object(value: Any) -> bool:
    is_closed = getattr(value, "is_closed", None)
    if callable(is_closed):
        try:
            return bool(is_closed())
        except BaseException:
            return True
    return False


def _looks_like_closed_browser_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "target page, context or browser has been closed" in text or "browser has been closed" in text or "context has been closed" in text


def _result(action_id: str, success: bool, message: str, error: str, started_at: datetime) -> ActionResult:
    return ActionResult(
        action_id=_stable_result_id(action_id),
        success=success,
        message=message,
        error="" if success else (error or message),
        started_at=started_at,
        finished_at=_now(),
        controller_used="playwright",
    )


def _stable_result_id(action_id: str) -> str:
    digest = sha1(f"{action_id}|{time.monotonic_ns()}".encode("utf-8")).hexdigest()[:10]
    return f"{action_id}-{digest}"
