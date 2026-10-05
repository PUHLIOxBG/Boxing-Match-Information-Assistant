"""Deterministic extraction of post-fight facts from public pages and feeds.

Rules are regular expressions and table parsing only — no LLM, no guessing.
A fact is produced only when a sentence (or record-table row) states it.
Knockdowns are recorded only from explicit knockdown wording with a round;
they are never inferred from a KO/TKO result.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup
from defusedxml import ElementTree

# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
}
ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
}
_ORD = r"(?:" + "|".join(ORDINAL_WORDS) + r"|opening|1[0-5]th|1st|2nd|3rd|[4-9]th)"
_NUM = r"(?:" + "|".join(NUMBER_WORDS) + r"|1[0-5]|[1-9])"
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
DECISIONS = {"UD", "SD", "MD", "TD"}

DIVISIONS = (
    ("light heavyweight", "Light Heavyweight"), ("super middleweight", "Super Middleweight"),
    ("super welterweight", "Super Welterweight"), ("junior middleweight", "Super Welterweight"), ("light middleweight", "Super Welterweight"),
    ("super lightweight", "Super Lightweight"), ("junior welterweight", "Super Lightweight"), ("light welterweight", "Super Lightweight"),
    ("super featherweight", "Super Featherweight"), ("junior lightweight", "Super Featherweight"),
    ("super bantamweight", "Super Bantamweight"), ("junior featherweight", "Super Bantamweight"),
    ("super flyweight", "Super Flyweight"), ("junior bantamweight", "Super Flyweight"),
    ("light flyweight", "Light Flyweight"), ("junior flyweight", "Light Flyweight"),
    ("mini flyweight", "Minimumweight"), ("minimumweight", "Minimumweight"), ("strawweight", "Minimumweight"),
    ("cruiserweight", "Cruiserweight"), ("bridgerweight", "Bridgerweight"), ("heavyweight", "Heavyweight"),
    ("middleweight", "Middleweight"), ("welterweight", "Welterweight"), ("lightweight", "Lightweight"),
    ("featherweight", "Featherweight"), ("bantamweight", "Bantamweight"), ("flyweight", "Flyweight"),
)
# "light-heavyweight" and "light heavyweight" are the same division.
_DIVISION_RE = re.compile(r"\b(" + "|".join(re.escape(d).replace(r"\ ", "[- ]") for d, _ in DIVISIONS) + r")\b", re.I)
_DIVISION_MAP = dict(DIVISIONS)

_ORG = r"(?:WBC|WBA|IBF|WBO|IBO|WBF|The Ring|Ring Magazine|British|Commonwealth|European|EBU|Lonsdale|NABF|NABO|USBA)"
_TITLE_ORGS = rf"({_ORG}(?:(?:\s*,\s*|\s+and\s+|\s*&\s*|\s*/\s*)(?:the\s+)?{_ORG})*)"
_TITLE_RE = re.compile(
    r"\b((?:(?:interim|vacant|unified|undisputed|regular|super|silver|gold|diamond|franchise|world|international|intercontinental)\s+)*)"
    + _TITLE_ORGS
    + r"((?:\s+(?:interim|silver|gold|international|intercontinental|regular|super|diamond|franchise|world|[a-z\-]+weight|light|junior|super|and|&|/|,))*)\s+"
      r"(?:[a-z\-]+weight\s+|light\s+[a-z]+weight\s+)?(title|titles|belt|belts|championship|crown|strap)\b"
)
_ORG_RE = re.compile(_ORG)
_TITLE_QUALIFIERS = ("interim", "silver", "international", "intercontinental", "regular", "diamond", "franchise", "gold")


def normalize(text: str) -> str:
    """Strip accents, unify quotes/dashes/spaces so rules can be simple."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    for old, new in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", " - "),
                     ("−", "-"), ("\xa0", " "), (" ", " "), ("​", "")):
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    return normalize(text).casefold()


def to_round(token: str) -> Optional[int]:
    token = token.lower()
    if token.isdigit():
        value = int(token)
    elif token in NUMBER_WORDS:
        value = NUMBER_WORDS[token]
    elif token in ORDINAL_WORDS:
        value = ORDINAL_WORDS[token]
    elif token == "opening":
        value = 1
    else:
        digits = re.match(r"(\d+)", token)
        value = int(digits.group(1)) if digits else 0
    return value if 1 <= value <= 15 else None


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\b(vs|Jr|Sr|Mr|St|No|Dr|def|Mt)\.", r"\1", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text) if s.strip()]


@dataclass(frozen=True)
class Boxer:
    full: str
    first: str
    surname: str

    @classmethod
    def from_name(cls, name: str) -> "Boxer":
        tokens = [t for t in normalize(name).replace('"', "").split() if t]
        while len(tokens) > 1 and tokens[-1].lower() in SUFFIXES:
            tokens.pop()
        if not tokens:
            return cls(name, "", "")
        return cls(" ".join(tokens), tokens[0] if len(tokens) > 1 else "", tokens[-1])

    def pattern(self, require_first: bool = False) -> str:
        surname = re.escape(self.surname)
        if not self.first:
            return rf"\b{surname}\b"
        first = re.escape(self.first)
        nickname = r"(?:\"[^\"]{1,25}\"\s+|'[^']{1,25}'\s+)?"
        if require_first:
            return rf"\b{first}\s+{nickname}(?:[A-Z][a-z]+\s+)?{surname}\b"
        return rf"(?:\b{first}\s+{nickname}(?:[A-Z][a-z]+\s+)?)?\b{surname}\b"


def boxer_patterns(a: Boxer, b: Boxer) -> tuple[str, str]:
    same = a.surname.casefold() == b.surname.casefold()
    return a.pattern(require_first=same), b.pattern(require_first=same)


# --------------------------------------------------------------------------- #
# Fact containers
# --------------------------------------------------------------------------- #

@dataclass
class Fact:
    field: str
    key: object  # normalised value used for agreement checks
    display: str
    quote: str


@dataclass
class KnockdownFact:
    victim: str  # "A" or "B"
    round: int
    count: int
    quote: str


@dataclass
class PageFacts:
    facts: list[Fact] = field(default_factory=list)
    knockdowns: list[KnockdownFact] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Article extraction
# --------------------------------------------------------------------------- #

# Future / conditional wording: the sentence is not reporting a completed result.
_FUTURE = re.compile(
    r"\b(will|would|could|should|might|must|if|plans?|wants?|hopes?|expects?|vows?|predicts?|aims?|targets?|eyes|set to|"
    r"bid to|attempt|preview|prediction|odds|next fight|next bout|needs?|needed|has to|have to|had to|trying to|looking to|going to)\b",
    re.I,
)
# Past fights and near-misses: they describe something other than this fight's result.
_PAST = re.compile(
    r"\b(rematch|nearly|almost|previous(?:ly)?(?! (?:unbeaten|undefeated|unknown))|last (?:year|time|month)|in (?:19|20)\d\d|(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|several|many) years? ago|"
    r"first (?:fight|meeting|bout)|who (?:has |had )?(?:beat|stopped|defeated|knocked|dropped|floored))\b",
    re.I,
)
# History / negation: blocks outcome claims.
_HISTORY = re.compile(_PAST.pattern[:-3] + r"|failed to|couldn't|could not|unable to|did not|didn't|never)\b", re.I)
# Fight records such as "(29-3-2, 19 KOs)" or "with 19 KOs" must not be read as results or scores.
_RECORD_RE = re.compile(r"\(\s*\d{1,3}-\d{1,3}(?:-\d{1,3})?(?:\s*,\s*\d{1,3}\s*(?:KOs?|knockouts))?\s*\)|\b\d{1,3} (?:KOs|knockouts|stoppages)\b", re.I)
_KD_HISTORY = re.compile(_PAST.pattern[:-3] + r"|never (?:been )?(?:down|dropped|floored))\b", re.I)
_BY_WIN = r"(?i:(?:by|after) (?:knocking out|stopping|beating|defeating|outpointing|halting))"
# Completed infinitives only ("survived a late scare to defeat"), never "needed X to beat".
_TO_WIN = r"(?i:(?:survived|rallied|recovered|held on|came back|fought back|battled back|went on)\b[^.;]{0,40}? to (?:defeat|beat|outpoint|stop|edge))"
_WIN_VERBS = (
    r"(?i:defeated|defeats|def|beat|beats|stopped|stops|knocked out|knocks out|outpointed|outpoints|outboxed|outboxes|"
    r"edged|edges|halted|halts|KO'd|TKO'd|KOs|TKOs|stunned|stuns|upset|upsets|dominated|dominates|overcame|"
    r"got past|got the better of|won (?:a |an |the )?(?:\w+ ){0,3}(?:decision|verdict|points win) (?:over|against)|won on points (?:over|against))"
)
# Between the verb and the loser: no clause break (comma, "but", "count", ...).
_OBJECT_GAP = r"(?:(?!\b(?:but|while|whereas|although|count|before|after|as|and|then)\b)[^.;,]){0,45}?"
_PASSIVE_LOSS = r"(?:was|got) (?:stopped|knocked out|beaten|defeated|outpointed|halted|upset) (?:\w+ ){0,4}?by"
_STOPPAGE_WORDS = re.compile(r"\b(stopp|stoppage|knock(?:ed)? ?out|KO|TKO|waved|wave-off|halted|counted out|ten count|retire|towel|called (?:it )?off|rescued|finish)", re.I)
_KD_WORDS = re.compile(r"\b(knocked (?:\w+ ){0,2}down|knocking (?:\w+ ){0,2}down|knockdowns?|dropped|dropping|floored|flooring|decked|decking|downed|hit the canvas|to the canvas|on the canvas|touched down|went down|was down|down (?:twice|once|three times))\b", re.I)
_KD_NOT = re.compile(r"\bdropped (?:a |an |the |his |her |their )?(?:\w+ )?(?:decision|out|hands?|guard|weight|points?|rounds?|belt|title|bout|fight|pounds|lbs)\b"
                     r"|\bno knockdowns?\b|\bwithout (?:a |any )?knockdowns?\b|\bknockdown power\b", re.I)
_SCORE_CONTEXT = re.compile(r"\b(scores?|scored|scorecards?|cards?|judges?|tall(?:y|ies)|read|verdict|decision|points)\b", re.I)
_SCORE_RE = re.compile(r"(?<![\d-])(\d{2,3})\s*-\s*(\d{2,3})(?![\d-])")
_NAME = r"[A-Z][a-zA-Z'\-]+(?: (?:[A-Z][a-zA-Z'\-]+|de|del|la|van|von|di|da|dos))*? [A-Z][a-zA-Z'\-]+"
_REFEREE_RE = re.compile(r"(?i:referee|ref)\s+(" + _NAME + r")\b")
_REFEREE_RE2 = re.compile(r"(" + _NAME + r") (?:was|served as) the (?:referee|third man)")
_JUDGES_RE = re.compile(r"(?i:judges?)\s+(" + _NAME + r")(?:,| and) (?:and )?(" + _NAME + r")(?:,? and (" + _NAME + r"))?")
_JUDGE_CARD_RE = re.compile(r"(" + _NAME + r") (?:scored it|had it|turned in|submitted|saw it|scored the (?:fight|bout|contest))\b")
# Only compound forms ("12-round", "ten-rounder") or explicit scheduling — never a bare "eight rounds".
_SCHEDULED_RE = re.compile(r"\b(four|six|eight|ten|twelve|fifteen|4|6|8|10|12|15)-round(?:er)?\b|\bscheduled (?:for )?(\d{1,2}|four|six|eight|ten|twelve) rounds\b"
                           r"|\b(?:decision|verdict|points) over (\d{1,2}|four|six|eight|ten|twelve) rounds\b", re.I)
_NOT_A_PERSON = re.compile(r"^The\b|\b(Guardian|Times|News|Sport|Sports|Boxing|ESPN|BBC|DAZN|Ring|Telegraph|Independent|Mirror|Post|Herald|Magazine|Journal|Network)\b")


# Sentences about other bouts on the same card.
_UNDERCARD = re.compile(r"\b(undercard|under-card|co-feature|co-main|chief support|on the card|on the bill|earlier (?:on the card|in the night|in the evening))\b", re.I)
_RESULT_CONTEXT = re.compile(
    r"\b(won|wins|beat|beats|defeated|defeats|stopped|stops|finished|ended|via|outpointed|retained|retains|captured|claimed|"
    r"victory|verdict|knocked out|knocks out|scored a|earned a|awarded|ruled|declared|waved off)\b", re.I)
_KO_DESCRIPTOR = re.compile(
    r"\b(?:knockout|KO)\s+(?:artist|power|puncher|threat|specialist|ratio|percentage|rate|record|wins|victories|streak|machine|king|"
    r"merchant|hitter|of the year)\b|\b\d+\s+(?:knockouts|KOs)\b|\bknockout-heavy\b", re.I)


def _method_in(sentence: str) -> Optional[str]:
    s = sentence
    if re.search(r"\btechnical draw\b", s, re.I):
        return "Technical draw"
    if re.search(r"\bunanimous(?:ly)? decision\b|\bUD\b", s):
        return "UD"
    if re.search(r"\bsplit decision\b", s, re.I) or re.search(r"\bSD\b", s):
        return "SD"
    if re.search(r"\bmajority decision\b", s, re.I) or re.search(r"\bMD\b", s):
        return "MD"
    if re.search(r"\btechnical decision\b|\bTD\b", s):
        return "TD"
    if re.search(r"\bdisqualif|\bDQ\b", s):
        return "DQ"
    if re.search(r"\bRTD\b|\bcorner retirement\b|\bretired (?:on|in) (?:his|her|the) (?:stool|corner)\b|\bretired after (?:the )?\w+ round\b|\bthrew in the towel\b", s, re.I):
        return "RTD"
    if re.search(r"\bTKO\b|\bTKO'd\b|\btechnical knockout\b", s, re.I):
        return "TKO"
    if re.search(r"\bKO\b|\bKO'd\b|\bKOs\b|\bknockout\b|\bknocked (?:\w+ )?out\b|\bknocking (?:\w+ )?out\b", s, re.I):
        return "KO"
    if re.search(r"\bon points\b|\bpoints (?:decision|win|victory)\b|\bPTS\b", s):
        return "PTS"
    return None


def _round_time(sentence: str) -> tuple[Optional[int], Optional[str]]:
    m = re.search(rf"\b(\d{{1,2}}:[0-5]\d) (?:of|into) (?:the )?(?:round )?({_ORD}|{_NUM})(?: round)?\b", sentence, re.I)
    if m:
        return to_round(m.group(2)), m.group(1)
    m = re.search(r"\(R(\d{1,2}),? (\d{1,2}:[0-5]\d)\)", sentence)
    if m:
        return to_round(m.group(1)), m.group(2)
    stop = _STOPPAGE_WORDS.search(sentence)
    if not stop:
        return None, None
    rounds = [(m.start(), to_round(m.group(1))) for m in re.finditer(rf"\b(?:in|during) (?:the )?({_ORD}) round\b", sentence, re.I)]
    rounds +=[(m.start(), to_round(m.group(1))) for m in re.finditer(rf"\b({_ORD})-round\b", sentence, re.I)]
    rounds += [(m.start(), to_round(m.group(1))) for m in re.finditer(rf"\b(?:in )?round ({_NUM})\b", sentence, re.I)]
    rounds += [(m.start(), to_round(m.group(1))) for m in re.finditer(r"\bR(\d{1,2})\b", sentence)]
    rounds = [r for r in rounds if r[1]]
    round_no = min(rounds, key=lambda r: abs(r[0] - stop.start()))[1] if rounds else None
    t = re.search(r"\b(?:at|after) (\d{1,2}:[0-5]\d)\b", sentence)
    return round_no, (t.group(1) if t else None)


def _scorecards(sentence: str, scheduled: Optional[int]) -> list[tuple[int, int]]:
    cards = []
    for m in _SCORE_RE.finditer(sentence):
        hi, lo = sorted((int(m.group(1)), int(m.group(2))), reverse=True)
        total = hi + lo
        plausible = [r for r in ((scheduled,) if scheduled else (4, 6, 8, 10, 12)) if r and 17 * r <= total <= 20 * r and hi <= 10 * r]
        if plausible:
            cards.append((hi, lo))
    return cards


def _titles(sentence: str) -> set[str]:
    found = set()
    for m in _TITLE_RE.finditer(sentence):
        words = (m.group(1) + " " + m.group(3)).lower()
        qualifiers = [q for q in _TITLE_QUALIFIERS if re.search(rf"\b{q}\b", words)]
        for org in _ORG_RE.findall(m.group(2)):  # "British and Commonwealth titles" -> two titles
            found.add(" ".join([org.replace("Ring Magazine", "The Ring"), *qualifiers]))
    return found


def _division(name: str) -> str:
    return _DIVISION_MAP[name.lower().replace("-", " ")]


def _clean_name(name: str, banned: tuple[str, ...]) -> Optional[str]:
    name = re.sub(r"'s?$", "", name.strip())  # "Reece Carter's count" -> "Reece Carter"
    if len(name.split()) < 2 or _NOT_A_PERSON.search(name) or any(b.casefold() in name.casefold() for b in banned):
        return None
    return name


def extract_from_text(text: str, a: Boxer, b: Boxer) -> PageFacts:
    """Apply sentence rules to normalised body text."""
    out = PageFacts()
    pa, pb = boxer_patterns(a, b)
    sentences = split_sentences(_RECORD_RE.sub("", normalize(text)))
    has_a = [bool(re.search(pa, s)) for s in sentences]
    has_b = [bool(re.search(pb, s)) for s in sentences]
    banned = tuple(x for x in (a.surname, b.surname) if x)

    winners: list[tuple[str, str]] = []
    methods: dict[str, list[str]] = {}
    rounds: list[tuple[int, Optional[str], str]] = []
    scheduled: dict[int, list[str]] = {}
    divisions: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    cards: list[tuple[list[tuple[int, int]], str]] = []
    referees: dict[str, str] = {}
    judges: dict[str, str] = {}
    kds: dict[tuple[str, int], tuple[int, str]] = {}

    for i, s in enumerate(sentences):
        about = has_a[i] or has_b[i]
        near = about or (i > 0 and (has_a[i - 1] or has_b[i - 1]))
        both = has_a[i] and has_b[i]
        future = bool(_FUTURE.search(s))
        skip = future or bool(_HISTORY.search(s))

        # Winner / draw / no contest — both boxers must be named in the sentence.
        if both and not skip:
            for winner, (x, y) in (("A", (pa, pb)), ("B", (pb, pa))):
                # Active voice: no passive auxiliary before the verb, no infinitive ("needed X to beat"),
                # no "by" after it, and no clause break between the verb and the loser.
                active = (rf"{x}(?:(?!\b(?:was|were|got|been|is)\b)[^.;]){{0,90}}?(?<!\bto )\b(?:{_WIN_VERBS}|{_BY_WIN})\b(?! by\b){_OBJECT_GAP}{y}"
                          rf"|{x}[^.;]{{0,30}}?\b{_TO_WIN}\b{_OBJECT_GAP}{y}")
                if re.search(active, s) or re.search(rf"{y}[^.;]{{0,40}}?\b{_PASSIVE_LOSS}\b[^.;]{{0,30}}?{x}", s):
                    winners.append((winner, s))
            if re.search(r"\b(?:fought to|ended in|ended with|declared|ruled|scored|settled for|was) (?:a |an )?(?:split |majority |unanimous |technical )?draw\b|\b(?:split|majority|unanimous|technical) draw\b", s, re.I):
                winners.append(("Draw", s))
            if re.search(r"\b(?:ruled|declared|ended in|ended as|was|changed to|overturned to) (?:a )?no[- ]contest\b", s, re.I):
                winners.append(("No contest", s))

        # Method, round and card details tolerate history words elsewhere in a long sentence,
        # but never future/conditional wording or near-miss phrasing.
        past = bool(_PAST.search(s))
        # A method only counts in a sentence that reports a result ("won by", "stopped", "via UD"),
        # never in a description such as "knockout artist" or "knockout power".
        if about and not future and not past and (both or _RESULT_CONTEXT.search(s)):
            method = _method_in(_KO_DESCRIPTOR.sub(" ", s))
            if method:
                methods.setdefault(method, []).append(s)

        if near and not future and not past:
            r, t = _round_time(s)
            if r and not (_KD_WORDS.search(s) and not _STOPPAGE_WORDS.search(s)):
                rounds.append((r, t, s))
            for m in _SCHEDULED_RE.finditer(s):
                value = to_round(m.group(1) or m.group(2) or m.group(3) or "")
                if value:
                    scheduled.setdefault(value, []).append(s)

        # Same-sentence rule: weight class, titles, scorecards, officials and knockdowns are taken
        # only from a sentence that itself names one of the two boxers — never from a neighbouring
        # sentence, and never from a sentence about the undercard.
        own = about and not _UNDERCARD.search(s)
        if own and not future and not past:
            for m in _DIVISION_RE.finditer(s):
                divisions.setdefault(_division(m.group(1)), []).append(s)
            for title in _titles(s):
                titles.setdefault(title, s)

        if own and _SCORE_CONTEXT.search(s):
            found = _scorecards(s, None)
            if found:
                cards.append((found, s))

        if own:
            for m in list(_REFEREE_RE.finditer(s)) + list(_REFEREE_RE2.finditer(s)):
                name = _clean_name(m.group(1), banned)
                if name:
                    referees.setdefault(name, s)
            for m in _JUDGES_RE.finditer(s):
                for g in m.groups():
                    name = _clean_name(g, banned) if g else None
                    if name:
                        judges.setdefault(name, s)
            for m in _JUDGE_CARD_RE.finditer(s):
                name = _clean_name(m.group(1), banned)
                if name and _SCORE_RE.search(s[m.end():m.end() + 20]):
                    judges.setdefault(name, s)

        # Knockdowns: explicit wording, a named fighter in this sentence and a stated round.
        if own and _KD_WORDS.search(s) and not _KD_NOT.search(s) and not future and not _KD_HISTORY.search(s):
            victim = None
            for v, (x, y) in (("B", (pa, pb)), ("A", (pb, pa))):
                if re.search(rf"{x}[^.;]{{0,40}}?\b(?:dropped|floored|decked|downed|knocked|sent|put)\b[^.;]{{0,15}}?{y}", s) \
                        or (both and re.search(rf"\b(?i:after|by|with|following) (?:dropping|flooring|decking|knocking down) {y}", s)) \
                        or re.search(rf"{x}[^.;]{{0,40}}?\b(?:scored|registered|earned|recorded|produced|landed)\b[^.;]{{0,20}}?\bknockdowns?\b", s) \
                        or re.search(rf"{y}[^.;]{{0,30}}?\b(?:was|were|got|had been|went|hit|touched) (?:also |then |briefly )?(?:dropped|floored|decked|down|knocked down|the canvas)\b", s):
                    victim = v
                    break
            round_match = re.search(rf"\b(?:in|during) (?:the )?({_ORD}) round\b|\bin round ({_NUM})\b|\b({_ORD})-round knockdown\b|\bround ({_NUM})\b", s, re.I)
            if victim and round_match:
                round_no = to_round(next(g for g in round_match.groups() if g))
                if round_no:
                    count = 3 if re.search(r"\bthree times\b", s, re.I) else 2 if re.search(r"\btwice\b|\btwo knockdowns\b", s, re.I) else 1
                    kds[(victim, round_no)] = (max(count, kds.get((victim, round_no), (0, ""))[0]), s)

    # Collapse per-page evidence into single facts (ambiguous pages contribute nothing).
    winner_keys = {w for w, _ in winners}
    if len(winner_keys) == 1:
        key = winner_keys.pop()
        out.facts.append(Fact("winner", key, {"A": a.full, "B": b.full}.get(key, key), winners[0][1]))
    elif len(winner_keys) > 1:
        out.notes.append("Page names more than one outcome for this pairing; outcome ignored.")
    best = None
    if methods:
        # "on points" is generic: prefer a specific decision type stated on the same page.
        specific = {m: v for m, v in methods.items() if m != "PTS"} if any(m in DECISIONS for m in methods) else methods
        best = max(specific, key=lambda m: (len(specific[m]), m in {"TKO", "RTD", "DQ", "UD", "SD", "MD"}))
        out.facts.append(Fact("method", best, best, specific[best][0]))
    if rounds and best not in DECISIONS | {"PTS"}:  # a decision has no stoppage round
        r, t, s = rounds[0]
        out.facts.append(Fact("round", r, str(r), s))
        timed = next((x for x in rounds if x[1]), None)
        if timed:
            out.facts.append(Fact("time", timed[1], timed[1], timed[2]))
    if scheduled:
        value = max(scheduled, key=lambda v: len(scheduled[v]))
        out.facts.append(Fact("scheduled_rounds", value, str(value), scheduled[value][0]))
    if divisions:
        value = max(divisions, key=lambda v: len(divisions[v]))
        out.facts.append(Fact("weight_class", value, value, divisions[value][0]))
    for title, s in titles.items():
        out.facts.append(Fact("titles", title, title, s))
    if cards:
        best_cards, s = max(cards, key=lambda c: len(c[0]))
        best_cards = sorted(best_cards, reverse=True)[:3]
        out.facts.append(Fact("scorecards", tuple(best_cards), ", ".join(f"{h}-{l}" for h, l in best_cards), s))
    for name, s in referees.items():
        out.facts.append(Fact("referee", name.casefold(), name, s))
        break
    for name, s in judges.items():
        out.facts.append(Fact("judges", name.casefold(), name, s))
    for (victim, round_no), (count, s) in sorted(kds.items(), key=lambda kv: kv[0][1]):
        out.knockdowns.append(KnockdownFact(victim, round_no, count, s))
    return out


def article_text(html: bytes) -> tuple[str, str, Optional[date]]:
    """(title, body text, published date) from an article page."""
    soup = BeautifulSoup(html, "html.parser")
    title = normalize(soup.title.get_text()) if soup.title else ""
    published = None
    for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"}, {"itemprop": "datePublished"},
                  {"name": "date"}, {"property": "og:published_time"}, {"name": "pubdate"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            published = parse_date(tag["content"])
            if published:
                break
    if not published:
        tag = soup.find("time", attrs={"datetime": True})
        published = parse_date(tag["datetime"]) if tag else None
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "figure", "iframe", "svg"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = [normalize(el.get_text(" ")) for el in root.find_all(["p", "li", "h2", "h3", "td"])]
    blocks = [b for b in blocks if len(b) > 2]
    text = " ".join(b if b.endswith((".", "!", "?")) else b + "." for b in blocks[:400])
    return title, text, published


def parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%B %d %Y", "%d %B, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Feeds
# --------------------------------------------------------------------------- #

@dataclass
class FeedItem:
    title: str
    link: str
    summary: str
    published: Optional[date]


def parse_feed(content: bytes) -> list[FeedItem]:
    """RSS 2.0 or Atom. defusedxml rejects entity-expansion attacks."""
    try:
        root = ElementTree.fromstring(content)
    except Exception:  # noqa: BLE001 - malformed or hostile XML: treat as no items
        return []
    items = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        values: dict[str, str] = {}
        link = ""
        for child in node:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "link":
                link = link or (child.get("href") or (child.text or "")).strip()
            elif ctag in ("title", "description", "summary", "pubDate", "published", "updated") and ctag not in values:
                values[ctag] = (child.text or "").strip()
        summary = BeautifulSoup(values.get("description") or values.get("summary") or "", "html.parser").get_text(" ")
        items.append(FeedItem(normalize(BeautifulSoup(values.get("title", ""), "html.parser").get_text()), link, normalize(summary),
                              parse_date(values.get("pubDate") or values.get("published") or values.get("updated") or "")))
    return items


def mentions_both(text: str, a: Boxer, b: Boxer) -> bool:
    pa, pb = boxer_patterns(a, b)
    text = normalize(text)
    return bool(re.search(pa, text, re.I)) and bool(re.search(pb, text, re.I))


# --------------------------------------------------------------------------- #
# Wikipedia professional boxing record
# --------------------------------------------------------------------------- #

@dataclass
class RecordRow:
    facts: list[Fact]
    cited_urls: list[str]


_RESULT_MAP = {"win": "subject", "loss": "opponent", "draw": "Draw", "nc": "No contest", "no contest": "No contest"}
_TYPE_MAP = {"ko": "KO", "tko": "TKO", "rtd": "RTD", "ud": "UD", "sd": "SD", "md": "MD", "dq": "DQ", "td": "TD", "pts": "PTS", "nc": "NC"}


def wikipedia_record(html: bytes, subject: Boxer, opponent: Boxer, subject_key: str, event_date: date) -> tuple[Optional[RecordRow], list[str], str]:
    """Find the record-table row for this fight. Returns (row, cited URLs from prose, page title)."""
    soup = BeautifulSoup(html, "html.parser")
    page_title = normalize(soup.title.get_text()) if soup.title else ""
    references = _reference_urls(soup)
    prose_urls = []
    for p in soup.find_all("p"):
        text = normalize(p.get_text(" "))
        if re.search(rf"\b{re.escape(opponent.surname)}\b", text) and str(event_date.year) in text:
            for sup in p.find_all("sup", class_="reference"):
                anchor = sup.find("a", href=True)
                if anchor and anchor["href"].startswith("#"):
                    prose_urls.extend(references.get(anchor["href"][1:], []))

    # The first table under the heading is usually the win/loss summary; use the one listing opponents.
    anchor = soup.find(id="Professional_boxing_record")
    rows, headers = [], []
    for table in (anchor.find_all_next("table", class_="wikitable", limit=3) if anchor else []):
        table_rows = table.find_all("tr")
        table_headers = [fold(c.get_text(" ")) for c in table_rows[0].find_all(["th", "td"])] if table_rows else []
        if any(h.startswith("opponent") for h in table_headers):
            rows, headers = table_rows, table_headers
            break
    if not rows:
        return None, prose_urls, page_title

    def col(*names: str) -> Optional[int]:
        for i, h in enumerate(headers):
            if any(h.startswith(n) for n in names):
                return i
        return None

    i_result, i_opp, i_type, i_round, i_time, i_date, i_notes = (col("result"), col("opponent"), col("type"), col("round"),
                                                                 col("time"), col("date"), col("notes"))
    if None in (i_result, i_opp, i_date):
        return None, prose_urls, page_title
    opp_re = re.compile(opponent.pattern(), re.I)
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) != len(headers):
            continue
        texts = [normalize(c.get_text(" ")) for c in cells]
        row_date = parse_date(re.sub(r"\[\d+\]", "", texts[i_date]))
        if not row_date or abs((row_date - event_date).days) > 2 or not opp_re.search(texts[i_opp]):
            continue
        quote = " | ".join(f"{headers[i].title()}: {texts[i]}" for i in range(len(texts)) if texts[i])
        facts = []
        result = _RESULT_MAP.get(texts[i_result].lower().strip())
        if result:
            winner = subject_key if result == "subject" else ("B" if subject_key == "A" else "A") if result == "opponent" else result
            display = {"A": subject.full if subject_key == "A" else opponent.full, "B": subject.full if subject_key == "B" else opponent.full}.get(winner, winner)
            facts.append(Fact("winner", winner, display, quote))
        if i_type is not None:
            method = _TYPE_MAP.get(re.sub(r"[^a-z]", "", texts[i_type].lower()))
            if method and method != "NC":
                facts.append(Fact("method", method, method, quote))
        round_text = texts[i_round] if i_round is not None else ""
        m = re.match(r"\s*(\d{1,2})\s*(?:\((\d{1,2})\))?\s*(?:,\s*(\d{1,2}:\d{2}))?", round_text)
        decision = any(f.field == "method" and f.key in {"UD", "SD", "MD", "PTS"} for f in facts)
        if m:
            ended, scheduled_rounds, time_value = int(m.group(1)), m.group(2), m.group(3)
            if scheduled_rounds:
                facts.append(Fact("scheduled_rounds", int(scheduled_rounds), scheduled_rounds, quote))
            elif decision:
                facts.append(Fact("scheduled_rounds", ended, str(ended), quote))
            if not decision:
                facts.append(Fact("round", ended, str(ended), quote))
            if not time_value and i_time is not None:
                separate = re.match(r"\s*(\d{1,2}:\d{2})", texts[i_time])
                time_value = separate.group(1) if separate else None
            if time_value and not decision:
                facts.append(Fact("time", time_value, time_value, quote))
        notes = texts[i_notes] if i_notes is not None else ""
        for title in _titles(notes):
            facts.append(Fact("titles", title, title, quote))
        division = _DIVISION_RE.search(notes)
        if division:
            value = _division(division.group(1))
            facts.append(Fact("weight_class", value, value, quote))
        cited = []
        for sup in tr.find_all("sup", class_="reference"):
            a_tag = sup.find("a", href=True)
            if a_tag and a_tag["href"].startswith("#"):
                cited.extend(references.get(a_tag["href"][1:], []))
        return RecordRow(facts, cited), prose_urls, page_title
    return None, prose_urls, page_title


def _reference_urls(soup: BeautifulSoup) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for li in soup.select("li[id^=cite_note]"):
        refs[li["id"]] = [a["href"] for a in li.select("a.external[href]") if a["href"].startswith("http") and "archive.org" not in a["href"]]
    return refs


def is_boxer_article(html: bytes, boxer: Boxer) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    if soup.find(id="disambigbox"):
        return False
    title = fold(soup.title.get_text()) if soup.title else ""
    return boxer.surname.casefold() in title and soup.find(id="Professional_boxing_record") is not None


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
