"""Source allowlist, tiers and public feeds used for automatic match reports.

Only domains listed here are ever fetched. Search engines, social networks and
login-gated or bot-protected sites (Google, Facebook, Instagram, X, BoxRec,
Tapology, BoxingScene) are deliberately absent.
"""
from __future__ import annotations

from typing import Optional

OFFICIAL = "Official"
MEDIA = "Established media"
REFERENCE = "Reference"

# domain -> (display name, tier)
DOMAINS: dict[str, tuple[str, str]] = {
    # Sanctioning bodies
    "wbcboxing.com": ("WBC", OFFICIAL),
    "wbaboxing.com": ("WBA", OFFICIAL),
    "wboboxing.com": ("WBO", OFFICIAL),
    "ibf-usba-boxing.com": ("IBF", OFFICIAL),
    # Promoters (official result announcements)
    "mostvaluablepromotions.com": ("Most Valuable Promotions", OFFICIAL),
    "matchroomboxing.com": ("Matchroom Boxing", OFFICIAL),
    "premierboxingchampions.com": ("Premier Boxing Champions", OFFICIAL),
    "toprank.com": ("Top Rank", OFFICIAL),
    "goldenboy.com": ("Golden Boy Promotions", OFFICIAL),
    "queensberry.co.uk": ("Queensberry Promotions", OFFICIAL),
    # Commissions / boards
    "nj.gov": ("New Jersey State Athletic Control Board", OFFICIAL),
    "tdlr.texas.gov": ("Texas Department of Licensing and Regulation", OFFICIAL),
    "bbbofc.com": ("British Boxing Board of Control", OFFICIAL),
    # Established media
    "espn.com": ("ESPN", MEDIA),
    "espn.co.uk": ("ESPN", MEDIA),
    "bbc.co.uk": ("BBC Sport", MEDIA),
    "bbc.com": ("BBC Sport", MEDIA),
    "theguardian.com": ("The Guardian", MEDIA),
    "skysports.com": ("Sky Sports", MEDIA),
    "badlefthook.com": ("Bad Left Hook", MEDIA),
    "dazn.com": ("DAZN", MEDIA),
    "ringmagazine.com": ("The Ring", MEDIA),
    "boxingnewsonline.net": ("Boxing News", MEDIA),
    "boxingnews24.com": ("Boxing News 24", MEDIA),
    "worldboxingnews.net": ("World Boxing News", MEDIA),
    "worldboxingnews.com": ("World Boxing News", MEDIA),
    "fightmag.com": ("FightMag", MEDIA),
    "cbssports.com": ("CBS Sports", MEDIA),
    "apnews.com": ("Associated Press", MEDIA),
    "reuters.com": ("Reuters", MEDIA),
    "independent.co.uk": ("The Independent", MEDIA),
    "telegraph.co.uk": ("The Telegraph", MEDIA),
    "mb.com.ph": ("Manila Bulletin", MEDIA),
    # Reference
    "en.wikipedia.org": ("Wikipedia", REFERENCE),
}

# Same publisher on several domains: count once when judging independence.
PUBLISHER_ALIASES = {"bbc.com": "bbc.co.uk", "espn.co.uk": "espn.com", "worldboxingnews.com": "worldboxingnews.net"}

# Recent-news RSS feeds (only useful for fights in the last few weeks).
RECENT_FEEDS: tuple[str, ...] = (
    "https://feeds.bbci.co.uk/sport/boxing/rss.xml",
    "https://www.espn.com/espn/rss/boxing/news",
    "https://www.theguardian.com/sport/boxing/rss",
    "https://www.skysports.com/rss/12183",
    "https://www.badlefthook.com/rss/index.xml",
    "https://www.boxingnewsonline.net/feed/",
)

# Sites exposing their own WordPress search as an RSS feed (?s=...&feed=rss2).
SEARCH_FEED_SITES: tuple[str, ...] = (
    "https://wbcboxing.com/en",
    "https://www.wbaboxing.com",
    "https://wboboxing.com",
    "https://www.ibf-usba-boxing.com",
    "https://www.mostvaluablepromotions.com",
    "https://www.boxingnews24.com",
    # World Boxing News (redirects search to its homepage) and FightMag (returns HTML, not a feed)
    # were removed: they returned no results and only used up requests.
)

# Feed hosts that are not article sources themselves.
FEED_ONLY_HOSTS = {"feeds.bbci.co.uk"}


def domain_for(host: str) -> Optional[str]:
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    for domain in DOMAINS:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def is_fetch_allowed(host: str) -> bool:
    return domain_for(host) is not None or host.lower() in FEED_ONLY_HOSTS


def describe(host: str) -> tuple[str, str]:
    """(display name, tier) for an allowlisted host."""
    domain = domain_for(host)
    return DOMAINS[domain] if domain else (host, "Other")


def publisher(host: str) -> str:
    domain = domain_for(host) or host.lower()
    return PUBLISHER_ALIASES.get(domain, domain)
