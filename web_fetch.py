"""Polite, allowlisted HTTP fetching for automatic match reports.

Every request is checked against a domain allowlist and the host's robots.txt,
is rate limited per host, has strict timeouts and a size cap, and is logged.
Redirects are followed manually so each hop is re-checked. Nothing here raises
on network failure: callers receive a FetchResult with ``ok=False``.
"""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

import requests

import sources

USER_AGENT = (
    "BoxingMatchInfoAssistant/1.0 (+https://github.com/PUHLIOxBG/Boxing-Match-Information-Assistant; "
    "post-fight research for manual settlement; low-rate)"
)
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 12
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 3
MIN_HOST_INTERVAL = 1.5  # seconds between requests to the same host
MAX_CRAWL_DELAY = 10  # skip hosts whose robots.txt asks for more than this
ROBOTS_TTL = 3600
ACCEPTED_TYPES = ("text/html", "application/xhtml", "application/rss", "application/atom", "application/xml", "text/xml")

_robots_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}
_robots_lock = threading.Lock()


@dataclass
class LogEntry:
    url: str
    purpose: str
    outcome: str


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: Optional[int] = None
    text: str = ""
    content: bytes = b""
    final_url: str = ""
    error: str = ""


class Fetcher:
    """One instance per lookup; enforces the request budget and deadline."""

    def __init__(self, session: Optional[requests.Session] = None, budget: int = 60, deadline_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 min_interval: float = MIN_HOST_INTERVAL):
        self.session = session or requests.Session()
        self.budget = budget
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + deadline_s
        self.min_interval = min_interval
        self.log: list[LogEntry] = []
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_hit: dict[str, float] = {}

    # -- bookkeeping -----------------------------------------------------------
    def _record(self, url: str, purpose: str, outcome: str) -> None:
        with self._lock:
            self.log.append(LogEntry(url, purpose, outcome))

    def _take_budget(self) -> bool:
        with self._lock:
            if self.budget <= 0 or self.clock() > self.deadline:
                return False
            self.budget -= 1
            return True

    def _wait_turn(self, host: str, delay: float) -> None:
        with self._lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._last_hit.get(host, -1e9) + delay - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last_hit[host] = self.clock()

    # -- robots.txt ------------------------------------------------------------
    def _robots(self, scheme: str, host: str) -> Optional[urllib.robotparser.RobotFileParser]:
        key = f"{scheme}://{host}"
        with _robots_lock:
            cached = _robots_cache.get(key)
            if cached and time.time() - cached[0] < ROBOTS_TTL:
                return cached[1]
        if not self._take_budget():
            return None
        parser = urllib.robotparser.RobotFileParser()
        robots_url = key + "/robots.txt"
        self._wait_turn(host, self.min_interval)
        try:
            response = self.session.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            status = response.status_code
            if status in (401, 403):
                parser.disallow_all = True  # same rule as urllib.robotparser
            elif 400 <= status < 500:
                parser.allow_all = True  # no robots.txt: crawling permitted (RFC 9309)
            elif status >= 500:
                parser.disallow_all = True  # server error: be conservative
            else:
                parser.parse(response.text[:500_000].splitlines())
            self._record(robots_url, "robots.txt", f"HTTP {status}")
        except requests.RequestException as error:
            parser.disallow_all = True
            self._record(robots_url, "robots.txt", f"unreachable ({type(error).__name__}) — host skipped")
        with _robots_lock:
            _robots_cache[key] = (time.time(), parser)
        return parser

    # -- public ----------------------------------------------------------------
    def get(self, url: str, purpose: str) -> FetchResult:
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            host = (parts.hostname or "").lower()
            if parts.scheme not in ("http", "https") or not sources.is_fetch_allowed(host):
                self._record(current, purpose, "skipped — domain not on the allowlist")
                return FetchResult(url, False, error="domain not allowed")
            robots = self._robots(parts.scheme, parts.netloc.lower())
            if robots is None:
                self._record(current, purpose, "skipped — request budget or time limit reached")
                return FetchResult(url, False, error="budget")
            if not robots.can_fetch(USER_AGENT, current):
                self._record(current, purpose, "skipped — disallowed by robots.txt")
                return FetchResult(url, False, error="robots")
            crawl_delay = robots.crawl_delay(USER_AGENT) or 0
            if crawl_delay > MAX_CRAWL_DELAY:
                self._record(current, purpose, f"skipped — robots.txt crawl-delay {crawl_delay}s")
                return FetchResult(url, False, error="crawl-delay")
            if not self._take_budget():
                self._record(current, purpose, "skipped — request budget or time limit reached")
                return FetchResult(url, False, error="budget")
            self._wait_turn(parts.netloc.lower(), max(self.min_interval, float(crawl_delay)))
            try:
                response = self.session.get(current, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                                            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True, allow_redirects=False)
            except requests.RequestException as error:
                self._record(current, purpose, f"failed — {type(error).__name__}")
                return FetchResult(url, False, error=type(error).__name__)
            try:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                    self._record(current, purpose, f"HTTP {response.status_code} redirect")
                    current = urljoin(current, response.headers["Location"])
                    continue
                if response.status_code != 200:
                    self._record(current, purpose, f"failed — HTTP {response.status_code}")
                    return FetchResult(url, False, status=response.status_code, error=f"HTTP {response.status_code}")
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and not content_type.startswith(ACCEPTED_TYPES):
                    self._record(current, purpose, f"skipped — content type {content_type.split(';')[0]}")
                    return FetchResult(url, False, status=200, error="content type")
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        self._record(current, purpose, "skipped — response larger than 3 MB")
                        return FetchResult(url, False, status=200, error="too large")
                encoding = response.encoding or "utf-8"
                try:
                    text = bytes(body).decode(encoding, errors="replace")
                except LookupError:
                    text = bytes(body).decode("utf-8", errors="replace")
                self._record(current, purpose, "HTTP 200")
                return FetchResult(url, True, status=200, text=text, content=bytes(body), final_url=current)
            except requests.RequestException as error:
                self._record(current, purpose, f"failed — {type(error).__name__}")
                return FetchResult(url, False, error=type(error).__name__)
            finally:
                response.close()
        self._record(current, purpose, "failed — too many redirects")
        return FetchResult(url, False, error="redirects")


def clear_robots_cache() -> None:
    with _robots_lock:
        _robots_cache.clear()
