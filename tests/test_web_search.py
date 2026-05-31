from __future__ import annotations

import unittest

from friday.services.web_search import WebSearchClient, WebSearchResult


class WebSearchClientTests(unittest.TestCase):
    def test_prompt_context_formats_results(self) -> None:
        client = WebSearchClient()

        context = client.format_for_prompt([
            WebSearchResult("Example Title", "https://example.com", "A current snippet."),
        ])

        self.assertIn("Example Title", context)
        self.assertIn("https://example.com", context)
        self.assertIn("A current snippet.", context)

    def test_empty_prompt_context_is_explicit(self) -> None:
        client = WebSearchClient()

        self.assertEqual(client.format_for_prompt([]), "No web results were available.")

    def test_search_uses_cache_for_repeated_query(self) -> None:
        client = WebSearchClient()
        calls = 0

        def fake_search(query: str, max_results: int) -> list[WebSearchResult]:
            nonlocal calls
            calls += 1
            return [WebSearchResult(query, "https://example.com", "fresh")]

        client._search_duckduckgo = fake_search  # type: ignore[method-assign]

        first = client.search("AI news today")
        second = client.search("ai   news today")

        self.assertEqual(first, second)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
