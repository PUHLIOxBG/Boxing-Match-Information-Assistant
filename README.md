# Boxing Match Information Assistant

Cloud-ready Streamlit prototype for post-match professional boxing research. It is deliberately evidence-first: **no mode settles a market**. The trader settles manually, using the facts and source links the app provides.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Modes

### Demo search
The 13 supplied matches, with a full Match Report for each. No network access.

### Free source discovery
Enter both boxers, the event/offered date and an optional event name. The app builds search links (DuckDuckGo, Google, BoxRec and Tapology lookups, official/promoter reports, round-by-round/knockdown evidence) that open in a new browser tab. Every link is labelled *Unverified manual source link*. This mode makes no network requests itself.

### Automatic match report
Enter both boxers, the event/offered date and an optional event name, then select **Find match report**. The app searches free public sources, reads a small number of pages and shows **only facts it actually finds**, each with a link to its source. Anything it cannot find is shown as **Not found**. The manual source links are shown underneath as a fallback.

**How retrieval works** — no API key, account, card, database or LLM:

1. **Wikipedia boxer articles** (`/wiki/` pages, permitted by robots.txt): the row for this fight in the *Professional boxing record* table, plus the citation links attached to it.
2. **Site-search RSS feeds** (`?s=…&feed=rss2`) published by the WBC, WBA, WBO, IBF, Most Valuable Promotions and Boxing News 24.
3. **Recent-news RSS feeds** from BBC Sport, ESPN, The Guardian, Sky Sports, Bad Left Hook and Boxing News, used only when the fight was in the last 3 weeks.
4. Up to 8 matching articles (at most 2 per publisher) are read. Facts are extracted from the **article body** with deterministic rules. Feed titles and snippets are only used to find articles, never as evidence.

**Politeness and safety** (`web_fetch.py`): domain allowlist (`sources.py`); robots.txt checked for every host (401/403/5xx/unreachable → host skipped); identifying User-Agent; at least 1.5 s between requests to the same host (or the robots.txt crawl-delay, up to 10 s); 5 s connect / 12 s read timeouts; 3 MB size cap; at most 60 requests and 60 s per lookup; redirects re-checked hop by hop; results cached for 30 minutes. Search engines, social networks and login-gated or bot-protected sites (Google, Facebook, Instagram, X, BoxRec, Tapology, BoxingScene) are never fetched.

**Extraction rules** (`extraction.py`): regular expressions and table parsing only. Sentences with future/conditional wording, historical references ("in 2019", "years ago", "previously beat", "who stopped") or near-misses ("nearly knocked out") are ignored. Fight records like "(29-3-2, 19 KOs)" are removed before matching. **Weight class, titles, scorecards, referee, judges and knockdowns are taken only from a sentence that itself names one of the two boxers**, and never from a sentence about the undercard, so details of other bouts on the card cannot leak into the report. A method is only read from a sentence reporting a result ("knockout artist" is not a method). A **knockdown is recorded only when a sentence explicitly describes one, names the fighter and states the round** — a KO/TKO result is never counted as a knockdown.

**Status levels** (`auto_report.py`), per fact:

| Status | Meaning |
|---|---|
| Confirmed | Stated by an official source (sanctioning body, commission or promoter) |
| Corroborated | Two or more independent publishers agree (two articles from the same publisher count once) |
| Single source | Only one publisher states it |
| Conflicting | Sources disagree — all values and their sources are listed under *Source conflicts* |
| Not found | No source read by the app stated it |

The **overall confidence** is the weaker of the result and method statuses (Conflicting if either conflicts).

**Limitations**
- Coverage depends on what the allowlisted publishers write and expose. Small cards, non-English coverage and very recent fights may be Not found or Single source.
- Pages rendered by JavaScript (e.g. ESPN stories) cannot be read; they are listed as links only and never used as evidence.
- Wikipedia is community-edited and listed as *Reference*; it counts as one publisher.
- Promoters are treated as official sources for results; they are not neutral.
- Rule-based extraction can miss unusual phrasing (safe failure: Not found). It can also misread a sentence, so every fact shows its quote — always open the source before settling.
- Results can differ between runs as feeds update or sites rate-limit requests.
- Judges' names are rarely stated in reports and are often Not found. The same-sentence rule also means a detail stated without naming a boxer ("The judges scored it 117-111…") is not used — a deliberate trade of coverage for safety.

## Tests

```bash
python -m pytest
```

All tests run offline: HTTP is mocked with fixture pages and feeds (`tests/fakes.py`), and real sockets are blocked.

## Deploy

Create a new private GitHub repository from this folder, then create a new Streamlit Cloud application with `app.py` as the entry point.
