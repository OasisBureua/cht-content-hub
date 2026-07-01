"""PubMed E-utilities fetcher + extractor.

Fetches papers for a confirmed HCP via `fetch_papers_for_hcp` and extracts
publication signals (with drug refs from MeSH) via `extract_signals`.

Disambiguation is separate (`hcp_intel.disambiguation`) — this module is the
dumb data pipe after resolution has happened.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncio

import httpx
from lxml import etree

from hcp_intel.drug_normalize import (
    DRUG_QUALIFIER_UIS,
    is_drug_class_heading,
    is_drug_term,
    normalize_drug,
)

from .common import DrugPayload, FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UA = "CHM-MediaHub-FeedFetcher/0.1 (sebastien@communityhealth.media)"


def _api_key() -> str:
    return os.getenv("NCBI_API_KEY", "")


def _rate_delay_seconds() -> float:
    """NCBI limit: 3 req/sec without a key, 10 req/sec with one. Be polite."""
    return 0.12 if _api_key() else 0.4


def _build_url(path: str, params: dict[str, str]) -> str:
    key = _api_key()
    if key:
        params = {**params, "api_key": key}
    from urllib.parse import urlencode

    return f"{BASE}/{path}?{urlencode(params)}"


async def _esearch(client: httpx.AsyncClient, query: str, retmax: int = 200) -> list[str]:
    await asyncio.sleep(_rate_delay_seconds())
    url = _build_url(
        "esearch.fcgi",
        {"db": "pubmed", "term": query, "retmax": str(retmax), "retmode": "json"},
    )
    r = await client.get(url, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


async def _efetch(client: httpx.AsyncClient, pmids: list[str]) -> bytes:
    if not pmids:
        return b""
    await asyncio.sleep(_rate_delay_seconds())
    url = _build_url(
        "efetch.fcgi",
        {
            "db": "pubmed",
            "id": ",".join(pmids[:200]),
            "rettype": "xml",
            "retmode": "xml",
        },
    )
    r = await client.get(url, headers={"User-Agent": UA}, timeout=30.0)
    r.raise_for_status()
    return r.content


@dataclass
class PubMedPaper:
    pmid: str
    title: str
    journal: str
    pub_date: datetime | None
    first_author: str
    authors_count: int
    affiliations: list[str]
    mesh_drugs: list[DrugPayload]
    abstract: str | None
    is_first_author_match: bool = False
    is_last_author_match: bool = False


def _text(el: etree._Element | None) -> str:
    if el is None:
        return ""
    # Flatten child text (strip inline markup like <i>, <sub>)
    return "".join(el.itertext()).strip()


def _parse_pub_date(article: etree._Element) -> datetime | None:
    """Extract the publication date. Tries JournalIssue/PubDate first.

    Clamps future dates to today. PubMed returns the journal "cover date"
    which is often months ahead of actual availability (e.g., a paper
    online in April listed with a July 2026 cover date). If we're seeing
    the paper, it exists — don't let the cover date make it look unborn.
    """
    node = article.find(".//Journal/JournalIssue/PubDate")
    if node is None:
        node = article.find(".//DateCompleted") or article.find(".//DateRevised")
    if node is None:
        return None

    parsed: datetime | None = None
    year_el = node.find("Year")
    if year_el is not None and year_el.text:
        year = int(year_el.text)
        month_el = node.find("Month")
        day_el = node.find("Day")
        month = _month_to_int(month_el.text if month_el is not None else None) or 1
        day = int(day_el.text) if day_el is not None and day_el.text else 1
        try:
            parsed = datetime(year, month, day)
        except ValueError:
            parsed = datetime(year, 1, 1)
    else:
        ml = node.find("MedlineDate")
        if ml is not None and ml.text:
            try:
                parsed = datetime(int(ml.text[:4]), 1, 1)
            except ValueError:
                return None

    if parsed is None:
        return None

    # Clamp future cover dates to today.
    now = datetime.utcnow()
    if parsed > now:
        return now
    return parsed


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_to_int(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return _MONTHS.get(raw[:3].lower())


def _extract_authors(article: etree._Element) -> tuple[str, int, list[str]]:
    """Return (first_author_display, count, per-author-affiliations[])."""
    authors = article.findall(".//AuthorList/Author")
    affiliations: list[str] = []
    first_author = ""
    for i, a in enumerate(authors):
        last = _text(a.find("LastName"))
        initials = _text(a.find("Initials"))
        if i == 0 and last:
            first_author = f"{last} {initials}".strip()
        for aff in a.findall("AffiliationInfo/Affiliation"):
            t = _text(aff)
            if t and t not in affiliations:
                affiliations.append(t)
    return first_author, len(authors), affiliations


def _author_full_names(article: etree._Element) -> list[tuple[str, str, str, list[str]]]:
    """Return [(last, first/forename, initials, [affiliations]), ...] for each author.

    Used to confirm a paper actually belongs to the target HCP — PubMed's
    `Shen J[Author]` query returns every Shen with first initial J, including
    Jianxing/Jingshan/etc. The post-filter requires either:
      - exact ForeName/last match against the HCP's first/last name, OR
      - last + initial match AND ≥1 affiliation matches the HCP's locale.
    """
    out: list[tuple[str, str, str, list[str]]] = []
    for a in article.findall(".//AuthorList/Author"):
        last = _text(a.find("LastName"))
        fore = _text(a.find("ForeName"))
        inits = _text(a.find("Initials"))
        affs: list[str] = []
        for aff in a.findall("AffiliationInfo/Affiliation"):
            t = _text(aff)
            if t:
                affs.append(t)
        if last:
            out.append((last, fore, inits, affs))
    return out


def _extract_mesh_drugs(article: etree._Element) -> list[DrugPayload]:
    drugs: list[DrugPayload] = []
    seen: set[str] = set()
    for mh in article.findall(".//MeshHeadingList/MeshHeading"):
        desc = mh.find("DescriptorName")
        if desc is None:
            continue
        term = _text(desc)
        if not term:
            continue
        qualifiers = mh.findall("QualifierName")
        uis = {q.get("UI", "") for q in qualifiers}
        hit = bool(uis & DRUG_QUALIFIER_UIS) or is_drug_term(term)
        if not hit:
            continue
        # Skip MeSH drug-class headings ("Antineoplastic Agents", etc.) —
        # they add noise without adding a specific agent.
        if is_drug_class_heading(term):
            continue
        norm = normalize_drug(term)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        drugs.append(
            DrugPayload(
                drug_source_term=term, drug_normalized=norm, source_field="mesh"
            )
        )
    return drugs


def _author_matches(last_name: str, first_author: str) -> bool:
    if not last_name or not first_author:
        return False
    return last_name.lower() in first_author.lower()


def _paper_belongs_to_hcp(
    article: etree._Element,
    *,
    target_last_name: str,
    target_first_name: str,
    target_city: str | None,
    target_state: str | None,
    target_hospital: str | None,
) -> bool:
    """Decide whether THIS paper actually belongs to the target HCP.

    PubMed's `Last J[Author]` query returns every author whose last name and
    first initial match — so e.g. searching for John Shen returns papers by
    Jianxing Shen, Jingshan Shen, etc. We need to confirm one of the paper's
    authors is in fact our HCP.

    Match rule (any one suffices):
      1. ForeName matches target_first_name exactly (case-insensitive). When
         PubMed records a full forename ("John") and we have one too ("John"),
         this is the strongest disambiguator.
      2. Last name + first initial match AND at least one of that author's
         affiliations matches HCP city/state/hospital. Used when forename is
         missing or only the initial is recorded.
    """
    from hcp_intel.drug_normalize import affiliation_matches

    last_lc = target_last_name.lower().strip()
    first_lc = target_first_name.lower().strip()
    initial = first_lc[:1] if first_lc else ""
    if not last_lc:
        return False

    for last, fore, inits, affs in _author_full_names(article):
        if last.lower() != last_lc:
            continue

        # Rule 1: full forename match (strongest)
        if first_lc and fore and fore.lower() == first_lc:
            return True

        # Rule 2: initial match + affiliation overlap
        author_initial = (inits or fore[:1] or "").lower()
        if initial and author_initial == initial:
            for aff in affs:
                if affiliation_matches(aff, target_city, target_state, target_hospital):
                    return True
    return False


def parse_papers(
    xml_bytes: bytes,
    *,
    target_last_name: str = "",
    target_first_name: str = "",
    target_city: str | None = None,
    target_state: str | None = None,
    target_hospital: str | None = None,
    require_attribution: bool = False,
) -> list[PubMedPaper]:
    """Parse EFetch XML → structured papers.

    When require_attribution=True, drops papers that don't pass the HCP
    attribution check (see _paper_belongs_to_hcp). This is the production
    path; the older callers that just want to inspect candidates pass
    require_attribution=False and rely on downstream disambig logic.
    """
    if not xml_bytes:
        return []
    root = etree.fromstring(xml_bytes)
    out: list[PubMedPaper] = []
    for article in root.findall("PubmedArticle"):
        if require_attribution and not _paper_belongs_to_hcp(
            article,
            target_last_name=target_last_name,
            target_first_name=target_first_name,
            target_city=target_city,
            target_state=target_state,
            target_hospital=target_hospital,
        ):
            continue

        pmid = _text(article.find(".//PMID"))
        title = _text(article.find(".//Article/ArticleTitle"))
        journal = _text(article.find(".//Journal/Title")) or _text(
            article.find(".//Journal/ISOAbbreviation")
        )
        pub_date = _parse_pub_date(article)
        first_author, n_authors, affiliations = _extract_authors(article)
        abstract_parts = [
            _text(ab) for ab in article.findall(".//Abstract/AbstractText")
        ]
        abstract = "\n".join(p for p in abstract_parts if p) or None
        mesh_drugs = _extract_mesh_drugs(article)

        is_first = _author_matches(target_last_name, first_author)
        # Last author: inspect last Author node
        last_authors = article.findall(".//AuthorList/Author")
        last_author_display = ""
        if last_authors:
            la = last_authors[-1]
            last_author_display = (
                f"{_text(la.find('LastName'))} {_text(la.find('Initials'))}".strip()
            )
        is_last = _author_matches(target_last_name, last_author_display)

        out.append(
            PubMedPaper(
                pmid=pmid,
                title=title,
                journal=journal,
                pub_date=pub_date,
                first_author=first_author,
                authors_count=n_authors,
                affiliations=affiliations,
                mesh_drugs=mesh_drugs,
                abstract=abstract,
                is_first_author_match=is_first,
                is_last_author_match=is_last,
            )
        )
    return out


async def fetch_papers_for_hcp(
    first_name: str,
    last_name: str,
    *,
    since: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    city: str | None = None,
    state: str | None = None,
    hospital: str | None = None,
    strict: bool = False,
) -> list[PubMedPaper]:
    """Fetch papers authored by the HCP.

    When strict=True, results are post-filtered so only papers where one of
    the listed authors matches the HCP by full forename OR by last+initial
    plus an affiliation overlap (city/state/hospital) are returned. This
    fixes the cross-author bleed (Jianxing Shen ≠ John Shen) the previous
    `Last J[Author]` query produced.

    Strict mode also tightens the PubMed query itself: when we have a real
    first name (not just an initial), we use the `[Full Author Name]` field
    which PubMed indexes for explicit forename matches.
    """
    last = last_name.strip()
    first = first_name.strip()
    initial = first[:1]

    if strict and len(first) >= 3:
        # PubMed's structured forename search.
        query = f'("{last} {first}"[Full Author Name] OR "{last}, {first}"[Full Author Name])'
    else:
        query = f"({last} {initial}[Author])"

    if since:
        query += f' AND ("{since.strftime("%Y/%m/%d")}"[PDat]:3000/12/31[PDat])'

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        pmids = await _esearch(client, query)
        if not pmids:
            return []
        xml = await _efetch(client, pmids)
        return parse_papers(
            xml,
            target_last_name=last,
            target_first_name=first,
            target_city=city,
            target_state=state,
            target_hospital=hospital,
            require_attribution=strict,
        )
    finally:
        if own_client:
            await client.aclose()


def paper_to_feed_item(paper: PubMedPaper) -> FeedItemPayload:
    """Convert a parsed paper → FeedItemPayload for persistence."""
    raw: dict[str, Any] = {
        "pmid": paper.pmid,
        "journal": paper.journal,
        "first_author": paper.first_author,
        "authors_count": paper.authors_count,
        "affiliations": paper.affiliations,
        "mesh_drugs": [
            {"term": d.drug_source_term, "normalized": d.drug_normalized}
            for d in paper.mesh_drugs
        ],
        "abstract": paper.abstract,
        "is_first_author": paper.is_first_author_match,
        "is_last_author": paper.is_last_author_match,
    }
    return FeedItemPayload(
        external_id=paper.pmid,
        title=paper.title,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/",
        published_at=paper.pub_date,
        raw=raw,
    )


def extract_signals(item: FeedItemPayload) -> list[SignalPayload]:
    """Turn a persisted feed_item back into a publication signal."""
    raw = item.raw or {}
    mesh = raw.get("mesh_drugs") or []
    drugs = [
        DrugPayload(
            drug_source_term=d["term"],
            drug_normalized=d["normalized"],
            source_field="mesh",
        )
        for d in mesh
        if d.get("normalized")
    ]
    entities = {
        "pmid": raw.get("pmid") or item.external_id,
        "journal": raw.get("journal"),
        "authors_count": raw.get("authors_count"),
        "is_first_author": bool(raw.get("is_first_author")),
        "is_last_author": bool(raw.get("is_last_author")),
        "abstract": raw.get("abstract"),
    }
    if item.published_at is None:
        return []
    return [
        SignalPayload(
            signal_type="publication",
            observed_at=item.published_at,
            title=item.title,
            url=item.url,
            summary=raw.get("journal") or None,
            entities=entities,
            drugs=drugs,
        )
    ]
