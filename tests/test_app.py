"""Run with: python -m pytest"""
from __future__ import annotations

import csv
import io
import json
import socket
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import report_builder as rb  # noqa: E402

APP = str(ROOT / "app.py")
MODES = ["Demo search", "Free source discovery", "Build verified report"]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("The app must not make network requests")
    monkeypatch.setattr(socket.socket, "connect", blocked)


def run_app(mode: str = "Demo search") -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    if mode != "Demo search":
        at.sidebar.radio[0].set_value(mode).run()
    assert not at.exception
    return at


def all_text(at: AppTest) -> str:
    parts = [*at.markdown, *at.caption, *at.info, *at.warning, *at.error, *at.success]
    return "\n".join(p.value for p in parts)


# Existing modes ---------------------------------------------------------------

def test_sidebar_modes():
    assert run_app().sidebar.radio[0].options == MODES


def test_demo_search_match_report():
    at = run_app()
    at.text_input[0].input("Isaac Cruz")
    at.text_input[1].input("Nestor Bravo")
    at.button[0].click().run()
    assert not at.exception
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
    assert len(links) == 6
    assert all("target='_blank'" in link for link in links)


# Build verified report: UI -----------------------------------------------------

def test_report_mode_initial_state():
    at = run_app("Build verified report")
    assert at.error[0].value == f"**{rb.DISCLAIMER}**"
    text = all_text(at)
    assert "### Match report preview" in text
    assert "Official result is Unknown" in text
    assert "Unavailable" in text
    assert [b.label for b in at.get("download_button")] == ["Download JSON", "Download CSV"]


def fill_cruz_bravo(at: AppTest) -> AppTest:
    at.text_input(key="report_boxer_a").input("Isaac Cruz")
    at.text_input(key="report_boxer_b").input("Nestor Bravo")
    at.date_input(key="report_event_date").set_value(date(2026, 9, 19))
    at.text_input(key="report_event_name").input("Cruz vs Bravo")
    at.text_input(key="report_venue").input("Pechanga Arena")
    at.text_input(key="report_country").input("USA")
    at.selectbox(key="report_outcome").set_value("Boxer A wins")
    at.selectbox(key="report_method").set_value("KO")
    at.number_input(key="report_scheduled_rounds").set_value(12)
    at.number_input(key="report_round_stopped").set_value(6)
    at.text_input(key="report_stopping_time").input("2:36")
    at.text_input(key="report_weight_class").input("Super Lightweight")
    at.text_input(key="report_referee").input("Thomas Taylor")
    at.text_input(key="report_src_1_name").input("PBC bout page")
    at.text_input(key="report_src_1_url").input("https://www.premierboxingchampions.com/bouts/715374")
    at.selectbox(key="report_src_1_conf").set_value("Official")
    return at.run()


def test_report_mode_preview():
    at = fill_cruz_bravo(run_app("Build verified report"))
    assert not at.exception
    text = all_text(at)
    assert "Isaac Cruz vs Nestor Bravo" in text
    assert "Round 6, 2:36" in text
    assert "Confirmed" in text and "1 official source(s) recorded." in text
    assert "Winner: Isaac Cruz" in at.selectbox(key="report_outcome").options
    warnings = at.warning[-1].value
    assert "No knockdowns recorded" in warnings
    assert "Official result is Unknown" not in warnings


def test_report_survives_mode_switch():
    at = fill_cruz_bravo(run_app("Build verified report"))
    at.sidebar.radio[0].set_value("Free source discovery").run()
    at.sidebar.radio[0].set_value("Build verified report").run()
    assert not at.exception
    assert at.text_input(key="report_boxer_a").value == "Isaac Cruz"
    assert at.selectbox(key="report_method").value == "KO"
    assert at.number_input(key="report_round_stopped").value == 6
    assert at.selectbox(key="report_src_1_conf").value == "Official"


def test_clear_report():
    at = fill_cruz_bravo(run_app("Build verified report"))
    next(b for b in at.button if b.label == "Clear report").click().run()
    assert not at.exception
    assert at.text_input(key="report_boxer_a").value == ""
    assert at.selectbox(key="report_outcome").value == "Unknown"


def test_report_escapes_html():
    at = run_app("Build verified report")
    at.text_input(key="report_boxer_a").input("<script>alert(1)</script>")
    at.text_input(key="report_src_1_url").input("https://example.com/'><script>x</script>")
    at.run()
    html_blocks = [m.value for m in at.markdown if "<div" in m.value or "<a " in m.value]
    assert html_blocks and not any("<script>" in block for block in html_blocks)


# Build verified report: rules and exports --------------------------------------

def build(**overrides):
    fields = {"boxer_a": "Isaac Cruz", "boxer_b": "Nestor Bravo", "event_date": date(2026, 9, 19), "event_name": "Cruz vs Bravo",
              "venue": "Pechanga Arena", "country": "USA", "outcome": "Boxer A wins", "method": "KO", "round_stopped": 6,
              "stopping_time": "2:36", "scheduled_rounds": 12, "weight_class": "Super Lightweight", "titles": "WBC Interim",
              "scorecards": ["", "", ""], "referee": "Thomas Taylor", "judges": ["", "", ""]}
    knockdowns = overrides.pop("knockdowns", [{"knocked_down": "Nestor Bravo", "scored_by": "Isaac Cruz", "round": 1.0, "count": 8.0,
                                               "source_url": "https://example.com/rbr", "notes": ""}])
    evidence = overrides.pop("evidence", [{"name": "PBC", "url": "https://example.com/pbc", "confidence": "Official"}])
    fields.update(overrides)
    return rb.build_report(fields, knockdowns, evidence)


def test_complete_report_has_no_warnings():
    report = build()
    assert report["warnings"] == []
    assert report["result"]["winner"] == "Isaac Cruz"
    assert report["knockdowns"][0]["round"] == 1 and report["knockdowns"][0]["count"] == 8


@pytest.mark.parametrize("confidences, expected", [
    (["Official", "Unverified"], "Confirmed"),
    (["Corroborated", "Corroborated"], "Corroborated"),
    (["Corroborated", "Unverified"], "Single source"),
    (["Unverified"], "Unverified"),
    ([], "Unavailable"),
])
def test_overall_confidence(confidences, expected):
    evidence = [{"name": f"S{i}", "url": f"https://example.com/{i}", "confidence": c} for i, c in enumerate(confidences)]
    assert build(evidence=evidence)["overall_confidence"] == expected


def test_sources_without_valid_url_do_not_count():
    report = build(evidence=[{"name": "Tweet", "url": "", "confidence": "Official"}, {"name": "X", "url": "example.com", "confidence": "Official"}])
    assert report["overall_confidence"] == "Unavailable"
    assert any("has no URL" in w for w in report["warnings"])
    assert any("must start with http" in w for w in report["warnings"])


@pytest.mark.parametrize("overrides, expected", [
    ({"outcome": "Unknown"}, "Official result is Unknown"),
    ({"method": "Not recorded"}, "Method of result is missing."),
    ({"round_stopped": None}, "Round stopped is missing"),
    ({"stopping_time": ""}, "Stopping time is missing"),
    ({"stopping_time": "2.36"}, "m:ss"),
    ({"round_stopped": 13}, "exceeds the scheduled rounds"),
    ({"outcome": "Draw"}, "inconsistent with a draw"),
    ({"method": "Technical Draw"}, "inconsistent with a winner"),
    ({"method": "UD", "round_stopped": None, "stopping_time": ""}, "Only 0 of 3 judges' scorecards"),
    ({"method": "UD"}, "entered for a UD decision"),
    ({"boxer_b": "isaac  cruz"}, "same name"),
    ({"venue": "", "country": ""}, "Match identity incomplete: venue, country."),
    ({"referee": ""}, "Referee is missing."),
    ({"evidence": [{"name": "Report", "url": "https://example.com/a", "confidence": "Corroborated"}]}, "No official source"),
    ({"knockdowns": []}, "No knockdowns recorded"),
    ({"knockdowns": [{"knocked_down": "Someone Else", "round": 2, "source_url": "https://example.com"}]}, "does not match Boxer A or Boxer B"),
    ({"knockdowns": [{"knocked_down": "Nestor Bravo", "round": 9, "source_url": "https://example.com"}]}, "after the fight ended (round 6)"),
    ({"knockdowns": [{"knocked_down": "Nestor Bravo", "round": 2}]}, "Knockdown 1: no source URL."),
])
def test_missing_information_warnings(overrides, expected):
    assert any(expected in w for w in build(**overrides)["warnings"]), build(**overrides)["warnings"]


def test_blank_knockdown_rows_are_ignored():
    blank = {"knocked_down": None, "scored_by": float("nan"), "round": float("nan"), "count": float("nan"), "source_url": None, "notes": None}
    assert build(knockdowns=[blank] * 6)["knockdowns"] == []


def test_json_export():
    report = build()
    data = json.loads(rb.to_json(report))
    assert data["disclaimer"] == rb.DISCLAIMER
    assert data["match"]["event_date"] == "2026-09-19"
    assert data["settlement_status"].startswith("Not settled")


def test_csv_export_and_formula_injection():
    report = build(titles="=HYPERLINK(\"https://evil\")", knockdowns=[{"knocked_down": "Nestor Bravo", "round": 1, "notes": "@cmd", "source_url": "https://example.com"}])
    raw = rb.to_csv(report)
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["section", "item", "field", "value"]
    values = {(r[0], r[1], r[2]): r[3] for r in rows[1:]}
    assert values[("result", "", "titles")].startswith("'=")
    assert values[("knockdown", "1", "notes")] == "'@cmd"
    assert values[("report", "", "disclaimer")] == rb.DISCLAIMER


def test_file_stem():
    assert rb.file_stem(build()) == "isaac-cruz-vs-nestor-bravo-2026-09-19-report"
    assert rb.file_stem(build(boxer_a="", boxer_b="", event_date=None)) == "boxer-a-vs-boxer-b-undated-report"


def test_knockdown_ledger_escapes_html():
    import pandas as pd
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["report_kd_saved"] = pd.DataFrame([
        {"knocked_down": "<img src=x onerror=alert(1)>", "scored_by": "", "round": 2.0, "count": float("nan"), "source_url": "javascript:alert(1)", "notes": ""},
        *[{"knocked_down": "", "scored_by": "", "round": float("nan"), "count": float("nan"), "source_url": "", "notes": ""}] * 5,
    ])
    at.run()
    at.sidebar.radio[0].set_value("Build verified report").run()
    assert not at.exception
    ledger = next(m.value for m in at.markdown if "class='ledger'" in m.value)
    assert "<img" not in ledger and "&lt;img" in ledger
    assert "href='javascript" not in ledger
    assert ledger.count("<tr>") == 2  # header + one filled knockdown row
