from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import html
from urllib.parse import urlencode

import streamlit as st

DEMO_MODE = "Demo search"
FREE_MODE = "Free source discovery"


@dataclass(frozen=True)
class Evidence:
    label: str
    url: str
    status: str


@dataclass(frozen=True)
class Fight:
    fighter_a: str
    fighter_b: str
    event_date: date
    offered_date: date
    event: str
    location: str
    division: str
    scheduled_rounds: int
    winner: str
    method: str
    round_time: str
    scorecards: str
    knockdowns: tuple[str, ...]
    officials: str
    title: str
    confidence: str
    notes: str
    evidence: tuple[Evidence, ...]
    aliases: tuple[str, ...] = ()


FIGHTS: tuple[Fight, ...] = (
    Fight("Ben Whittaker", "Conor Wallace", date(2026, 10, 3), date(2026, 10, 3), "Whittaker vs Wallace", "Utilita Arena, Birmingham, UK", "Light Heavyweight", 12, "Ben Whittaker", "Unanimous Decision", "12 rounds", "117–111, 116–112, 115–113", ("Canvas incidents reported late in the fight — official knockdown confirmation required.",), "To be collected from official result", "IBF final eliminator", "Corroborated", "Do not settle a knockdown market solely from reports of a boxer going to the canvas.", (Evidence("ESPN fight report", "https://www.espn.com/boxing/story/_/id/50093253/ben-whittaker-dominates-chaotic-finish-outpoint-conor-wallace", "Corroborated"),)),
    Fight("Omari Jones", "Alan Sanchez", date(2026, 10, 2), date(2026, 10, 3), "Matchroom Boxing Project Series 2", "Orlando, Florida, USA", "Super Welterweight", 8, "Omari Jones", "TKO", "Round 2", "Not applicable", ("Knockdown detail requires source review.",), "To be collected", "—", "Corroborated", "Local event date is 2 Oct; offered time falls on 3 Oct in UTC-facing systems.", (Evidence("FightMag event results", "https://www.fightmag.com/project-series-2-jones-vs-sanchez-live-results/", "Corroborated"),)),
    Fight("Jordan Orozco", "Yusniel Abrahante", date(2026, 10, 2), date(2026, 10, 3), "Matchroom Boxing Project Series 2", "Orlando, Florida, USA", "Bantamweight", 8, "Jordan Orozco", "TKO", "Round 6, 2:31", "Not applicable", ("No confirmed knockdown record in the demo evidence set.",), "To be collected", "—", "Corroborated", "Alias handling is required for Jordan Orozco Hernandez.", (Evidence("Boxing Wire event report", "https://www.boxingwire.com/article/omari-jones-stops-sanchez-project-series-2", "Corroborated"),), ("Jordan Orozco Hernandez",)),
    Fight("Takuma Inoue", "Tenshin Nasukawa", date(2026, 9, 27), date(2026, 9, 27), "Inoue vs Nasukawa II", "Toyota Arena, Tokyo, Japan", "Bantamweight", 12, "Takuma Inoue", "Unanimous Decision", "12 rounds", "116–111, 116–111, 114–113", ("Tenshin Nasukawa credited with a knockdown of Takuma Inoue in Round 7.",), "To be collected", "WBC World Bantamweight title", "Corroborated", "International / non-English source discovery is required.", (Evidence("World Boxing News live results", "https://www.worldboxingnews.com/inoue-vs-nasukawa-2-live-results/", "Corroborated"),)),
    Fight("Isaac Cruz", "Nestor Bravo", date(2026, 9, 19), date(2026, 9, 20), "Cruz vs Bravo", "Pechanga Arena, San Diego, USA", "Super Lightweight", 12, "Isaac Cruz", "KO", "Round 6", "Not applicable", ("Bravo reportedly knocked down in Round 1.", "Final KO sequence in Round 6 — review source policy before counting as an additional KD."), "Thomas Taylor (reported)", "WBC Interim Super Lightweight title", "Confirmed", "A good test of a stoppage plus prior scored knockdown.", (Evidence("Premier Boxing Champions", "https://www.premierboxingchampions.com/bouts/715374", "Confirmed"), Evidence("Boxing News 24 round-by-round", "https://www.boxingnews24.com/2026/09/isaac-cruz-vs-nestor-bravo-live-scorecard-and-results/", "Corroborated"))),
    Fight("Pat Brown", "John Hedges", date(2026, 9, 19), date(2026, 9, 19), "Brown vs Hedges", "Co-op Live, Manchester, UK", "Cruiserweight", 12, "Pat Brown", "KO", "Round 6, 2:36", "Not applicable", ("John Hedges reported down twice from body shots before the stoppage.",), "To be collected", "British & Commonwealth / WBA International Cruiserweight titles", "Corroborated", "Strong test case for a repeatable knockdown-evidence list.", (Evidence("WBA event report", "https://www.wbaboxing.com/boxing-news/pat-brown-knocked-out-john-hedges-to-win-the-wba-international-cruiserweight-title", "Confirmed"),)),
    Fight("Lazaro Lorenzana", "Marcos Vazquez", date(2026, 9, 19), date(2026, 9, 19), "Cruz vs Bravo undercard", "San Diego, USA", "Super Middleweight", 10, "Lazaro Lorenzana", "Majority Decision", "10 rounds", "Partial / source review required", ("No reliable knockdown information located in the demo set.",), "To be collected", "—", "Corroborated", "A lower-coverage majority-decision test.", (Evidence("FightMag event results", "https://www.fightmag.com/boxing-isaac-pitbull-cruz-vs-nestor-bravo-live-results/", "Corroborated"),), ("Lazaro Francisco Lorenzana", "Marcos Vazquez Rodriguez")),
    Fight("Shabaz Masoud", "Ckari Mansilla", date(2026, 9, 19), date(2026, 9, 19), "Brown vs Hedges", "Manchester, UK", "Featherweight", 12, "Shabaz Masoud", "Unanimous Decision", "12 rounds", "Partial / source review required", ("No reliable knockdown information located in the demo set.",), "To be collected", "WBA International Featherweight title", "Confirmed", "Name normalisation must include Ckari Cani Mansilla.", (Evidence("WBA event report", "https://www.wbaboxing.com/boxing-news/shabaz-masoud-defeated-mansilla-for-the-wba-international-featherweight-title", "Confirmed"),), ("Ckari Cani Mansilla",)),
    Fight("Bobbi Flood", "Jack Swallow", date(2026, 9, 5), date(2026, 9, 5), "Taylor vs Pili undercard", "Dublin, Ireland", "—", 4, "Bobbi Flood", "Points", "4 rounds", "40–36", ("No reliable knockdown information located in the demo set.",), "To be collected", "—", "Corroborated", "Small-card points-decision coverage test.", (Evidence("BoxRec forum event coverage", "https://boxrec.com/forum/viewtopic.php?p=6224086", "Single source"),)),
    Fight("Andy Ruiz Jr", "Damian Knyba", date(2026, 9, 4), date(2026, 9, 5), "Ruiz vs Knyba", "Prudential Center, Newark, USA", "Heavyweight", 10, "Damian Knyba", "Unanimous Decision", "10 rounds", "Official PDF available — extract per-judge scores", ("Andy Ruiz Jr reported knocked down in Round 7.",), "Official New Jersey result document available", "—", "Confirmed", "Model case for official commission-PDF extraction.", (Evidence("New Jersey official results PDF", "https://nj.gov/oag/sacb/results/2026-0904_Official_Show_Results_Pro_Boxing-Prudential_Center_Newark_Matchroom.pdf", "Confirmed"), Evidence("NJ Boxing News", "https://njboxingnews.com/damian-knyba-drops-andy-ruiz-wins-decision-at-prudential-center/", "Corroborated"))),
    Fight("Takeshi Ishii", "Wilfredo Mendez", date(2026, 9, 2), date(2026, 9, 2), "Lemino Boxing double world-title card", "Yokohama, Japan", "Minimumweight", 12, "Takeshi Ishii", "KO", "Round 1, 1:05", "Not applicable", ("Exact knockdown count requires confirmation.",), "To be collected", "WBA Minimumweight World title", "Confirmed", "Strong Japan/title-fight result source; use Japanese source variants.", (Evidence("WBA event report", "https://www.wbaboxing.com/boxing-news/takeshi-ishii-destroys-wilfredo-mendez-in-the-first-round-to-claim-wba-title", "Confirmed"),)),
    Fight("Weljon Mindoro", "Carlos Ocampo", date(2026, 8, 29), date(2026, 8, 30), "Martinez vs Plantic undercard", "Los Angeles, USA", "Catchweight", 10, "Carlos Ocampo", "TKO", "Round 9", "Not applicable", ("Exact knockdown count requires confirmation.",), "To be collected", "—", "Corroborated", "Use alias Wejlon Mindoro during discovery.", (Evidence("Manila Bulletin fight report", "https://mb.com.ph/2026/08/30/weljon-mindoro-suffers-first-career-defeat-vs-ocampo", "Corroborated"),), ("Wejlon Mindoro",)),
    Fight("Gemma Richardson", "Kirstie Bavington", date(2026, 8, 29), date(2026, 8, 29), "MVPW-06", "Birmingham, UK", "Super Lightweight", 6, "Gemma Richardson", "Decision", "6 rounds", "60–54", ("No reliable knockdown information located in the demo set.",), "To be collected", "—", "Confirmed", "Strong women’s boxing points-decision test.", (Evidence("Most Valuable Promotions official report", "https://www.mostvaluablepromotions.com/mvpw-06-gemma-richardson-shuts-out-kirstie-bavington/", "Confirmed"),)),
)


def normalise(value: str) -> str:
    return " ".join(value.casefold().replace("jr.", "jr").split())


def find_fight(fighter_a: str, fighter_b: str, selected_date: Optional[date]) -> Optional[Fight]:
    a, b = normalise(fighter_a), normalise(fighter_b)
    for fight in FIGHTS:
        names_a = {normalise(fight.fighter_a), *(normalise(alias) for alias in fight.aliases)}
        names_b = {normalise(fight.fighter_b), *(normalise(alias) for alias in fight.aliases)}
        direct = a in names_a and b in names_b
        reverse = a in names_b and b in names_a
        dates_match = selected_date in {fight.event_date, fight.offered_date} if selected_date else True
        if (direct or reverse) and dates_match:
            return fight
    return None


def badge(status: str) -> str:
    colors = {"Confirmed": "#147a4b", "Corroborated": "#1f6db3", "Single source": "#8a5a00", "Review": "#8a5a00", "Unavailable": "#5c6470", "Conflicting": "#b8322f"}
    color = colors.get(status, "#5c6470")
    return f"<span style='background:{color};color:white;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:700'>{status}</span>"


def build_source_links(fighter_a: str, fighter_b: str, event_date: date, event_name: str = "") -> list[tuple[str, str, str]]:
    """Return (label, query, url) search links. Nothing is fetched by the app."""
    a, b = (name.replace('"', "").strip() for name in (fighter_a, fighter_b))
    pair = f'"{a}" "{b}"'
    when = event_date.strftime("%d %B %Y")
    event = f' "{event_name.replace(chr(34), "").strip()}"' if event_name.strip() else ""
    google = "https://www.google.com/search?"
    searches = [
        ("General result search — DuckDuckGo", f"{pair} boxing result {when}{event}", "https://duckduckgo.com/?"),
        ("General result search — Google", f"{pair} boxing result {when}{event}", google),
        ("BoxRec lookup — Google site:boxrec.com", f"site:boxrec.com {pair}", google),
        ("Tapology lookup — Google site:tapology.com", f"site:tapology.com {pair}", google),
        ("Official / promoter report search", f'{pair} boxing ("official result" OR promoter OR commission OR scorecards) {when}{event}', google),
        ("Round-by-round / knockdown evidence search", f'{pair} boxing ("round by round" OR knockdown OR "knocked down") {when}{event}', google),
    ]
    return [(label, query, base + urlencode({"q": query})) for label, query, base in searches]


def render_free_discovery() -> None:
    st.warning("Free source discovery builds **unverified manual source links** only. The app does not open, read or extract these pages, does not claim any result, and does not settle any market.")
    st.caption("No account, API key, card or server-side web scraping is needed: each link simply opens a public search in a new browser tab for you to review.")

    with st.form("free-source-discovery"):
        left, middle, right = st.columns([1, 1, 0.8])
        fighter_a = left.text_input("Boxer A", placeholder="e.g. Isaac Cruz")
        fighter_b = middle.text_input("Boxer B", placeholder="e.g. Nestor Bravo")
        event_date = right.date_input("Event / offered date", value=date(2026, 9, 20))
        event_name = st.text_input("Event name (optional)", placeholder="e.g. Cruz vs Bravo")
        submitted = st.form_submit_button("Build source links", type="primary", use_container_width=True)

    if not submitted:
        st.info("Enter both boxer names and the event date to build manual search links.")
        return
    if not fighter_a.strip() or not fighter_b.strip():
        st.error("Please enter both boxer names.")
        return

    st.markdown("### Manual source links")
    for label, query, url in build_source_links(fighter_a, fighter_b, event_date, event_name):
        with st.container(border=True):
            st.markdown(f"{badge('Unverified manual source link')} &nbsp; <a href='{html.escape(url, quote=True)}' target='_blank' rel='noopener noreferrer'><strong>{html.escape(label)}</strong> ↗</a>", unsafe_allow_html=True)
            st.caption(f"Search: {query}")
    st.caption("Search results are not verified evidence. Review each source against the operator’s own settlement rules.")


st.set_page_config(page_title="Boxing Match Information Assistant", page_icon="🥊", layout="wide")
st.markdown("""
<style>
.stApp { background: #08111f; color: #f4f7fb; }
[data-testid='stSidebar'] { background: #0d1b2d; }
.hero { background: linear-gradient(120deg, #102a4a, #0b1728 55%, #8f1d2c); border: 1px solid #29425f; border-radius: 20px; padding: 28px 32px; margin-bottom: 20px; }
.hero h1 { margin: 0; color: #fff; font-size: 2.15rem; }
.hero p { color: #e6edf5; margin: 8px 0 0; }
.panel { background: #101e30; border: 1px solid #3a5372; border-radius: 14px; padding: 18px; min-height: 132px; }
.label { color: #a9bdd4; font-size: 0.78rem; text-transform: uppercase; letter-spacing: .08em; }
.value { color: #fff; font-weight: 700; font-size: 1.2rem; margin-top: 4px; }
.muted { color: #c3d0df; }
a { color: #75b8ff !important; }
[data-testid='stCaptionContainer'] { opacity: 1 !important; }
[data-testid='stCaptionContainer'], [data-testid='stCaptionContainer'] p { color: #c3d0df !important; }
[data-testid^='stBaseButton-primary'], [data-testid^='stBaseButton-primary'] p { color: #fff !important; }
.stApp button:disabled { background: #142234 !important; border: 1px dashed #5b7594 !important; cursor: not-allowed; opacity: 1; }
.stApp button:disabled, .stApp button:disabled p { color: #8597ad !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🥊 Boxing Intelligence")
    st.caption("Post-match evidence assistant")
    mode = st.radio("Mode", [DEMO_MODE, FREE_MODE], index=0)
    st.divider()
    st.markdown("**Version 1 principle**")
    st.caption("The trader settles the market. The app supplies traceable facts and warnings.")
    st.divider()
    st.markdown("**Demo corpus**")
    st.caption(f"{len(FIGHTS)} offered professional fights")

st.markdown("""
<div class='hero'>
  <h1>Boxing Match Information Assistant</h1>
  <p>Find a completed fight, review the evidence, and make a confident settlement decision.</p>
</div>
""", unsafe_allow_html=True)

if mode == FREE_MODE:
    render_free_discovery()
    st.stop()

with st.form("fight-search"):
    left, middle, right = st.columns([1, 1, 0.8])
    fighter_a = left.text_input("Boxer A", placeholder="e.g. Isaac Cruz")
    fighter_b = middle.text_input("Boxer B", placeholder="e.g. Nestor Bravo")
    event_date = right.date_input("Event / offered date", value=date(2026, 9, 20))
    submitted = st.form_submit_button("Search completed fight", type="primary", use_container_width=True)

if not submitted:
    st.info("Demo mode is ready. Try **Isaac Cruz / Nestor Bravo** with 20 Sep 2026, or select one of the examples below.")
    choices = [f"{f.fighter_a} vs {f.fighter_b}" for f in FIGHTS]
    selected = st.selectbox("Load a demo fight", choices)
    if st.button("Load report"):
        selected_fight = FIGHTS[choices.index(selected)]
    else:
        selected_fight = None
else:
    selected_fight = find_fight(fighter_a, fighter_b, event_date)

if submitted and not selected_fight:
    st.error("No exact demo match found. In the live version this area will show possible matches and alias suggestions instead of returning an empty result.")

if selected_fight:
    fight = selected_fight
    st.markdown("### Match report")
    st.caption(f"{fight.event} · {fight.location}")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"<div class='panel'><div class='label'>Official outcome</div><div class='value'>{fight.winner}</div><div class='muted'>{fight.method}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='panel'><div class='label'>Round / time</div><div class='value'>{fight.round_time}</div><div class='muted'>Scheduled: {fight.scheduled_rounds} rounds</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='panel'><div class='label'>Scorecards</div><div class='value'>{fight.scorecards}</div><div class='muted'>{fight.division}</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='panel'><div class='label'>Evidence confidence</div><div class='value'>{badge(fight.confidence)}</div><div class='muted' style='margin-top:14px'>{fight.title}</div></div>", unsafe_allow_html=True)

    st.write("")
    main, side = st.columns([1.55, 1])
    with main:
        st.markdown("#### Knockdown evidence")
        if fight.knockdowns:
            for item in fight.knockdowns:
                st.warning(item)
        else:
            st.info("Unavailable — no reliable knockdown evidence found.")
        st.markdown("#### Officials and event metadata")
        st.markdown(f"- **Division:** {fight.division}\n- **Scheduled rounds:** {fight.scheduled_rounds}\n- **Referee / judges:** {fight.officials}\n- **Titles:** {fight.title}\n- **Event date:** {fight.event_date.strftime('%d %b %Y')}\n- **Offered date:** {fight.offered_date.strftime('%d %b %Y')}")
    with side:
        st.markdown("#### Evidence ledger")
        for source in fight.evidence:
            st.markdown(f"{badge(source.status)} &nbsp; [{source.label}]({source.url})", unsafe_allow_html=True)
        st.markdown("#### Trader note")
        st.info(fight.notes)

    st.markdown("#### Settlement support")
    st.caption("No market is settled automatically. Use these facts as evidence for the operator’s own settlement rules.")
    with st.expander("Show data availability"):
        st.dataframe({"Field": ["Outcome", "Method", "Round / time", "Scorecards", "Knockdowns", "Round statistics", "Officials"], "Status": [fight.confidence, fight.confidence, fight.confidence, "Available" if fight.scorecards not in {"Not applicable", "Partial / source review required"} else "Review", "Review" if "requires" in " ".join(fight.knockdowns).lower() or "reported" in " ".join(fight.knockdowns).lower() else "Unavailable", "Unavailable", "Review" if "To be collected" in fight.officials else "Available"]}, hide_index=True, use_container_width=True)
