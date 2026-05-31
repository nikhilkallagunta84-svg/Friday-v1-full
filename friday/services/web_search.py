from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: List[WebSearchResult] = []
        self._in_title = False
        self._in_snippet = False
        self._pending_url = ""
        self._pending_title: list[str] = []
        self._pending_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        class_name = attributes.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._in_title = True
            self._pending_url = self._clean_url(attributes.get("href", ""))
            self._pending_title = []
            self._pending_snippet = []
        elif tag in {"a", "div"} and "result__snippet" in class_name:
            self._in_snippet = True
            self._pending_snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if tag in {"a", "div"} and self._in_snippet:
            self._in_snippet = False
            self._commit_result()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._pending_title.append(data)
        elif self._in_snippet:
            self._pending_snippet.append(data)

    def _commit_result(self) -> None:
        title = self._normalize(" ".join(self._pending_title))
        snippet = self._normalize(" ".join(self._pending_snippet))
        if title and self._pending_url and not any(result.url == self._pending_url for result in self.results):
            self.results.append(WebSearchResult(title=title, url=self._pending_url, snippet=snippet))
        self._pending_title = []
        self._pending_snippet = []
        self._pending_url = ""

    def _clean_url(self, url: str) -> str:
        clean = html.unescape(url)
        if clean.startswith("//"):
            clean = "https:" + clean
        parsed = urllib.parse.urlparse(clean)
        if parsed.path == "/l/":
            query = urllib.parse.parse_qs(parsed.query)
            target = query.get("uddg", [""])[0]
            if target:
                clean = target
        return clean

    def _normalize(self, value: str) -> str:
        clean = html.unescape(value)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()


class WebSearchClient:
    def __init__(self, cache_ttl_seconds: int = 900, timeout_seconds: float = 8.0) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._cache: Dict[str, Tuple[float, List[WebSearchResult]]] = {}

    def search(self, query: str, max_results: int = 4) -> List[WebSearchResult]:
        clean_query = " ".join(query.strip().split())
        if not clean_query:
            return []
        cache_key = clean_query.lower()
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return cached[1][:max_results]
        results = self._search_duckduckgo(clean_query, max_results=max_results)
        self._cache[cache_key] = (now, results)
        return results[:max_results]

    def format_for_prompt(self, results: List[WebSearchResult]) -> str:
        if not results:
            return "No web results were available."
        lines = []
        for index, result in enumerate(results, start=1):
            snippet = f" - {result.snippet}" if result.snippet else ""
            lines.append(f"{index}. {result.title}\nURL: {result.url}\nSnippet: {snippet}".strip())
        return "\n\n".join(lines)

    def _search_duckduckgo(self, query: str, max_results: int) -> List[WebSearchResult]:
        encoded = urllib.parse.urlencode({"q": query})
        request = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?{encoded}",
            headers={
                "User-Agent": "Mozilla/5.0 FRIDAY local assistant",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            page = response.read().decode("utf-8", errors="replace")
        parser = _DuckDuckGoHTMLParser()
        parser.feed(page)
        return parser.results[:max_results]
