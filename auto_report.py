"""Automatic match report: discover public sources, extract facts, grade agreement.

Discovery uses only free, keyless, robots.txt-permitted endpoints:
  * Wikipedia boxer articles (/wiki/ pages) — the "Professional boxing record" row,
    plus the citation links attached to it;
  * site-search RSS feeds published by sanctioning bodies, a promoter and boxing media;
  * recent-news RSS feeds of established outlets (for fights in the last few weeks).
Feed titles and snippets are used only to locate articles — never as evidence.
Facts come from the article body or the record table, with a quote and a link.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

import extraction as ex
import sources
from web_fetch import Fetcher, LogEntry

CONFIRMED, CORROBORATED, SINGLE, CONFLICTING, NOT_FOUND = "Confirmed", "Corroborated", "Single source", "Conflicting", "Not found"
STATUS_RANK = {CONFLICTING: 0, NOT_FOUND: 1, SINGLE: 2, CORROBORATED: 3, CONFIRMED: 4}
FIELDS = (
    ("winner", "Result"), ("method", "Method"), ("round", "Round"), ("time", "Time"), ("scheduled_rounds", "Scheduled rounds"),
    ("weight_class", "Weight class"), ("titles", "Titles"), ("scorecards", "Scorecards"), ("referee", "Referee"), ("judges", "Judges"),
)
MULTI_VALUE_FIELDS = {"titles", "judges"}  # several values can all be true at once
MAX_ARTICLES = 8
MAX_PER_PUBLISHER = 2
RECENT_FEED_DAYS = 21
MIN_READABLE_WORDS = 40  # JavaScript-rendered pages (e.g. ESPN) have ~0 words in their HTML; short official reports have 150+
_RESULT_WORDS = re.compile(r"\b(beats?|stops?|stopped|defeats?|defeated|knocks? out|KOs?|TKOs?|wins?|won|outpoints?|results?|decision|retains?|dethrones?|edges?|drops?)\b", re.I)
_TRACKING = re.compile(r"^(utm_|at_|ocid|cmp|fbclid|gclid|ref$|src$)", re.I)


@dataclass
class Source:
    id: int
    name: str
    tier: str
    publisher: str
    url: str
    title: str
    published: str
    via: str
    facts: list[ex.Fact] = field(default_factory=list)
    knockdowns: list[ex.KnockdownFact] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class FieldResult:
    field: str
    label: str
    status: str
    value: str
    source_ids: list[int]
    alternatives: list[tuple[str, str, list[int]]] = field(default_factory=list)  # (value, status, source ids)


@dataclass
class KnockdownResult:
    victim: str
    scorer: str
    round: int
    count: str
    status: str
    source_ids: list[int]


@dataclass
class MatchReport:
    boxer_a: str
    boxer_b: str
    event_date: date
    event_name: str
    fields: dict[str, FieldResult]
    knockdowns: list[KnockdownResult]
    overall: str
    overall_reason: str
    conflicts: list[str]
    sources: list[Source]
    log: list[LogEntry]
    notes: list[str]

    @property
    def found_anything(self) -> bool:
        return any(f.status != NOT_FOUND for f in self.fields.values()) or bool(self.knockdowns)


@dataclass
class _Candidate:
    url: str
    title: str
    published: Optional[date]
    via: str


def _feed_name(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return "BBC Sport" if host in sources.FEED_ONLY_HOSTS else sources.describe(host)[0]


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #

def _wikipedia(fetcher: Fetcher, subject: ex.Boxer, opponent: ex.Boxer, key: str, event_date: date) -> tuple[Optional[Source], list[_Candidate]]:
    for title in (f"{subject.full} (boxer)", subject.full):
        url = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
        page = fetcher.get(url, f"Wikipedia article for {subject.full}")
        if not page.ok or not ex.is_boxer_article(page.content, subject):
            continue
        row, prose_urls, page_title = ex.wikipedia_record(page.content, subject, opponent, key, event_date)
        cited = (row.cited_urls if row else []) + prose_urls
        candidates = [_Candidate(u, "", None, f"cited by Wikipedia ({subject.full})") for u in cited]
        if not row:
            return None, candidates
        source = Source(0, "Wikipedia", sources.REFERENCE, "wikipedia.org", page.final_url + "#Professional_boxing_record",
                        page_title, "", "Wikipedia article (professional boxing record table)", facts=row.facts)
        return source, candidates
    return None, []


def _feed_candidates(fetcher: Fetcher, url: str, purpose: str, a: ex.Boxer, b: ex.Boxer, event_date: date) -> list[_Candidate]:
    page = fetcher.get(url, purpose)
    if not page.ok:
        return []
    found = []
    for item in ex.parse_feed(page.content):
        if not item.link.startswith("http") or not ex.mentions_both(f"{item.title} {item.summary}", a, b):
            continue
        if item.published and not (event_date - timedelta(days=1) <= item.published <= event_date + timedelta(days=60)):
            continue
        found.append(_Candidate(item.link, item.title, item.published, purpose))
    return found


def _rank(candidates: list[_Candidate], event_name: str, event_date: date) -> list[_Candidate]:
    unique: dict[str, _Candidate] = {}
    for c in candidates:
        host = urlsplit(c.url).hostname or ""
        if sources.describe(host)[1] not in (sources.OFFICIAL, sources.MEDIA):
            continue
        unique.setdefault(canonical_url(c.url), c)
    event_words = {w for w in ex.fold(event_name).split() if len(w) > 2 and w != "vs"}

    def score(c: _Candidate) -> tuple:
        tier = sources.describe(urlsplit(c.url).hostname or "")[1]
        title = ex.fold(c.title)
        closeness = abs((c.published - event_date).days) if c.published else 99
        return (tier != sources.OFFICIAL, not _RESULT_WORDS.search(c.title), -sum(w in title for w in event_words), closeness)

    chosen, per_publisher = [], {}
    for c in sorted(unique.values(), key=score):
        pub = sources.publisher(urlsplit(c.url).hostname or "")
        if per_publisher.get(pub, 0) >= MAX_PER_PUBLISHER:
            continue
        per_publisher[pub] = per_publisher.get(pub, 0) + 1
        chosen.append(c)
        if len(chosen) >= MAX_ARTICLES:
            break
    return chosen


def _article(fetcher: Fetcher, c: _Candidate, a: ex.Boxer, b: ex.Boxer, event_date: date) -> Optional[Source]:
    page = fetcher.get(c.url, "article")
    if not page.ok:
        return None
    title, text, published = ex.article_text(page.content)
    host = urlsplit(page.final_url).hostname or ""
    name, tier = sources.describe(host)
    published = published or c.published
    source = Source(0, name, tier, sources.publisher(host), page.final_url, title or c.title,
                    published.isoformat() if published else "", c.via)
    if published and published < event_date - timedelta(days=1):
        source.notes.append("Published before the fight — treated as a preview; no facts used.")
        return source
    if len(text.split()) < MIN_READABLE_WORDS:
        source.notes.append("Page content could not be read without JavaScript — listed as a link only, not used as evidence.")
        return source
    if not ex.mentions_both(text, a, b):
        source.notes.append("Page body does not name both boxers; no facts used.")
        return source
    facts = ex.extract_from_text(text, a, b)
    source.facts, source.knockdowns, source.notes = facts.facts, facts.knockdowns, facts.notes
    if not facts.facts and not facts.knockdowns:
        source.notes.append("No result facts matched the extraction rules.")
    return source


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def _grade(evidence: list[tuple[object, str, Source]]) -> tuple[str, list[tuple[str, str, list[int]]]]:
    groups: dict[object, tuple[str, list[Source]]] = {}
    for key, display, src in evidence:
        groups.setdefault(key, (display, []))[1].append(src)

    def status_of(srcs: list[Source]) -> str:
        if any(s.tier == sources.OFFICIAL for s in srcs):
            return CONFIRMED
        return CORROBORATED if len({s.publisher for s in srcs}) >= 2 else SINGLE

    alternatives = [(display, status_of(srcs), sorted({s.id for s in srcs})) for display, srcs in groups.values()]
    alternatives.sort(key=lambda alt: (-STATUS_RANK[alt[1]], -len(alt[2])))
    if not alternatives:
        return NOT_FOUND, []
    if len(alternatives) > 1:
        return CONFLICTING, alternatives
    return alternatives[0][1], alternatives


def _merge_partial_scorecards(evidence: list[tuple[object, str, Source]]) -> list[tuple[object, str, Source]]:
    """A source listing only some cards agrees with a fuller list that contains them."""
    def contains(full: tuple, part: tuple) -> bool:
        remaining = list(full)
        for card in part:
            if card not in remaining:
                return False
            remaining.remove(card)
        return True

    merged = []
    for key, display, src in evidence:
        fuller = [(k, d) for k, d, _ in evidence if len(k) > len(key) and contains(k, key)]
        if fuller and len({k for k, _ in fuller}) == 1:  # unambiguous superset
            key, display = fuller[0]
        merged.append((key, display, src))
    return merged


def aggregate(a: ex.Boxer, b: ex.Boxer, found: list[Source]) -> tuple[dict[str, FieldResult], list[KnockdownResult], list[str]]:
    fields: dict[str, FieldResult] = {}
    conflicts: list[str] = []
    for key, label in FIELDS:
        evidence = [(f.key, f.display, s) for s in found for f in s.facts if f.field == key]
        if key in MULTI_VALUE_FIELDS:
            items = []
            for value in dict.fromkeys(k for k, _, _ in evidence):
                _, alts = _grade([e for e in evidence if e[0] == value])
                items.append(alts[0])
            if not items:
                fields[key] = FieldResult(key, label, NOT_FOUND, "Not found", [])
            else:
                status = min((i[1] for i in items), key=STATUS_RANK.get)
                fields[key] = FieldResult(key, label, status, ", ".join(i[0] for i in items),
                                          sorted({sid for i in items for sid in i[2]}), items)
            continue
        if key == "method" and any(k in ex.DECISIONS for k, _, _ in evidence):
            # "On points" is compatible with any specific decision type; it neither conflicts nor adds support.
            evidence = [e for e in evidence if e[0] != "PTS"]
        if key == "scorecards":
            evidence = _merge_partial_scorecards(evidence)
        status, alts = _grade(evidence)
        if status == NOT_FOUND:
            fields[key] = FieldResult(key, label, NOT_FOUND, "Not found", [])
        elif status == CONFLICTING:
            fields[key] = FieldResult(key, label, CONFLICTING, " / ".join(alt[0] for alt in alts), sorted({i for alt in alts for i in alt[2]}), alts)
            conflicts.append(f"{label}: " + "; ".join(f"{alt[0]} ({', '.join(f'[{i}]' for i in alt[2])})" for alt in alts))
        else:
            fields[key] = FieldResult(key, label, status, alts[0][0], alts[0][2], alts)

    names = {"A": a.full, "B": b.full}
    kd_groups: dict[tuple[str, int], list[tuple[int, Source]]] = {}
    for s in found:
        for kd in s.knockdowns:
            kd_groups.setdefault((kd.victim, kd.round), []).append((kd.count, s))
    knockdowns = []
    for (victim, round_no), entries in sorted(kd_groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        status, _ = _grade([(True, "", s) for _, s in entries])
        counts = sorted({c for c, _ in entries})
        if len(counts) > 1:
            status = CONFLICTING
            conflicts.append(f"Knockdowns of {names[victim]} in round {round_no}: sources report {' vs '.join(map(str, counts))}.")
        knockdowns.append(KnockdownResult(names[victim], names["B" if victim == "A" else "A"], round_no,
                                          " / ".join(map(str, counts)), status, sorted({s.id for _, s in entries})))

    stop_round = fields["round"]
    if stop_round.status not in (NOT_FOUND, CONFLICTING):
        late = [k for k in knockdowns if k.round > int(stop_round.value)]
        for k in late:
            conflicts.append(f"Knockdown reported in round {k.round}, after the recorded final round {stop_round.value}.")
    if fields["winner"].value == "Draw" and fields["method"].value in {"KO", "TKO", "RTD", "DQ"}:
        conflicts.append(f"Result 'Draw' is inconsistent with method {fields['method'].value}.")
    return fields, knockdowns, conflicts


def overall_confidence(fields: dict[str, FieldResult]) -> tuple[str, str]:
    winner, method = fields["winner"], fields["method"]
    if winner.status == NOT_FOUND:
        return NOT_FOUND, "No source stated the result of this fight."
    if CONFLICTING in (winner.status, method.status):
        return CONFLICTING, "Sources disagree on the result or method — review the conflicts below."
    if method.status == NOT_FOUND:
        return winner.status, f"Result is {winner.status.lower()}; the method was not found."
    level = min((winner.status, method.status), key=STATUS_RANK.get)
    return level, f"Weakest of result ({winner.status.lower()}) and method ({method.status.lower()})."


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def find_match_report(boxer_a: str, boxer_b: str, event_date: date, event_name: str = "",
                      fetcher: Optional[Fetcher] = None, today: Optional[date] = None) -> MatchReport:
    """Never raises: failures are reported in ``notes`` and ``log``."""
    fetcher = fetcher or Fetcher()
    today = today or ex.utc_today()
    a, b = ex.Boxer.from_name(boxer_a), ex.Boxer.from_name(boxer_b)
    notes: list[str] = []
    found: list[Source] = []

    def finish() -> MatchReport:
        for i, s in enumerate(found, start=1):
            s.id = i
        with_facts = [s for s in found if s.facts or s.knockdowns]
        fields, knockdowns, conflicts = aggregate(a, b, with_facts)
        overall, reason = overall_confidence(fields)
        return MatchReport(a.full, b.full, event_date, event_name.strip(), fields, knockdowns, overall, reason,
                           conflicts, found, list(fetcher.log), notes)

    if not a.surname or not b.surname:
        notes.append("Both boxer names are required.")
        return finish()
    if event_date > today + timedelta(days=1):
        notes.append("The event date is in the future, so no result can exist yet. Nothing was searched.")
        return finish()

    try:
        query = quote_plus(f"{a.surname} {b.surname}")
        tasks = [("wikipedia", (a, b, "A")), ("wikipedia", (b, a, "B"))]
        tasks += [("feed", (f"{site}/?s={query}&feed=rss2", f"site search: {sources.describe(urlsplit(site).hostname)[0]}")) for site in sources.SEARCH_FEED_SITES]
        if (today - event_date).days <= RECENT_FEED_DAYS:
            tasks += [("feed", (url, f"recent feed: {_feed_name(url)}")) for url in sources.RECENT_FEEDS]

        def run(task):
            kind, args = task
            try:
                if kind == "wikipedia":
                    return _wikipedia(fetcher, *args, event_date)
                return None, _feed_candidates(fetcher, *args, a, b, event_date)
            except Exception as error:  # noqa: BLE001 - one bad source must not break the report
                notes.append(f"A discovery step failed ({type(error).__name__}); it was skipped.")
                return None, []

        candidates: list[_Candidate] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for wiki_source, found_candidates in pool.map(run, tasks):
                if wiki_source:
                    found.append(wiki_source)
                candidates.extend(found_candidates)

        chosen = _rank(candidates, event_name, event_date)
        if not chosen and not found:
            notes.append("No public source matching both boxers was found by the automatic search.")

        def read(c: _Candidate) -> Optional[Source]:
            try:
                return _article(fetcher, c, a, b, event_date)
            except Exception as error:  # noqa: BLE001
                notes.append(f"Reading {urlsplit(c.url).hostname} failed ({type(error).__name__}); it was skipped.")
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            found.extend(s for s in pool.map(read, chosen) if s)
    except Exception as error:  # noqa: BLE001 - last line of defence for the UI
        notes.append(f"Automatic retrieval stopped unexpectedly ({type(error).__name__}). Results may be incomplete.")
    if fetcher.log and all(not e.outcome.startswith("HTTP 200") for e in fetcher.log if e.purpose != "robots.txt"):
        notes.append("Every automatic request failed or was blocked. Use the manual source links below.")
    return finish()
