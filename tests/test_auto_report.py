"""Automatic match report: fetcher politeness, extraction rules, grading, pipeline. Fully offline."""
from __future__ import annotations

import socket
import sys
from datetime import date
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import auto_report as ar  # noqa: E402
import extraction as ex  # noqa: E402
import web_fetch  # noqa: E402
from fakes import (BLH_FEED_URL, MEDIA_HTML, MEDIA_URL, PREVIEW_HTML, PREVIEW_URL, WIKI_HTML, FailingSession,  # noqa: E402
                   FakeSession, cruz_bravo_routes)

A, B = ex.Boxer.from_name("Isaac Cruz"), ex.Boxer.from_name("Nestor Bravo")
FIGHT = date(2026, 9, 19)
TODAY = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("tests must not use the network")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    web_fetch.clear_robots_cache()
    yield
    web_fetch.clear_robots_cache()


def fetcher(session, **kwargs) -> web_fetch.Fetcher:
    return web_fetch.Fetcher(session=session, sleep=lambda s: None, min_interval=0, **kwargs)


# --------------------------------------------------------------------------- #
# Fetcher politeness
# --------------------------------------------------------------------------- #

def test_user_agent_is_sent_and_identifies_the_app():
    session = FakeSession({MEDIA_URL: (200, MEDIA_HTML)})
    assert fetcher(session).get(MEDIA_URL, "t").ok
    assert all(h["User-Agent"].startswith("BoxingMatchInfoAssistant/") for _, h in session.calls)


def test_robots_disallow_blocks_the_page():
    session = FakeSession({"https://www.boxingnews24.com/robots.txt": (200, "User-agent: *\nDisallow: /2026/\n", {"Content-Type": "text/plain"}),
                           MEDIA_URL: (200, MEDIA_HTML)})
    f = fetcher(session)
    result = f.get(MEDIA_URL, "t")
    assert not result.ok and result.error == "robots"
    assert session.requested(MEDIA_URL) == []
    assert "disallowed by robots.txt" in f.log[-1].outcome


@pytest.mark.parametrize("status, allowed", [(403, False), (401, False), (404, True), (500, False)])
def test_robots_status_rules(status, allowed):
    session = FakeSession({"https://www.boxingnews24.com/robots.txt": (status, "x"), MEDIA_URL: (200, MEDIA_HTML)})
    assert fetcher(session).get(MEDIA_URL, "t").ok is allowed


def test_robots_unreachable_skips_host():
    session = FakeSession({"https://www.boxingnews24.com/robots.txt": requests.Timeout(), MEDIA_URL: (200, MEDIA_HTML)})
    assert not fetcher(session).get(MEDIA_URL, "t").ok
    assert session.requested(MEDIA_URL) == []


@pytest.mark.parametrize("url", ["https://www.google.com/search?q=cruz", "https://www.facebook.com/x", "https://www.instagram.com/p/x",
                                 "https://boxrec.com/en/box-pro/1", "https://www.tapology.com/fightcenter", "https://evil.example/wbcboxing.com"])
def test_non_allowlisted_domains_are_never_requested(url):
    session = FakeSession()
    result = fetcher(session).get(url, "t")
    assert not result.ok and result.error == "domain not allowed"
    assert session.calls == []


def test_redirect_to_non_allowlisted_domain_is_blocked():
    session = FakeSession({MEDIA_URL: (302, "", {"Location": "https://www.facebook.com/login"})})
    result = fetcher(session).get(MEDIA_URL, "t")
    assert not result.ok and session.requested("facebook") == []


def test_redirect_within_allowlist_is_followed_and_rechecked():
    target = "https://www.boxingnews24.com/2026/09/final/"
    session = FakeSession({MEDIA_URL: (301, "", {"Location": "/2026/09/final/"}), target: (200, MEDIA_HTML)})
    result = fetcher(session).get(MEDIA_URL, "t")
    assert result.ok and result.final_url == target


def test_network_errors_are_logged_not_raised():
    f = fetcher(FakeSession({MEDIA_URL: requests.ConnectionError("boom")}))
    result = f.get(MEDIA_URL, "article")
    assert not result.ok and result.error == "ConnectionError"
    assert f.log[-1].outcome == "failed — ConnectionError"


def test_request_budget_is_enforced():
    session = FakeSession({MEDIA_URL: (200, MEDIA_HTML)})
    f = fetcher(session, budget=2)  # robots.txt + one page
    assert f.get(MEDIA_URL, "t").ok
    assert f.get(MEDIA_URL, "t").error == "budget"


def test_oversized_and_non_html_responses_are_rejected():
    big = FakeSession({MEDIA_URL: (200, b"x" * (web_fetch.MAX_BYTES + 10))})
    assert fetcher(big).get(MEDIA_URL, "t").error == "too large"
    web_fetch.clear_robots_cache()
    pdf = FakeSession({MEDIA_URL: (200, b"%PDF", {"Content-Type": "application/pdf"})})
    assert fetcher(pdf).get(MEDIA_URL, "t").error == "content type"


def test_per_host_rate_limit_waits_between_requests():
    clock = {"t": 0.0}
    waits = []
    session = FakeSession({MEDIA_URL: (200, MEDIA_HTML)})
    f = web_fetch.Fetcher(session=session, clock=lambda: clock["t"], sleep=lambda s: (waits.append(s), clock.__setitem__("t", clock["t"] + s)), min_interval=1.5)
    f.get(MEDIA_URL, "t")
    f.get(MEDIA_URL, "t")
    assert waits and all(w == pytest.approx(1.5) for w in waits)


def test_robots_crawl_delay_over_limit_skips_host():
    session = FakeSession({"https://www.boxingnews24.com/robots.txt": (200, "User-agent: *\nCrawl-delay: 60\n", {"Content-Type": "text/plain"}),
                           MEDIA_URL: (200, MEDIA_HTML)})
    assert fetcher(session).get(MEDIA_URL, "t").error == "crawl-delay"


# --------------------------------------------------------------------------- #
# Extraction rules
# --------------------------------------------------------------------------- #

def facts_of(text: str, a=A, b=B) -> dict:
    page = ex.extract_from_text(text, a, b)
    out: dict = {}
    for f in page.facts:
        out.setdefault(f.field, []).append(f.key)
    out["knockdowns"] = [(k.victim, k.round, k.count) for k in page.knockdowns]
    return out


def test_stoppage_report():
    got = facts_of('Isaac "Pitbull" Cruz knocked out Néstor Bravo in the sixth round to retain his WBC interim light welterweight title. '
                   "Referee Thomas Taylor waved it off at 1:30 of round six as Bravo slumped.")
    assert got["winner"] == ["A"] and got["method"] == ["KO"] and got["round"] == [6] and got["time"] == ["1:30"]
    assert got["weight_class"] == ["Super Lightweight"] and got["titles"] == ["WBC interim"] and got["referee"] == ["thomas taylor"]


def test_decision_report_with_scorecards_and_judges():
    got = facts_of("Nestor Bravo outpointed Isaac Cruz by split decision over 12 rounds. "
                   "The judges scored it 115-113, 113-115 and 116-112 for Bravo. Judges Max DeLuca, Zachary Young and Lou Moret scored Cruz vs Bravo.")
    assert got["winner"] == ["B"] and got["method"] == ["SD"]
    assert got["scorecards"] == [((116, 112), (115, 113), (115, 113))]
    assert sorted(got["judges"]) == ["lou moret", "max deluca", "zachary young"]


@pytest.mark.parametrize("text, expected", [
    ("Isaac Cruz and Nestor Bravo fought to a majority draw in San Diego.", "Draw"),
    ("The bout between Isaac Cruz and Nestor Bravo was ruled a no contest after a clash of heads.", "No contest"),
    ("Nestor Bravo was stopped by Isaac Cruz in the sixth round.", "A"),
])
def test_outcome_wording(text, expected):
    assert facts_of(text)["winner"] == [expected]


@pytest.mark.parametrize("text", [
    "Isaac Cruz will knock out Nestor Bravo, he predicts.",
    "Cruz, who stopped Bravo in 2019, returns on Saturday.",
    "Isaac Cruz could beat Nestor Bravo if he starts fast.",
    "Isaac Cruz failed to stop Nestor Bravo.",
    "Isaac Cruz wants a rematch after he beat Nestor Bravo.",
])
def test_future_historical_and_negated_sentences_give_no_outcome(text):
    assert "winner" not in facts_of(text)


def test_fight_records_are_not_methods_or_scorecards():
    got = facts_of("Cruz (29-3-2, 19 KOs) faces Bravo (24-2, 17 KOs) in a decision-heavy matchup with 26-2 judges.")
    assert "method" not in got and "scorecards" not in got


def test_knockout_result_never_creates_a_knockdown():
    got = facts_of("Isaac Cruz knocked out Nestor Bravo in the sixth round. Isaac Cruz stopped Nestor Bravo by TKO in round six.")
    assert got["knockdowns"] == []


@pytest.mark.parametrize("text, expected", [
    ("Cruz dropped Bravo in the first round with a left hook.", [("B", 1, 1)]),
    ("After dropping Bravo in the opening round, Cruz finished the job.", [("B", 1, 1)]),
    ("Bravo was dropped twice in the fourth round by Cruz.", [("B", 4, 2)]),
    ("Cruz scored a knockdown in round 3 against Bravo.", [("B", 3, 1)]),
    ("Bravo floored Cruz in round 2.", [("A", 2, 1)]),
])
def test_explicit_knockdowns(text, expected):
    assert facts_of(text)["knockdowns"] == expected


@pytest.mark.parametrize("text", [
    "Bravo dropped a decision to Cruz in round 12.",          # 'dropped a decision' is not a knockdown
    "Cruz dropped him in the first round.",                    # opponent only a pronoun: not identifiable
    "Cruz dropped Bravo late in the fight.",                   # no round stated
    "Cruz, who dropped Bravo in 2019 in round two, is back.",  # historical
    "Cruz could drop Bravo in the first round.",               # conditional
    "There were no knockdowns as Cruz beat Bravo in round 12.",
])
def test_non_knockdowns_are_ignored(text):
    assert facts_of(text)["knockdowns"] == []


def test_scorecards_must_be_plausible_totals():
    assert "scorecards" not in facts_of("Cruz beat Bravo; the judges scored it 200-15 and 99-1.")


def test_nearly_knocked_out_is_not_a_method():
    assert "method" not in facts_of("Isaac Cruz was nearly knocked out by Nestor Bravo early on.")


def test_same_surname_requires_first_names():
    a, b = ex.Boxer.from_name("Jermall Charlo"), ex.Boxer.from_name("Jermell Charlo")
    assert "winner" not in facts_of("Charlo beat Charlo.", a, b)
    assert facts_of("Jermell Charlo defeated Jermall Charlo by unanimous decision.", a, b)["winner"] == ["B"]


def test_article_text_drops_navigation_and_reads_published_date():
    title, text, published = ex.article_text(MEDIA_HTML.encode())
    assert "unanimous decision in round 9" not in text
    assert published == date(2026, 9, 20) and title.startswith("Pitbull Cruz")


def test_feed_parsing_rss_and_atom():
    rss_items = ex.parse_feed(b"<rss><channel><item><title>Cruz &amp; Bravo</title><link>https://x/1</link>"
                              b"<pubDate>Sun, 20 Sep 2026 05:00:00 +0000</pubDate></item></channel></rss>")
    assert rss_items[0].title == "Cruz & Bravo" and rss_items[0].published == date(2026, 9, 20)
    atom = ex.parse_feed(b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>T</title><link href='https://x/2'/>"
                         b"<updated>2026-09-20T05:00:00Z</updated></entry></feed>")
    assert atom[0].link == "https://x/2"


def test_hostile_or_broken_xml_is_rejected():
    bomb = b"<?xml version='1.0'?><!DOCTYPE l [<!ENTITY a 'aaaa'><!ENTITY b '&a;&a;&a;&a;'>]><rss><channel><item><title>&b;</title></item></channel></rss>"
    assert ex.parse_feed(bomb) == []
    assert ex.parse_feed(b"<rss><channel><item>") == []


def test_wikipedia_record_row():
    row, prose, _ = ex.wikipedia_record(WIKI_HTML.encode(), A, B, "A", FIGHT)
    got = {f.field: f.key for f in row.facts}
    assert got == {"winner": "A", "method": "KO", "scheduled_rounds": 12, "round": 6, "time": "1:30",
                   "titles": "WBC interim", "weight_class": "Super Lightweight"}
    assert "https://www.boxingnews24.com/2026/09/pitbull-cruz-defeats-nestor-bravo/" in prose


def test_wikipedia_decision_row_and_date_window():
    roach = ex.Boxer.from_name("Lamont Roach Jr.")
    row, _, _ = ex.wikipedia_record(WIKI_HTML.encode(), A, roach, "A", date(2025, 12, 7))
    got = {f.field: f.key for f in row.facts}
    assert got["winner"] == "Draw" and got["method"] == "MD" and got["scheduled_rounds"] == 12 and "round" not in got
    assert ex.wikipedia_record(WIKI_HTML.encode(), A, B, "A", date(2026, 9, 1))[0] is None


# --------------------------------------------------------------------------- #
# Grading
# --------------------------------------------------------------------------- #

def src(i: int, tier: str, publisher: str, **facts) -> ar.Source:
    s = ar.Source(i, publisher, tier, publisher, f"https://{publisher}/{i}", "", "", "test")
    s.facts = [ex.Fact(k, v, str(v), "quote") for k, v in facts.items()]
    return s


def test_grading_levels():
    official = src(1, "Official", "wbcboxing.com", winner="A", method="KO")
    media1 = src(2, "Established media", "espn.com", winner="A", method="KO")
    media2 = src(3, "Established media", "bbc.co.uk", winner="A")
    same_pub = src(4, "Established media", "espn.com", winner="A")
    fields, _, _ = ar.aggregate(A, B, [official, media1])
    assert fields["winner"].status == ar.CONFIRMED
    fields, _, _ = ar.aggregate(A, B, [media1, media2])
    assert fields["winner"].status == ar.CORROBORATED and fields["method"].status == ar.SINGLE
    fields, _, _ = ar.aggregate(A, B, [media1, same_pub])
    assert fields["winner"].status == ar.SINGLE  # two articles, one publisher: not independent
    fields, _, _ = ar.aggregate(A, B, [])
    assert fields["winner"].status == ar.NOT_FOUND and fields["winner"].value == "Not found"


def test_conflicts_are_reported():
    fields, _, conflicts = ar.aggregate(A, B, [src(1, "Official", "wbcboxing.com", method="TKO"), src(2, "Established media", "espn.com", method="KO")])
    assert fields["method"].status == ar.CONFLICTING
    assert [alt[0] for alt in fields["method"].alternatives] == ["TKO", "KO"]
    assert conflicts and conflicts[0].startswith("Method:")
    assert ar.overall_confidence({**fields, "winner": ar.FieldResult("winner", "Result", ar.CONFIRMED, "A", [1])})[0] == ar.CONFLICTING


def test_knockdown_grading_and_cross_checks():
    s1 = src(1, "Established media", "espn.com", round=3)
    s1.knockdowns = [ex.KnockdownFact("B", 1, 1, "q"), ex.KnockdownFact("B", 5, 1, "q")]
    s2 = src(2, "Established media", "bbc.co.uk")
    s2.knockdowns = [ex.KnockdownFact("B", 1, 2, "q")]
    _, kds, conflicts = ar.aggregate(A, B, [s1, s2])
    assert kds[0].round == 1 and kds[0].status == ar.CONFLICTING and kds[0].count == "1 / 2"
    assert kds[1].status == ar.SINGLE
    assert any("after the recorded final round 3" in c for c in conflicts)


def test_overall_confidence_is_the_weaker_of_result_and_method():
    fields, _, _ = ar.aggregate(A, B, [src(1, "Official", "wbcboxing.com", winner="A"), src(2, "Established media", "espn.com", method="KO")])
    assert ar.overall_confidence(fields) == (ar.SINGLE, "Weakest of result (confirmed) and method (single source).")


# --------------------------------------------------------------------------- #
# End-to-end pipeline with mocked HTTP
# --------------------------------------------------------------------------- #

def test_pipeline_finds_and_grades_the_report():
    session = FakeSession(cruz_bravo_routes())
    report = ar.find_match_report("Isaac Cruz", "Nestor Bravo", FIGHT, "Cruz vs Bravo", fetcher=fetcher(session), today=TODAY)
    status = {k: (f.status, f.value) for k, f in report.fields.items()}
    assert status["winner"] == (ar.CONFIRMED, "Isaac Cruz")
    assert status["method"] == (ar.CONFIRMED, "KO")
    assert status["round"] == (ar.CONFIRMED, "6") and status["time"] == (ar.CONFIRMED, "1:30")
    assert status["scheduled_rounds"] == (ar.SINGLE, "12")
    # The WBC fixture's weight-class sentence names neither boxer, so it is not used (same-sentence rule).
    assert status["weight_class"] == (ar.CORROBORATED, "Super Lightweight")
    assert status["titles"] == (ar.CORROBORATED, "WBC interim")
    assert status["referee"] == (ar.CONFIRMED, "Thomas Taylor")
    assert status["scorecards"] == (ar.NOT_FOUND, "Not found") and status["judges"][0] == ar.NOT_FOUND
    assert [(k.victim, k.round, k.status) for k in report.knockdowns] == [("Nestor Bravo", 1, ar.CONFIRMED)]
    assert report.overall == ar.CONFIRMED and report.conflicts == []
    # The WBC search snippet claimed round 3; snippets are never evidence.
    assert all("round 3" not in f.quote for s in report.sources for f in s.facts)
    # Only allowlisted hosts were contacted; the YouTube citation was never fetched.
    assert session.requested("youtube") == [] and session.requested("google") == []
    assert {s.name for s in report.sources} >= {"Wikipedia", "WBC", "Boxing News 24"}


def test_preview_articles_are_not_used_as_evidence():
    session = FakeSession({PREVIEW_URL: (200, PREVIEW_HTML)})
    source = ar._article(fetcher(session), ar._Candidate(PREVIEW_URL, "", None, "test"), A, B, FIGHT)
    assert source.facts == [] and "preview" in source.notes[0]


def test_recent_feeds_only_for_recent_fights():
    session = FakeSession(cruz_bravo_routes())
    ar.find_match_report("Isaac Cruz", "Nestor Bravo", FIGHT, fetcher=fetcher(session), today=TODAY)
    assert session.requested(BLH_FEED_URL)
    web_fetch.clear_robots_cache()
    old = FakeSession(cruz_bravo_routes())
    ar.find_match_report("Isaac Cruz", "Nestor Bravo", FIGHT, fetcher=fetcher(old), today=date(2027, 6, 1))
    assert not old.requested(BLH_FEED_URL)


def test_all_requests_failing_still_returns_a_report():
    report = ar.find_match_report("Isaac Cruz", "Nestor Bravo", FIGHT, fetcher=fetcher(FailingSession()), today=TODAY)
    assert all(f.status == ar.NOT_FOUND for f in report.fields.values())
    assert report.overall == ar.NOT_FOUND and not report.found_anything
    assert any("Every automatic request failed" in n for n in report.notes)


def test_future_event_makes_no_requests():
    session = FakeSession(cruz_bravo_routes())
    report = ar.find_match_report("Isaac Cruz", "Nestor Bravo", date(2027, 1, 1), fetcher=fetcher(session), today=TODAY)
    assert session.calls == [] and "future" in report.notes[0]


def test_unexpected_exception_inside_a_source_is_contained(monkeypatch):
    monkeypatch.setattr(ex, "extract_from_text", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad page")))
    report = ar.find_match_report("Isaac Cruz", "Nestor Bravo", FIGHT, fetcher=fetcher(FakeSession(cruz_bravo_routes())), today=TODAY)
    assert any("failed (ValueError)" in n for n in report.notes)
    assert report.fields["winner"].status != ar.NOT_FOUND  # Wikipedia still contributed


def test_canonical_url_strips_tracking():
    assert ar.canonical_url("https://www.bbc.co.uk/sport/x?at_medium=RSS&at_campaign=rss&id=5#top") == "https://www.bbc.co.uk/sport/x?id=5"


# --------------------------------------------------------------------------- #
# Regressions from live pages (Sept/Oct 2026): each produced a wrong fact before
# --------------------------------------------------------------------------- #

BROWN, HEDGES = ex.Boxer.from_name("Pat Brown"), ex.Boxer.from_name("John Hedges")
RUIZ, KNYBA = ex.Boxer.from_name("Andy Ruiz Jr"), ex.Boxer.from_name("Damian Knyba")
WHITTAKER, WALLACE = ex.Boxer.from_name("Ben Whittaker"), ex.Boxer.from_name("Conor Wallace")


def test_beating_the_count_is_not_winning_the_fight():
    got = facts_of("Hedges beat referee Reece Carter's count, but Brown immediately returned to the body.", BROWN, HEDGES)
    assert "winner" not in got and got["referee"] == ["reece carter"]


def test_needed_to_beat_is_not_a_result():
    assert "winner" not in facts_of("Matchroom needed Ruiz Jr to beat Knyba convincingly enough.", RUIZ, KNYBA)


def test_years_ago_round_is_not_this_fight():
    got = facts_of("Seven years ago, Ruiz upset Anthony Joshua, stopping him in the seventh round, and Knyba is next.", RUIZ, KNYBA)
    assert "round" not in got and "winner" not in got


def test_bare_rounds_count_is_not_scheduled_distance():
    assert "scheduled_rounds" not in facts_of("Against a foe who had never gone beyond eight rounds, Ruiz looked ordinary.", RUIZ, KNYBA)


def test_publication_is_not_a_judge():
    assert "judges" not in facts_of("Knyba beat Ruiz on the cards. (The Guardian had it 117-110.)", RUIZ, KNYBA)


def test_decision_pages_report_no_stoppage_round():
    got = facts_of("Damian Knyba upset Andy Ruiz Jr by unanimous decision. Knyba hurt Ruiz in the seventh round and nearly finished him.", RUIZ, KNYBA)
    assert got["method"] == ["UD"] and "round" not in got


@pytest.mark.parametrize("text", [
    'Ben "The Surgeon" Whittaker survived a difficult finish to defeat Conor Wallace by unanimous decision over 12 rounds.',
    "Ben Whittaker Beats Conor Wallace After Late Scare.",
    "Whittaker won on points against Wallace.",
])
def test_whittaker_wording(text):
    assert facts_of(text, WHITTAKER, WALLACE)["winner"] == ["A"]


def test_hyphenated_division_and_chained_titles():
    got = facts_of("Pat Brown won the vacant British and Commonwealth light-heavyweight titles by knocking out John Hedges.", BROWN, HEDGES)
    assert got["weight_class"] == ["Light Heavyweight"] and sorted(got["titles"]) == ["British", "Commonwealth"]


def test_points_does_not_conflict_with_unanimous_decision():
    fields, _, conflicts = ar.aggregate(A, B, [src(1, "Established media", "espn.com", method="UD"), src(2, "Established media", "bbc.co.uk", method="PTS")])
    assert fields["method"].value == "UD" and conflicts == []


def test_partial_scorecards_support_the_full_list():
    full, part = ((117, 110), (114, 113), (114, 113)), ((117, 110), (114, 113))
    fields, _, conflicts = ar.aggregate(A, B, [src(1, "Established media", "espn.com", scorecards=full), src(2, "Established media", "bbc.co.uk", scorecards=part)])
    assert fields["scorecards"].status == ar.CORROBORATED and conflicts == []


def test_previously_unbeaten_is_a_description_not_a_past_fight():
    got = facts_of("Facing a previously unbeaten opponent, Pat Brown beat John Hedges in the sixth round.", BROWN, HEDGES)
    assert got["winner"] == ["A"]
    assert "winner" not in facts_of("Brown previously beat Hedges.", BROWN, HEDGES)


@pytest.mark.parametrize("text", [
    "Ben Whittaker defends his WBC Silver title against dangerous knockout artist Connor Wallace in Birmingham.",
    "Wallace, a knockout artist with real power, is Whittaker's toughest test.",
    "Whittaker respects Wallace's knockout power.",
])
def test_knockout_descriptions_are_not_a_method(text):
    assert "method" not in facts_of(text, WHITTAKER, WALLACE)


def test_method_still_found_in_result_sentences():
    assert facts_of("Whittaker won by unanimous decision.", WHITTAKER, WALLACE)["method"] == ["UD"]
    assert facts_of("Cruz stopped Bravo by TKO.")["method"] == ["TKO"]



# --------------------------------------------------------------------------- #
# Same-sentence rule: details must name a target boxer in the same sentence
# --------------------------------------------------------------------------- #

def test_undercard_sentence_after_main_event_is_not_carried_over():
    text = ("Ben Whittaker defeated Conor Wallace by unanimous decision to retain his IBF light heavyweight title. "
            "Bilal Fawaz retained the British and Commonwealth super-welterweight titles with a knockout of Eithan James in the eighth round.")
    got = facts_of(text, WHITTAKER, WALLACE)
    assert got["weight_class"] == ["Light Heavyweight"] and got["titles"] == ["IBF"]
    assert got["winner"] == ["A"] and got["method"] == ["UD"]


@pytest.mark.parametrize("text, field", [
    ("Whittaker won. The southpaw won the Australian light heavyweight title earlier in his career.", "weight_class"),
    ("Whittaker won. It was for the vacant WBO International title.", "titles"),
    ("Whittaker won. The judges scored it 117-111, 116-112 and 115-113.", "scorecards"),
    ("Whittaker won. Referee Kieran McCann waved it off.", "referee"),
    ("Whittaker won. Judges Max DeLuca, Zachary Young and Lou Moret scored it.", "judges"),
])
def test_details_from_a_sentence_without_a_target_boxer_are_ignored(text, field):
    assert field not in facts_of(text, WHITTAKER, WALLACE)


def test_undercard_wording_blocks_details_even_with_a_target_name():
    got = facts_of("On the undercard of Whittaker vs Wallace, Fawaz retained the British super-welterweight title and dropped James in round two.",
                   WHITTAKER, WALLACE)
    assert "weight_class" not in got and "titles" not in got and got["knockdowns"] == []


def test_knockdown_requires_a_named_fighter_in_the_same_sentence():
    assert facts_of("Cruz beat Bravo. He was dropped in the first round.")["knockdowns"] == []
    assert facts_of("Cruz dropped Bravo in the first round.")["knockdowns"] == [("B", 1, 1)]


def test_round_time_and_scheduled_rounds_unchanged_by_same_sentence_rule():
    got = facts_of("Isaac Cruz knocked out Nestor Bravo in a 12-round title fight. Referee Thomas Taylor waved it off at 1:30 of round six.")
    assert got["round"] == [6] and got["time"] == ["1:30"] and got["scheduled_rounds"] == [12]


def test_unreadable_javascript_page_is_a_link_not_evidence():
    url = "https://www.espn.com/boxing/story/_/id/1/cruz-bravo"
    session = FakeSession({url: (200, "<html><head><title>Cruz beats Bravo - ESPN</title></head><body><div id='root'></div></body></html>")})
    source = ar._article(fetcher(session), ar._Candidate(url, "Cruz beats Bravo", None, "test"), A, B, FIGHT)
    assert source.facts == [] and "could not be read without JavaScript" in source.notes[0]


def test_removed_search_feeds_are_not_requested():
    assert not any("worldboxingnews" in s or "fightmag" in s for s in __import__("sources").SEARCH_FEED_SITES)
    session = FakeSession(cruz_bravo_routes())
    ar.find_match_report("Isaac Cruz", "Nestor Bravo", FIGHT, fetcher=fetcher(session), today=TODAY)
    assert not session.requested("worldboxingnews") and not session.requested("fightmag")
