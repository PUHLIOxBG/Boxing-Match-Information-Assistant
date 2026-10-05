"""Manual post-fight report: validation, confidence and export.

Pure functions only. Nothing here fetches, scrapes or stores data, and nothing
settles a market: the report supports the trader's own manual review.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

DISCLAIMER = (
    "This report supports manual review only. Do not settle a market solely from a search snippet, "
    "AI overview, video title, or an unverified social-media post."
)

OUTCOMES = ("Boxer A wins", "Boxer B wins", "Draw", "No contest", "Unknown")
METHOD_NOT_RECORDED = "Not recorded"
METHODS = (METHOD_NOT_RECORDED, "KO", "TKO", "RTD", "UD", "SD", "MD", "DQ", "Technical Draw", "Other")
STOPPAGE_METHODS = {"KO", "TKO", "RTD", "DQ", "Technical Draw"}
DECISION_METHODS = {"UD", "SD", "MD"}
SOURCE_CONFIDENCE = ("Official", "Corroborated", "Unverified")
MAX_KNOCKDOWNS = 6
MAX_SOURCES = 5
KNOCKDOWN_FIELDS = ("knocked_down", "scored_by", "round", "count", "source_url", "notes")

_TIME_RE = re.compile(r"^\d{1,2}:[0-5]\d$")


def clean(value: Any) -> str:
    """Normalise a form or table value to a stripped string ('' for empty/NaN)."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def as_int(value: Any) -> Optional[int]:
    text = clean(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://")) and len(value) > len("https://")


def _same_name(a: str, b: str) -> bool:
    return bool(a) and " ".join(a.casefold().split()) == " ".join(b.casefold().split())


def winner_name(outcome: str, boxer_a: str, boxer_b: str) -> str:
    if outcome == "Boxer A wins":
        return boxer_a or "Boxer A"
    if outcome == "Boxer B wins":
        return boxer_b or "Boxer B"
    return ""


def overall_confidence(evidence: list[dict]) -> tuple[str, str]:
    """Return (badge status, explanation) from the sources that have a valid URL."""
    usable = [e for e in evidence if is_url(e["url"])]
    official = sum(e["confidence"] == "Official" for e in usable)
    corroborated = sum(e["confidence"] == "Corroborated" for e in usable)
    if official:
        return "Confirmed", f"{official} official source(s) recorded."
    if corroborated >= 2:
        return "Corroborated", f"{corroborated} corroborating sources, but no official source."
    if corroborated == 1:
        return "Single source", "Only one corroborating source and no official source."
    if usable:
        return "Unverified", "Only unverified sources recorded."
    return "Unavailable", "No evidence source with a valid URL has been recorded."


def build_report(fields: dict, knockdowns: list[dict], evidence: list[dict]) -> dict:
    """Assemble the report and its missing-information warnings."""
    a, b = clean(fields.get("boxer_a")), clean(fields.get("boxer_b"))
    outcome = fields.get("outcome") or "Unknown"
    method = fields.get("method") or METHOD_NOT_RECORDED
    event_date = fields.get("event_date")

    kd_rows = []
    for row in knockdowns[:MAX_KNOCKDOWNS]:
        entry = {
            "knocked_down": clean(row.get("knocked_down")),
            "scored_by": clean(row.get("scored_by")),
            "round": as_int(row.get("round")),
            "count": as_int(row.get("count")),
            "source_url": clean(row.get("source_url")),
            "notes": clean(row.get("notes")),
        }
        if any(v not in ("", None) for v in entry.values()):
            kd_rows.append(entry)

    sources = []
    for row in evidence[:MAX_SOURCES]:
        entry = {"name": clean(row.get("name")), "url": clean(row.get("url")), "confidence": row.get("confidence") or "Unverified"}
        if entry["name"] or entry["url"]:
            sources.append(entry)

    judges = [clean(j) for j in fields.get("judges", [])]
    scorecards = [clean(s) for s in fields.get("scorecards", [])]
    level, explanation = overall_confidence(sources)

    report = {
        "report_type": "Manual post-fight report",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disclaimer": DISCLAIMER,
        "settlement_status": "Not settled — for the trader's manual review only",
        "match": {
            "boxer_a": a,
            "boxer_b": b,
            "event_date": event_date.isoformat() if isinstance(event_date, date) else "",
            "event_name": clean(fields.get("event_name")),
            "venue": clean(fields.get("venue")),
            "country": clean(fields.get("country")),
        },
        "result": {
            "outcome": outcome,
            "winner": winner_name(outcome, a, b),
            "method": method if method != METHOD_NOT_RECORDED else "",
            "method_detail": clean(fields.get("method_other")) if method == "Other" else "",
            "round_stopped": as_int(fields.get("round_stopped")),
            "stopping_time": clean(fields.get("stopping_time")),
            "scheduled_rounds": as_int(fields.get("scheduled_rounds")),
            "weight_class": clean(fields.get("weight_class")),
            "titles": clean(fields.get("titles")),
        },
        "scorecards": [{"judge": judges[i] if i < len(judges) else "", "scorecard": card} for i, card in enumerate(scorecards)],
        "knockdowns": kd_rows,
        "officials": {"referee": clean(fields.get("referee")), "judges": judges},
        "evidence": sources,
        "overall_confidence": level,
        "confidence_explanation": explanation,
    }
    report["warnings"] = missing_information(report)
    return report


def missing_information(report: dict) -> list[str]:
    match, result, officials = report["match"], report["result"], report["officials"]
    a, b = match["boxer_a"], match["boxer_b"]
    outcome, method = result["outcome"], result["method"]
    scheduled, round_stopped, stop_time = result["scheduled_rounds"], result["round_stopped"], result["stopping_time"]
    warnings: list[str] = []

    # Match identity
    if not a or not b:
        warnings.append("Both boxer names are required.")
    elif _same_name(a, b):
        warnings.append("Boxer A and Boxer B have the same name.")
    if not match["event_date"]:
        warnings.append("Event date is missing.")
    missing_identity = [label for key, label in (("event_name", "event name"), ("venue", "venue"), ("country", "country")) if not match[key]]
    if missing_identity:
        warnings.append("Match identity incomplete: " + ", ".join(missing_identity) + ".")

    # Official result
    if outcome == "Unknown":
        warnings.append("Official result is Unknown — the report cannot support settlement yet.")
    elif outcome != "No contest" and not method:
        warnings.append("Method of result is missing.")
    if method == "Other" and not result["method_detail"]:
        warnings.append("Method is 'Other' but no description was entered.")
    if outcome == "Draw" and method in {"KO", "TKO", "RTD", "DQ"}:
        warnings.append(f"Method {method} is inconsistent with a draw.")
    if outcome in {"Boxer A wins", "Boxer B wins"} and method == "Technical Draw":
        warnings.append("Method Technical Draw is inconsistent with a winner.")
    if method in STOPPAGE_METHODS:
        if round_stopped is None:
            warnings.append(f"Round stopped is missing for a {method} result.")
        if not stop_time and method != "RTD":
            warnings.append(f"Stopping time is missing for a {method} result.")
    if method in DECISION_METHODS and (round_stopped is not None or stop_time):
        warnings.append(f"Round stopped / stopping time entered for a {method} decision — check the method.")
    if stop_time and not _TIME_RE.match(stop_time):
        warnings.append("Stopping time should use the m:ss format, e.g. 2:31.")
    if scheduled is None:
        warnings.append("Scheduled rounds are missing.")
    elif round_stopped is not None and round_stopped > scheduled:
        warnings.append(f"Round stopped ({round_stopped}) exceeds the scheduled rounds ({scheduled}).")
    if not result["weight_class"]:
        warnings.append("Weight class is missing.")

    # Scorecards
    filled_cards = sum(bool(s["scorecard"]) for s in report["scorecards"])
    if (method in DECISION_METHODS or (outcome == "Draw" and method not in STOPPAGE_METHODS)) and filled_cards < 3:
        warnings.append(f"Only {filled_cards} of 3 judges' scorecards entered for a decision.")

    # Knockdowns
    if not report["knockdowns"]:
        warnings.append("No knockdowns recorded. Confirm from an official or round-by-round source that none occurred before settling knockdown markets.")
    last_round = round_stopped if method in STOPPAGE_METHODS and round_stopped is not None else scheduled
    names = {n for n in (a, b) if n}
    for index, kd in enumerate(report["knockdowns"], start=1):
        label = f"Knockdown {index}"
        if not kd["knocked_down"]:
            warnings.append(f"{label}: fighter knocked down is missing.")
        elif len(names) == 2 and not any(_same_name(kd["knocked_down"], n) for n in names):
            warnings.append(f"{label}: '{kd['knocked_down']}' does not match Boxer A or Boxer B.")
        if kd["scored_by"] and _same_name(kd["scored_by"], kd["knocked_down"]):
            warnings.append(f"{label}: the same fighter is recorded as knocked down and scoring the knockdown.")
        if kd["round"] is None:
            warnings.append(f"{label}: round is missing.")
        elif last_round is not None and kd["round"] > last_round:
            warnings.append(f"{label}: round {kd['round']} is after the fight ended (round {last_round}).")
        if not kd["source_url"]:
            warnings.append(f"{label}: no source URL.")
        elif not is_url(kd["source_url"]):
            warnings.append(f"{label}: source URL must start with http:// or https://.")

    # Officials
    if not officials["referee"]:
        warnings.append("Referee is missing.")
    if method in DECISION_METHODS and sum(bool(j) for j in officials["judges"]) < 3:
        warnings.append("Not all three judges are named for a decision.")

    # Evidence
    usable = [s for s in report["evidence"] if is_url(s["url"])]
    for index, source in enumerate(report["evidence"], start=1):
        if not source["url"]:
            warnings.append(f"Source {index} ('{source['name']}') has no URL and is ignored.")
        elif not is_url(source["url"]):
            warnings.append(f"Source {index}: URL must start with http:// or https:// — ignored.")
    urls = [s["url"].rstrip("/").casefold() for s in usable]
    if len(urls) != len(set(urls)):
        warnings.append("The same source URL is listed more than once.")
    if not usable:
        warnings.append("No evidence source has been recorded.")
    elif not any(s["confidence"] == "Official" for s in usable):
        warnings.append("No official source (commission, sanctioning body or promoter result) has been recorded.")
    return warnings


def file_stem(report: dict) -> str:
    match = report["match"]
    parts = [match["boxer_a"] or "boxer-a", "vs", match["boxer_b"] or "boxer-b", match["event_date"] or "undated"]
    slug = re.sub(r"[^a-z0-9]+", "-", "-".join(parts).casefold()).strip("-")
    return f"{slug or 'match'}-report"


def to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def _cell(value: Any) -> str:
    """Stringify for CSV and neutralise spreadsheet formula injection."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(report: dict) -> bytes:
    """Long-format CSV (section, item, field, value) that opens cleanly in spreadsheets."""
    rows: list[tuple[str, Any, str, Any]] = []
    for field in ("report_type", "generated_at_utc", "disclaimer", "settlement_status", "overall_confidence", "confidence_explanation"):
        rows.append(("report", "", field, report[field]))
    for section in ("match", "result"):
        rows.extend((section, "", field, value) for field, value in report[section].items())
    for index, card in enumerate(report["scorecards"], start=1):
        rows.extend(("scorecard", index, field, value) for field, value in card.items())
    for index, kd in enumerate(report["knockdowns"], start=1):
        rows.extend(("knockdown", index, field, kd[field]) for field in KNOCKDOWN_FIELDS)
    rows.append(("officials", "", "referee", report["officials"]["referee"]))
    rows.extend(("officials", index, "judge", judge) for index, judge in enumerate(report["officials"]["judges"], start=1))
    for index, source in enumerate(report["evidence"], start=1):
        rows.extend(("evidence", index, field, value) for field, value in source.items())
    rows.extend(("warning", index, "message", message) for index, message in enumerate(report["warnings"], start=1))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("section", "item", "field", "value"))
    writer.writerows(tuple(_cell(v) for v in row) for row in rows)
    # BOM so Excel detects UTF-8 (en dashes in scorecards, accented names).
    return buffer.getvalue().encode("utf-8-sig")
