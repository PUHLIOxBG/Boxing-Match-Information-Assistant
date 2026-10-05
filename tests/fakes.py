"""Offline HTTP fakes and fixture pages for tests. No test touches the internet."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

import requests


class FakeResponse:
    def __init__(self, url: str, status: int = 200, body: bytes | str = b"", headers: Optional[dict] = None):
        self.url = url
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": "text/html; charset=utf-8", **(headers or {})}
        self.encoding = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def iter_content(self, size: int):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def close(self) -> None:
        pass


class FakeSession:
    """Routes exact URLs (or 'host/robots.txt') to canned responses; everything else is 404."""

    def __init__(self, routes: Optional[dict] = None, default_robots: str = "User-agent: *\nAllow: /\n"):
        self.routes = dict(routes or {})
        self.default_robots = default_robots
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, headers: Optional[dict] = None, timeout=None, stream: bool = False, allow_redirects: bool = True):
        self.calls.append((url, headers or {}))
        route = self.routes.get(url)
        if route is None and urlsplit(url).path == "/robots.txt":
            return FakeResponse(url, 200, self.default_robots, {"Content-Type": "text/plain"})
        if route is None:
            return FakeResponse(url, 404, "not found")
        if isinstance(route, Exception):
            raise route
        if callable(route):
            return route(url)
        status, body, *rest = route
        return FakeResponse(url, status, body, rest[0] if rest else None)

    def requested(self, fragment: str) -> list[str]:
        return [u for u, _ in self.calls if fragment in u]


class FailingSession(FakeSession):
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("headers") or {}))
        raise requests.ConnectionError("network down")


WIKI_URL = "https://en.wikipedia.org/wiki/Isaac_Cruz"
WIKI_HTML = """<html><head><title>Isaac Cruz - Wikipedia</title></head><body>
<p>On 19 September 2026, Cruz knocked out Nestor Bravo in San Diego.<sup class="reference"><a href="#cite_note-7">[7]</a></sup></p>
<h2 id="Professional_boxing_record">Professional boxing record</h2>
<table class="wikitable"><tr><th>34 fights</th><th>29 wins</th><th>3 losses</th></tr><tr><td>By knockout</td><td>19</td><td>0</td></tr></table>
<table class="wikitable">
<tr><th>No.</th><th>Result</th><th>Record</th><th>Opponent</th><th>Type</th><th>Round, time</th><th>Date</th><th>Location</th><th>Notes</th></tr>
<tr><td>34</td><td>Win</td><td>29–3–2</td><td>Néstor Bravo</td><td>KO</td><td>6 (12), 1:30</td><td>19 Sep 2026</td><td>Pechanga Arena, San Diego</td>
<td>Retained WBC interim super lightweight title<sup class="reference"><a href="#cite_note-8">[8]</a></sup></td></tr>
<tr><td>33</td><td>Draw</td><td>28–3–2</td><td>Lamont Roach Jr.</td><td>MD</td><td>12</td><td>6 Dec 2025</td><td>San Antonio</td><td>Retained WBC interim super lightweight title</td></tr>
</table>
<ol class="references">
<li id="cite_note-7"><a class="external text" href="https://www.boxingnews24.com/2026/09/pitbull-cruz-defeats-nestor-bravo/">Cruz defeats Bravo</a></li>
<li id="cite_note-8"><a class="external text" href="https://www.youtube.com/watch?v=abc">Video</a></li>
</ol></body></html>"""

WBC_URL = "https://wbcboxing.com/en/cruz-kos-bravo/"
WBC_HTML = """<html><head><title>Isaac Cruz KO's Nestor Bravo in San Diego</title>
<meta property="article:published_time" content="2026-09-21T10:00:00+00:00"></head><body><article>
<p>Mexican star Isaac "Pitbull" Cruz roared, by knocking out Puerto Rico's Néstor Bravo in the sixth round of their clash at the Pechanga Arena.</p>
<p>From the first bell, the Interim Super Lightweight Champion of the World Boxing Council applied relentless pressure.</p>
<p>After dropping Bravo in the opening round, the decisive finish came at 1:30 of the sixth round, when Cruz landed a left hook.</p>
<p>Referee Thomas Taylor counted Bravo out.</p>
</article></body></html>"""

MEDIA_URL = "https://www.boxingnews24.com/2026/09/pitbull-cruz-defeats-nestor-bravo/"
MEDIA_HTML = """<html><head><title>Pitbull Cruz defeats Nestor Bravo</title>
<meta property="article:published_time" content="2026-09-20T05:00:00+00:00"></head><body>
<nav><p>Isaac Cruz beat Nestor Bravo by unanimous decision in round 9.</p></nav>
<article>
<p>Isaac "Pitbull" Cruz knocked out Nestor Bravo in the sixth round Saturday night, retaining his WBC interim light welterweight title.</p>
<p>Cruz (29-3-2, 19 KOs), 139 pounds, dropped Bravo (24-2, 17 KOs) during the opening round.</p>
<p>Cruz ended the disorder at 1:30 of round six. Referee Thomas Taylor waved it off.</p>
<p>Cruz will now target Ryan Garcia, and could knock him out next year.</p>
</article></body></html>"""

PREVIEW_URL = "https://www.badlefthook.com/cruz-vs-bravo-preview"
PREVIEW_HTML = """<html><head><title>Cruz vs Bravo preview</title>
<meta property="article:published_time" content="2026-09-10T05:00:00+00:00"></head><body><article>
<p>Isaac Cruz stopped Nestor Bravo in sparring years ago, a story told before the fight.</p></article></body></html>"""


def rss(items: list[tuple[str, str, str, str]]) -> str:
    body = "".join(f"<item><title>{t}</title><link>{link}</link><description>{d}</description><pubDate>{p}</pubDate></item>"
                   for t, link, d, p in items)
    return f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>Feed</title>{body}</channel></rss>"


WBC_SEARCH_URL = "https://wbcboxing.com/en/?s=Cruz+Bravo&feed=rss2"
WBC_SEARCH_RSS = rss([
    ("Isaac Cruz KO's Nestor Bravo in San Diego", WBC_URL, "Cruz stopped Bravo in round 3 says this snippet", "Mon, 21 Sep 2026 10:00:00 +0000"),
    ("Explanations March 2019", "https://wbcboxing.com/en/explanations-2019/", "unrelated", "Fri, 01 Mar 2019 10:00:00 +0000"),
])
MEDIA_SEARCH_URL = "https://www.boxingnews24.com/?s=Cruz+Bravo&feed=rss2"
MEDIA_SEARCH_RSS = rss([
    ("Pitbull Cruz defeats Nestor Bravo", MEDIA_URL, "Cruz wins", "Sun, 20 Sep 2026 05:00:00 +0000"),
    ("Pitbull Cruz says he's willing to fight Ryan Garcia", "https://www.boxingnews24.com/garcia/", "Cruz and Garcia", "Sun, 20 Sep 2026 06:00:00 +0000"),
])
BLH_FEED_URL = "https://www.badlefthook.com/rss/index.xml"
BLH_FEED = rss([("Cruz vs Bravo preview", PREVIEW_URL, "Cruz and Bravo meet Saturday", "Thu, 10 Sep 2026 05:00:00 +0000")])

XML = {"Content-Type": "application/rss+xml; charset=UTF-8"}


def cruz_bravo_routes() -> dict:
    return {
        WIKI_URL: (200, WIKI_HTML),
        WBC_URL: (200, WBC_HTML),
        MEDIA_URL: (200, MEDIA_HTML),
        PREVIEW_URL: (200, PREVIEW_HTML),
        WBC_SEARCH_URL: (200, WBC_SEARCH_RSS, XML),
        MEDIA_SEARCH_URL: (200, MEDIA_SEARCH_RSS, XML),
        BLH_FEED_URL: (200, BLH_FEED, XML),
    }
