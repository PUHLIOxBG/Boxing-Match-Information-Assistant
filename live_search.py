"""Live source discovery via the Brave Web Search API.

Returns unverified source candidates only. No scraping, extraction or settlement.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
REQUEST_TIMEOUT_SECONDS = 10
RESULT_COUNT = 10

_TAG_RE = re.compile(r"<[^>]+>")


class LiveSearchError(Exception):
    """User-safe error message. Never contains the API key."""


@dataclass(frozen=True)
class SourceCandidate:
    title: str
    url: str
    snippet: str


def build_query(fighter_a: str, fighter_b: str, event_date: date, event_name: Optional[str] = None) -> str:
    parts = [f'"{fighter_a.strip()}"', f'"{fighter_b.strip()}"', "boxing result", event_date.strftime("%d %B %Y")]
    if event_name and event_name.strip():
        parts.append(event_name.strip())
    return " ".join(parts)


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def search_sources(query: str, api_key: str) -> list[SourceCandidate]:
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query, "count": RESULT_COUNT}
    try:
        response = requests.get(BRAVE_ENDPOINT, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.Timeout:
        raise LiveSearchError("The search request timed out. Please try again.") from None
    except requests.ConnectionError:
        raise LiveSearchError("Could not reach the Brave Search API. Check the network connection and try again.") from None
    except requests.RequestException:
        raise LiveSearchError("The search request failed before a response was received.") from None

    if response.status_code in (401, 403):
        raise LiveSearchError("The Brave Search API rejected the request. Check that BRAVE_SEARCH_API_KEY is valid and active.")
    if response.status_code == 429:
        raise LiveSearchError("Brave Search API rate limit or quota reached. Please wait and try again.")
    if not response.ok:
        raise LiveSearchError(f"Brave Search API returned HTTP {response.status_code}. Please try again later.")

    try:
        payload = response.json()
    except ValueError:
        raise LiveSearchError("The Brave Search API returned an unreadable response.") from None

    web = payload.get("web") if isinstance(payload, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        results = []
    candidates = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        candidates.append(SourceCandidate(_clean(str(item.get("title") or url)), url, _clean(str(item.get("description") or ""))))
    return candidates
