"""Google News per-HCP RSS feed.

Free, unauthenticated RSS endpoint:
  https://news.google.com/rss/search?q=<query>&hl=en-US&gl=US&ceid=US:en

`external_handle` on the subscription is the literal query string, e.g.
`"Sara M Tolaney" OR "Tolaney SM"`. Auto-bound on HCP creation with the
HCP's canonical name; admin can override.

Disambiguation (v2 — stricter):

1. **Name match required.** The HCP's last name must appear in the title
   or description blob. If the first name is also present, that's stronger
   evidence. Without the name anywhere, the match is automatic-reject
   regardless of Google's relevance ranking.

2. **Medical context required.** At least one of:
   - Hospital affiliation token match (existing behavior)
   - Oncology/medicine specialty keyword in the blob
     ("oncolog", "cancer", "chemo", "breast", "clinical trial", "nejm",
      "asco", "patient", "tumor", "dose", "therapy", "fda approv",
      "medical", "doctor", "md," "md,"  etc.)

3. **Entertainment blocklist.** Hard-reject if the blob contains obvious
   non-medical context (TV show titles, movie terms, sports). Catches the
   "'The Pitt' Season 2 Cast" kind of hits that triggered this rewrite.

Items matching name-only but failing the medical-context check are
dropped with a debug log so we can tune the heuristic.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from lxml import etree

from .common import FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

FEED = "https://news.google.com/rss/search"
UA = "CHM-MediaHub-FeedFetcher/0.1 (sebastien@communityhealth.media)"

SIGNAL_TYPE = "news_article"

# Hospital-affiliation tokenization. Same stopword list as cold_tier_seed
# for consistency.
_STOP = {
    "the", "of", "for", "and", "at", "in", "a", "an", "medical", "center",
    "centers", "hospital", "hospitals", "health", "system", "systems",
    "clinic", "clinics", "inc", "llc", "pc", "group", "associates",
    "physicians", "institute",
}

# Medical/oncology context keywords. Any hit → "medical context present".
# Intentionally oncology-leaning since CHM's roster is oncology-focused.
_MEDICAL_KEYWORDS = (
    "oncolog", "cancer", "tumor", "tumour", "chemo", "breast", "metasta",
    "clinical trial", "clinical-trial", "trial result", "fda approv",
    "nejm", "lancet", "asco", "san antonio", "sabcs", "esmo",
    "patient", "therapy", "treatment", "drug", "medication", "prescri",
    "dose", "dosage", "md,", "md ", "mph", "doctor ", "physician",
    "radiation", "surgical", "hematolog", "immunotherap", "biomark",
    "genomic", "biopsy", "diagnos", "therapeutic",
)

# Things that strongly suggest the article is NOT about a physician.
# Hard-reject if matched (even if name + medical keyword both present —
# avoids "Dr. Smith Season 2 Cast" edge cases).
_ENTERTAINMENT_BLOCKLIST = (
    "season 2", "season 3", "season 4", "season 5", "season 1 cast",
    "cast shakeup", "cast changes", "confirmed to return", "confirmed exit",
    "sherlock holmes", "book review", "crime fiction", "booktrib",
    "just jared", "movie ", "film ", "tv show", "series premiere",
    "box office", "screen actor", "netflix series", "hbo series",
    "celebrity", "arrested in", "murder charge",
)

# "Dr X's" possessive → almost always a company (Dr Reddy's Laboratories,
# Dr Martens, etc.), not a specific physician. Hard-reject.
# Allow both straight ' and smart ' (ASCII 0x27 and Unicode 0x2019).
_COMPANY_POSSESSIVE = re.compile(r"\bdr\.?\s+\w+[\u2019']s\b", re.IGNORECASE)

# Surnames that are also common English nouns. For these, a last-name-only
# match is too weak — the article must contain the full first+last name AND
# medical context. Catches cases like "Dr. LeVee" matching "levee breach in
# Baton Rouge" or "Dr. Steele" matching steel-industry news.
_SURNAME_NOUN_COLLISIONS = {
    "levee", "steele", "steel", "stone", "wood", "woods", "rock", "river",
    "rivers", "brook", "brooks", "field", "fields", "park", "parks", "lake",
    "hill", "hills", "vale", "vail", "page", "pages", "young", "old",
    "white", "black", "brown", "green", "gray", "grey", "wright", "right",
    "knight", "king", "kings", "lord", "duke", "earl", "fox", "foxx", "wolf",
    "bear", "hunter", "hunt", "cook", "cooks", "baker", "miller", "smith",
    "carter", "porter", "potter", "tailor", "taylor", "weaver", "shepherd",
    "carpenter", "fisher", "fisherman", "marshall", "ward", "wards",
    "abbott", "bishop", "deacon", "abbot", "monk", "ace", "best", "case",
    "cope", "cross", "rich", "good", "fast", "long", "short", "small",
    "tall", "rosa", "rose", "lily", "violet", "summer", "winter", "spring",
    "fall", "snow", "rain", "dawn", "moon", "sun", "star", "sky",
    "may", "june", "april", "love", "joy", "hope", "faith", "pearl",
    "ruby", "amber", "jade", "ivory",
}

# Sports/obituary/society-event terms that were still slipping through.
# Conservative — only adds context-specific phrases, never single common
# words like "trial" or "study" that legitimate medical articles use.
_NON_MEDICAL_CONTEXT = (
    # Sports — verified leagues, sites, lingo
    "baseball", "basketball", "tennis", "football", "soccer", "cricket",
    "mlb.com", "espn", "espncricinfo", "premier league", "world cup",
    "ipl ", "lpga", "pga ", "nfl ", "nba ", "fifa", "uefa",
    "live score", "scores &", "ground ball", "innings", "wicket", "century",
    "box score", "lineup", "game recap", "training camp", "preseason",
    "released", "lions release", "lions wire", "goal.com", "flograppling",
    "jiu-jitsu", "ibjjf", "championship", "tournament", "marathon",
    "swing", "putt", "tee shot", "instructor", "coach", "manager said",

    # Obituaries / funeral homes (when "obituary" itself isn't in the title)
    "obituary", "funeral chapel", "funeral home", "memorial service",

    # Higher-ed / arts / academic non-medical
    "utsa grad", "grad ", "alumnus", "alum of",
    "fashion", "jewelry", "omega constellation", "gallery:",
    "psychedelic", "art exhibition", "biopic",
    "dean of arts", "dean of sciences", "named dean",
    "vice provost", "appointed dean",

    # Annual "Power N" / "Top N executives" lists
    "power 25", "power 50", "power 100", "top 25", "top 50",
    "40 under 40", "30 under 30",

    # Business / corporate (catches false-pharma matches)
    "laboratories", "ltd.", "holdings", "founding partner",
    "ceo of", "founder of", "chairman of", "infotech", "open market purchase",
    "boost stake", "licensing pact", "ink cancer drug licensing",
    "net worth", "multi-crore", "stake to", "settles suit",

    # Religion / community (matched physician names by coincidence)
    "evangelist", "pastor", "ministry ", "diocese",

    # Bollywood / Hindi cinema (multiple mukesh bhatt false positives)
    "bollywood", "bhatt family", "alia bhatt", "mahesh bhatt",
    "soni razdan", "raha", "pritam", "neha kakkar", "neeraj shridhar",
    "mohit suri", "razdan",

    # UK soap stars / actresses with cancer death stories
    # (false-positive vector — "cancer battle" trips medical kw)
    "eastenders", "bbc star", "soap star", "actress dies", "actor dies",
    "soap actress", "tv actress", "tv actor",
    "cancer battle", "after cancer fight",

    # Tech industry analysts (Ming-Chi Kuo etc.)
    "apple analyst", "tech analyst", "kuo",
    "foldable iphone", "macdailynews",

    # Crime / litigation
    "rape", "assault", "settles suit", "filed suit", "lawsuit alleg",
    "accused him of", "criminal complaint",
)

# Common first+last name pairs (mostly non-Western names that have many
# unrelated celebrity/sports/business hits in Google News). For these,
# require both full-name AND hospital match — same treatment as surname
# collisions.
# Common name pairs that have many globally-famous non-medical homonyms
# (athletes, actors, executives). For these the filter requires both
# full-name AND hospital match.
#
# CAREFUL: do not add pairs where the doctor IS legitimately newsworthy
# (e.g. "linda buck" = Nobel laureate in Olfaction, "anil potti" =
# retraction-watch oncologist). Those collisions resolve naturally via
# the hospital-affiliation match if the doctor has a hospital populated.
_COMMON_NAME_PAIRS = {
    ("rashid", "khan"), ("mukesh", "bhatt"), ("mahesh", "bhatt"),
    ("alia", "bhatt"), ("ming", "chi"), ("ming-chi", "kuo"),
    ("henry", "fox"),
    ("mukul", "gupta"), ("sumit", "sawhney"),  # Renault India MD
    ("alyssa", "thompson"), ("meredith", "kirk"), ("thomas", "oliver"),
    ("joseph", "moore"), ("michael", "goodman"),
}


def _hospital_keywords(hosp: str | None) -> list[str]:
    if not hosp:
        return []
    parts = re.split(r"[,;/|&\-\s]+", hosp.lower())
    return [p for p in parts if p and len(p) > 3 and p not in _STOP]


def _name_tokens(first: str | None, last: str | None) -> tuple[str, str]:
    f = (first or "").strip().lower()
    l = (last or "").strip().lower()
    return f, l


# Strip HTML tags + entity-decode so RSS descriptions render cleanly.
# Google News descriptions frequently include anchor tags and entities
# like `&nbsp;` or `&#x27;` that would leak into the UI otherwise.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_html(s: str | None) -> str | None:
    if not s:
        return s
    decoded = html.unescape(s)
    no_tags = _TAG_RE.sub(" ", decoded)
    return _WS_RE.sub(" ", no_tags).strip() or None


def _has_name(blob: str, first: str, last: str) -> tuple[bool, bool]:
    """Returns (last_found, first_and_last_found)."""
    if not last:
        return (False, False)
    # Word-boundary match so "shen" doesn't match "shenanigan" or "cohen".
    last_pat = rf"\b{re.escape(last)}\b"
    last_found = bool(re.search(last_pat, blob))
    if not first or not last_found:
        return (last_found, False)
    first_pat = rf"\b{re.escape(first)}\b"
    first_found = bool(re.search(first_pat, blob))
    return (last_found, last_found and first_found)


def parse_feed(xml_bytes: bytes) -> list[FeedItemPayload]:
    if not xml_bytes:
        return []
    root = etree.fromstring(xml_bytes)
    items: list[FeedItemPayload] = []
    for item in root.iter("item"):
        title = _clean_html(item.findtext("title")) or ""
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        description = _clean_html(item.findtext("description")) or ""
        pub_date = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source_name = (source_el.text or "").strip() if source_el is not None else ""
        try:
            pub_at = parsedate_to_datetime(pub_date) if pub_date else None
            if pub_at is not None:
                pub_at = pub_at.replace(tzinfo=None)
        except (TypeError, ValueError):
            pub_at = None
        items.append(
            FeedItemPayload(
                external_id=guid,
                title=title,
                url=link or None,
                published_at=pub_at,
                raw={
                    "description": description,
                    "source_name": source_name,
                    "pubDate": pub_date,
                },
            )
        )
    return items


async def fetch_for_query(
    query: str, *, client: httpx.AsyncClient | None = None
) -> list[FeedItemPayload]:
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        r = await client.get(
            FEED,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers={"User-Agent": UA},
        )
        r.raise_for_status()
        return parse_feed(r.content)
    finally:
        if own:
            await client.aclose()


def extract_signals(
    item: FeedItemPayload,
    *,
    hospital_affiliations: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> list[SignalPayload]:
    """Convert a Google News feed item to an hcp_signals row, applying the
    disambiguation filter.

    Three checks, in order:
    1. Name must appear in title+description.
    2. Must NOT contain entertainment/non-medical red flags.
    3. Must contain either a hospital token match OR a medical keyword.

    All three must pass. Any failure → drop the item silently.
    """
    if item.published_at is None:
        return []

    # Reject future-dated items (Google News sometimes returns placeholder
    # dates or regional feeds shift timezones oddly).
    if item.published_at > datetime.utcnow():
        return []

    title = item.title or ""
    description = (item.raw or {}).get("description") or ""
    blob = (title + " " + description).lower()

    first, last = _name_tokens(first_name, last_name)

    # (1) Name check — require at least last-name match if we know the name.
    if last:
        last_ok, full_ok = _has_name(blob, first, last)
        if not last_ok:
            return []
    else:
        # No name metadata → can't verify. Fall back to historical behavior
        # (hospital-only filter) below.
        full_ok = False

    # (2) Entertainment / non-medical blocklist
    if any(bad in blob for bad in _ENTERTAINMENT_BLOCKLIST):
        return []
    if any(bad in blob for bad in _NON_MEDICAL_CONTEXT):
        return []
    if _COMPANY_POSSESSIVE.search(blob):
        return []

    # (3) Medical context — hospital match OR medical keyword
    # Hospital match requires ≥2 tokens overlapping. A single-token match
    # is too weak — "henry" matching both "Fox Henry B Office" and "Ed
    # Henry Fox News" was a false-positive vector.
    has_hospital = False
    hospital_keys = _hospital_keywords(hospital_affiliations)
    if hospital_keys:
        hits = sum(1 for k in hospital_keys if k in blob)
        has_hospital = hits >= 2 or (
            hits >= 1 and len(hospital_keys) == 1  # one-token hospital edge
        )

    has_medical_kw = any(kw in blob for kw in _MEDICAL_KEYWORDS)

    if not (has_hospital or has_medical_kw):
        return []

    # If we matched on last-name-only (no first name) AND have no hospital
    # signal, require medical context to be stronger (≥2 keyword hits).
    # When the full name matches OR hospital matches, 1 medical hit is plenty.
    if last and not full_ok and not has_hospital:
        # Only enforce the stricter bar when the last name is a real English
        # word (tri-gram test: if it's in a common-surname→common-noun
        # collision pool, require more context). Heuristic: last names ≤ 5
        # chars AND lowercase-only in text are often false friends.
        short_collide = len(last) <= 5
        if short_collide:
            hits = sum(1 for kw in _MEDICAL_KEYWORDS if kw in blob)
            if hits < 2:
                return []

    # Surname-noun collisions (LeVee/levee, Steele/steel, etc.): require
    # both the full first+last name AND a hospital match. Medical keywords
    # alone aren't enough because the article can be about a "levee breach"
    # in a city that happens to have a hospital.
    if last in _SURNAME_NOUN_COLLISIONS:
        if not (full_ok and has_hospital):
            return []

    # Common-name pairs (Rashid Khan, Mukesh Bhatt, etc.) collide globally
    # with athletes, actors, analysts. Same strict bar as surname collisions.
    if (first, last) in _COMMON_NAME_PAIRS:
        if not (full_ok and has_hospital):
            return []

    return [
        SignalPayload(
            signal_type=SIGNAL_TYPE,
            observed_at=item.published_at,
            title=item.title,
            url=item.url,
            summary=description[:500] or None,
            entities={
                "source_name": (item.raw or {}).get("source_name"),
                "guid": item.external_id,
            },
            drugs=[],
        )
    ]
