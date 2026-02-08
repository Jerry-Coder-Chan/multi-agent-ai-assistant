"""
SearchAgent - Live web search via SerpAPI.
"""
from typing import List, Dict, Optional
import requests


class SearchAgent:
    """Simple SerpAPI-based search agent."""

    SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, max_results: int = 5, timeout: int = 8):
        self.api_key = api_key
        self.max_results = max_results
        self.timeout = timeout

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str) -> str:
        """Run a search and return a concise markdown summary."""
        if not self.api_key:
            return "Search is not configured. Please provide a SERPAPI_API_KEY."

        params = {
            "q": query,
            "engine": "google",
            "api_key": self.api_key,
            "num": self.max_results,
        }

        resp = requests.get(self.SERPAPI_ENDPOINT, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        results: List[Dict] = data.get("organic_results", [])[: self.max_results]
        if not results:
            return "No search results found."

        lines: List[str] = ["Here are the top live results:"]
        for r in results:
            title = r.get("title") or "Result"
            link = r.get("link") or ""
            snippet = r.get("snippet") or ""
            if link:
                lines.append(f"- [{title}]({link}) — {snippet}")
            else:
                lines.append(f"- {title} — {snippet}")

        return "\n".join(lines)
