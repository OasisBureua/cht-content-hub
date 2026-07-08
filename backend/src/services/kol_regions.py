"""Canonical region taxonomy for /kol-network.

Both the Content Hub CMS editor (region picker) and the public KOL API
(GET /api/public/kols) read from this single list.
"""
from typing import TypedDict


class Region(TypedDict):
    slug: str
    label: str


REGIONS: list[Region] = [
    {"slug": "ny-northeast", "label": "New York & Northeast"},
    {"slug": "new-england", "label": "New England"},
    {"slug": "east-coast", "label": "East Coast Academic Centers"},
    {"slug": "florida", "label": "Florida"},
    {"slug": "midwest-chicago", "label": "Midwest — Chicago"},
    {"slug": "midwest-indiana", "label": "Midwest — Indiana"},
    {"slug": "missouri", "label": "Missouri"},
    {"slug": "kansas", "label": "Kansas"},
    {"slug": "tennessee", "label": "Tennessee"},
    {"slug": "texas", "label": "Texas"},
    {"slug": "colorado", "label": "Colorado"},
    {"slug": "pacific-northwest", "label": "Pacific Northwest"},
    {"slug": "california", "label": "California"},
]

REGIONS_BY_SLUG: dict[str, Region] = {r["slug"]: r for r in REGIONS}


def label_for(slug: str | None) -> str | None:
    """Return the canonical label for a region slug, or None if not found."""
    if not slug:
        return None
    r = REGIONS_BY_SLUG.get(slug)
    return r["label"] if r else None


# Institution → region inference table for the one-time backfill of existing
# KOLs. Keys are exact-match institution names; mapping is conservative —
# anything not in this table is left null for manual assignment in the CMS.
#
# Built from existing KOL data plus common oncology centers.
# expected to appear over the next 6 months. Extend liberally — false
# positives are not really a risk here since regions are publicly editable.
INSTITUTION_REGION_INFERENCES: dict[str, str] = {
    # New York & Northeast
    "Memorial Sloan Kettering": "ny-northeast",
    "Memorial Sloan Kettering Cancer Center": "ny-northeast",
    "MSK": "ny-northeast",
    "Weill Cornell Medicine": "ny-northeast",
    "Weill Cornell": "ny-northeast",
    "Columbia University Irving Medical Center": "ny-northeast",
    "Mount Sinai": "ny-northeast",
    "Icahn School of Medicine at Mount Sinai": "ny-northeast",
    "NYU Langone": "ny-northeast",
    "NYU Langone Health": "ny-northeast",
    # New England
    "Dana-Farber Cancer Institute": "new-england",
    "Dana-Farber": "new-england",
    "Dana Farber Cancer Institute": "new-england",
    "Dana Farber": "new-england",
    "Massachusetts General Hospital": "new-england",
    "Mass General": "new-england",
    "Brigham and Women's Hospital": "new-england",
    "Yale School of Medicine": "new-england",
    "Yale Cancer Center": "new-england",
    # East Coast Academic Centers
    "Johns Hopkins": "east-coast",
    "Johns Hopkins Medicine": "east-coast",
    "Johns Hopkins Sidney Kimmel Comprehensive Cancer Center": "east-coast",
    "University of Pennsylvania": "east-coast",
    "Penn Medicine": "east-coast",
    "Abramson Cancer Center": "east-coast",
    "Duke University": "east-coast",
    "Duke Cancer Institute": "east-coast",
    "UNC Lineberger": "east-coast",
    # Florida
    "Moffitt Cancer Center": "florida",
    "Moffitt": "florida",
    "Sylvester Comprehensive Cancer Center": "florida",
    "University of Miami": "florida",
    "Cancer Care Centers of Brevard": "florida",
    "Brevard": "florida",
    # Midwest — Chicago
    "Northwestern Medicine": "midwest-chicago",
    "Northwestern Medical Group": "midwest-chicago",
    "Northwestern University": "midwest-chicago",
    "Northwestern": "midwest-chicago",
    "Robert H. Lurie Comprehensive Cancer Center": "midwest-chicago",
    "University of Chicago": "midwest-chicago",
    "University of Chicago Medicine": "midwest-chicago",
    "Rush University": "midwest-chicago",
    "Rush University Medical Center": "midwest-chicago",
    "University of Illinois Cancer Center": "midwest-chicago",
    "University of Illinois": "midwest-chicago",
    # Midwest — Indiana
    "Indiana University Simon Cancer Center": "midwest-indiana",
    "Indiana University School of Medicine": "midwest-indiana",
    "IU Health": "midwest-indiana",
    "Hematology Oncology of Indiana": "midwest-indiana",
    "Indianapolis": "midwest-indiana",
    # Missouri
    "Washington University in St. Louis": "missouri",
    "Washington University School of Medicine": "missouri",
    "Siteman Cancer Center": "missouri",
    # Kansas
    "University of Kansas Cancer Center": "kansas",
    "KU Cancer Center": "kansas",
    # Tennessee
    "Vanderbilt University Medical Center": "tennessee",
    "Vanderbilt-Ingram Cancer Center": "tennessee",
    "Sarah Cannon Research Institute": "tennessee",
    "Sarah Cannon": "tennessee",
    "West Cancer Center": "tennessee",
    # Texas
    "MD Anderson": "texas",
    "Md Anderson": "texas",
    "MD Anderson Cancer Center": "texas",
    "The University of Texas MD Anderson Cancer Center": "texas",
    "Baylor College of Medicine": "texas",
    "Baylor Saint Lukes Medical Center": "texas",
    "Baylor Saint Lukes": "texas",
    "Texas Oncology": "texas",
    "Ut Southwestern Medical Center": "texas",
    "UT Southwestern": "texas",
    "Simmons Comprehensive Cancer Center": "texas",
    # Colorado
    "University of Colorado Cancer Center": "colorado",
    "UCHealth": "colorado",
    # Pacific Northwest
    "Fred Hutchinson Cancer Center": "pacific-northwest",
    "Fred Hutch": "pacific-northwest",
    "Seattle Cancer Care Alliance": "pacific-northwest",
    "Oregon Health & Science University": "pacific-northwest",
    "OHSU": "pacific-northwest",
    "Providence Portland Medical Center": "pacific-northwest",
    "Providence Portland": "pacific-northwest",
    # California
    "UCSF": "california",
    "UCSF Helen Diller Family Comprehensive Cancer Center": "california",
    "Stanford Medicine": "california",
    "Stanford Cancer Institute": "california",
    "Stanford Womens Cancer Center": "california",
    "Stanford": "california",
    "UCLA": "california",
    "UCLA Jonsson Comprehensive Cancer Center": "california",
    "University Of California Los Angeles": "california",
    "University of California Los Angeles": "california",
    "David Geffen School Of Medicine": "california",
    "David Geffen": "california",
    "City of Hope": "california",
    "USC Norris Comprehensive Cancer Center": "california",
}


def infer_region_from_institution(institution: str | None) -> str | None:
    """Best-effort region slug from a current-affiliation institution string.

    Returns None if the institution isn't in the inference table. The caller
    is expected to fall back to manual CMS assignment.
    """
    if not institution:
        return None
    # Exact match first
    if institution in INSTITUTION_REGION_INFERENCES:
        return INSTITUTION_REGION_INFERENCES[institution]
    # Substring match — e.g. "MSK Breast Service" should match "MSK"
    lowered = institution.lower()
    for key, slug in INSTITUTION_REGION_INFERENCES.items():
        if key.lower() in lowered:
            return slug
    return None
