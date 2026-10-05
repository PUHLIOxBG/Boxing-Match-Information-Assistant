"""Streamlit UI tests. Run with: python -m pytest  (no internet needed)"""
from __future__ import annotations

import socket
import sys
from datetime import date
from pathlib import Path

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import auto_report as ar  # noqa: E402
import web_fetch  # noqa: E402
from fakes import FakeSession, cruz_bravo_routes  # noqa: E402

APP = str(ROOT / "app.py")
MODES = ["Demo search", "Free source discovery", "Automatic match report"]
REAL_FIND = ar.find_match_report


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("The app must not reach the network during tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    st.cache_data.clear()
    web_fetch.clear_robots_cache()
    yield
    st.cache_data.clear()


def run_app(mode: str = "Demo search") -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    if mode != "Demo search":
        at.sidebar.radio[0].set_value(mode).run()
    assert not at.exception
    return at


def all_text(at: AppTest) -> str:
    parts = [*at.markdown, *at.caption, *at.info, *at.warning, *at.error, *at.success]
    return "\n".join(p.value for p in parts)


def search(at: AppTest, a: str = "Isaac Cruz", b: str = "Nestor Bravo", when: date = date(2026, 9, 19)) -> AppTest:
    at.text_input[0].input(a)
    at.text_input[1].input(b)
    at.date_input[0].set_value(when)
    at.button[0].click().run()
    assert not at.exception
    return at


# Existing modes (unchanged) ----------------------------------------------------

def test_sidebar_modes():
    assert run_app().sidebar.radio[0].options == MODES


def test_demo_search_match_report():
    at = run_app()
    at.text_input[0].input("Isaac Cruz")
    at.text_input[1].input("Nestor Bravo")
    at.button[0].click().run()
    headings = [m.value for m in at.main.markdown if m.value.startswith("#")]
    assert headings == ["### Match report", "#### Knockdown evidence", "#### Officials and event metadata", "#### Evidence ledger", "#### Trader note", "#### Settlement support"]


def test_demo_no_match():
    at = run_app()
    at.text_input[0].input("Nobody")
    at.text_input[1].input("Else")
    at.button[0].click().run()
    assert at.error[0].value.startswith("No exact demo match found.")


def test_demo_load_report():
    at = run_app()
    at.selectbox[0].set_value("Pat Brown vs John Hedges")
    next(b for b in at.button if b.label == "Load report").click().run()
    assert "Brown vs Hedges · Co-op Live, Manchester, UK" in all_text(at)


def test_free_source_discovery_links():
    at = run_app("Free source discovery")
    at.text_input[0].input("Isaac Cruz")
    at.text_input[1].input("Nestor Bravo")
    at.button[0].click().run()
    links = [m.value for m in at.markdown if "Unverified manual source link" in m.value]
    assert len(links) == 6 and all("target='_blank'" in link for link in links)


# Automatic match report --------------------------------------------------------

def test_automatic_mode_has_only_the_lookup_form():
    at = run_app("Automatic match report")
    assert [t.label for t in at.text_input] == ["Boxer A", "Boxer B", "Event name (optional)"]
    assert len(at.date_input) == 1 and len(at.main.selectbox) == 0 and len(at.number_input) == 0
    assert [b.label for b in at.button] == ["Find match report"]
    assert "do not settle any market" in at.warning[0].value


def test_automatic_mode_requires_both_names():
    at = run_app("Automatic match report")
    at.text_input[0].input("Isaac Cruz")
    at.button[0].click().run()
    assert at.error[0].value == "Please enter both boxer names."


def test_automatic_report_renders_found_facts(monkeypatch):
    def fake_find(a, b, when, event):
        fetcher = web_fetch.Fetcher(session=FakeSession(cruz_bravo_routes()), sleep=lambda s: None, min_interval=0)
        return REAL_FIND(a, b, when, event, fetcher=fetcher, today=date(2026, 10, 5))
    monkeypatch.setattr(ar, "find_match_report", fake_find)
    at = search(run_app("Automatic match report"))
    text = all_text(at)
    assert "### Found match report" in text
    assert "Isaac Cruz vs Nestor Bravo" in text
    facts_table = next(m.value for m in at.markdown if "<th>Field</th>" in m.value)
    assert "Thomas Taylor" in facts_table and "[1] Wikipedia" in facts_table and ">Confirmed<" in facts_table
    assert ">Not found<" in facts_table  # scorecards / judges
    kd_table = next(m.value for m in at.markdown if "<th>Fighter down</th>" in m.value)
    assert "Nestor Bravo" in kd_table and "<td>1</td>" in kd_table
    assert "No disagreements were detected" in text
    assert "#### Evidence ledger" in text and "Retrieval log" in "".join(e.label for e in at.expander)
    assert sum("Unverified manual source link" in m.value for m in at.markdown) == 6  # fallback links retained


def test_automatic_report_when_all_requests_fail(monkeypatch):
    def refuse(self, url, **kwargs):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests.Session, "get", refuse)
    at = search(run_app("Automatic match report"))
    text = all_text(at)
    assert "Every automatic request failed or was blocked" in text
    assert "No facts about this fight were found automatically" in text
    assert "Not found" in text
    assert sum("Unverified manual source link" in m.value for m in at.markdown) == 6


def test_automatic_report_escapes_source_content(monkeypatch):
    def hostile(a, b, when, event):
        source = ar.Source(1, "<b>Evil</b>", "Established media", "espn.com", "https://www.espn.com/x'><script>", "<script>alert(1)</script>", "", "test")
        source.facts = [ar.ex.Fact("winner", "A", a, "<img src=x onerror=alert(1)>")]
        fields, kds, conflicts = ar.aggregate(ar.ex.Boxer.from_name(a), ar.ex.Boxer.from_name(b), [source])
        overall, reason = ar.overall_confidence(fields)
        return ar.MatchReport(a, b, when, event, fields, kds, overall, reason, conflicts, [source], [], [])
    monkeypatch.setattr(ar, "find_match_report", hostile)
    at = search(run_app("Automatic match report"))
    html_blocks = [m.value for m in at.markdown if "<" in m.value]
    assert html_blocks and not any("<script>" in h or "<img" in h or "<b>Evil" in h for h in html_blocks)


def test_automatic_report_survives_an_unexpected_crash(monkeypatch):
    monkeypatch.setattr(ar, "find_match_report", lambda *a: (_ for _ in ()).throw(RuntimeError("bug")))
    at = search(run_app("Automatic match report"))
    assert "Automatic retrieval failed unexpectedly" in all_text(at)
    assert sum("Unverified manual source link" in m.value for m in at.markdown) == 6
