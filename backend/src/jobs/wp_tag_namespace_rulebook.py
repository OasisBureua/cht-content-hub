"""Common-sense WP tag → namespaced tag mapping rules (WPR-11).

Deterministic pattern-matching rulebook that projects a flat WordPress tag
slug onto a namespaced tag. Runs at seed time (bulk-populate
`wp_tag_namespace_map` from the current `wordpress_tags` inventory) AND at
ingest time (as the fallback path when a new WP tag arrives that hasn't
been mapped yet).

Design principle: prefer under-classification (leave to `wp:*` fallback)
over misclassification. A tag falsely classified as `biomarker:*` pollutes
biomarker filter surfaces; a tag left as `wp:her2-therapy` still surfaces
somewhere useful and can be promoted later.

Rules are ordered — the first matching rule wins. Ordering is oncology-
domain-informed (biomarker > drug > trial > conference), based on the
observed WordPress editorial patterns on communityhealth.media.

## Extending the rulebook

To add a new pattern: append to `_RULES`. Each rule is a `(matcher, apply)`
pair. Matchers can be:
  - a string (exact match against slug), or
  - a compiled regex (search anywhere in slug), or
  - a callable that takes the slug and returns a bool.
`apply` returns `(namespace, canonical_value)` or `None` to skip.

## Case handling

WP slugs are lowercase; canonical values preserve editorial casing
(HER2+, T-DXd, DESTINY-Breast-09). The `apply` function is where the
lowercase→display transformation happens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


NAMESPACE_BIOMARKER = "biomarker"
NAMESPACE_DRUG = "drug"
NAMESPACE_TRIAL = "trial"
NAMESPACE_CONFERENCE = "conference"
NAMESPACE_STAGE = "stage"
NAMESPACE_TOPIC = "topic"

_KNOWN_NAMESPACES = frozenset(
    {
        NAMESPACE_BIOMARKER,
        NAMESPACE_DRUG,
        NAMESPACE_TRIAL,
        NAMESPACE_CONFERENCE,
        NAMESPACE_STAGE,
        NAMESPACE_TOPIC,
    }
)


@dataclass(frozen=True)
class TagMapping:
    """One classification result — namespace + canonical value + source label."""

    namespace: str
    value: str
    source: str  # 'rule:<rule_name>' | 'wp_fallback'


# ─────────────────────────────────────────────────────────────────────────────
# Rules
# ─────────────────────────────────────────────────────────────────────────────
#
# Ordered by domain-informed specificity. First match wins.
#
# Each entry is a tuple: (rule_name, matcher, applier). The matcher can be
# a callable or a compiled regex; the applier receives the slug and returns
# (namespace, value) or None.


# --- Biomarkers ---
_BIOMARKER_EXACT: dict[str, str] = {
    "her2": "HER2+",
    "her2-positive": "HER2+",
    "her2-low": "HER2-low",
    "her2-ultra-low": "HER2-ultra-low",
    "her2-zero": "HER2-zero",
    "her2-negative": "HER2-negative",
    "hr": "HR+",
    "hr-positive": "HR+",
    "hr-negative": "HR-",
    "esr1": "ESR1",
    "pik3ca": "PIK3CA",
    "brca1": "BRCA1",
    "brca2": "BRCA2",
    "brca": "BRCA",
    "pd-l1": "PD-L1",
    "tnbc": "TNBC",
    "triple-negative": "TNBC",
    "akt": "AKT",
    "pten": "PTEN",
    "kras": "KRAS",
    "egfr": "EGFR",
    "alk": "ALK",
    "ros1": "ROS1",
    "ntrk": "NTRK",
    "msi": "MSI",
    "msi-high": "MSI-high",
    "dmmr": "dMMR",
    "tmb": "TMB",
    "hrd": "HRD",
}


# --- Drugs (brand + generic) ---
_DRUG_EXACT: dict[str, str] = {
    # ADCs
    "t-dxd": "T-DXd",
    "trastuzumab-deruxtecan": "T-DXd",
    "enhertu": "Enhertu",
    "sg": "sacituzumab-govitecan",
    "sacituzumab-govitecan": "Sacituzumab-Govitecan",
    "trodelvy": "Trodelvy",
    "datopotamab": "Datopotamab-DXd",
    "dato-dxd": "Dato-DXd",
    # HER2 mAbs
    "trastuzumab": "Trastuzumab",
    "herceptin": "Herceptin",
    "pertuzumab": "Pertuzumab",
    "perjeta": "Perjeta",
    "tucatinib": "Tucatinib",
    "tukysa": "Tukysa",
    "neratinib": "Neratinib",
    "nerlynx": "Nerlynx",
    "margetuximab": "Margetuximab",
    "margenza": "Margenza",
    # Endocrine
    "tamoxifen": "Tamoxifen",
    "letrozole": "Letrozole",
    "anastrozole": "Anastrozole",
    "exemestane": "Exemestane",
    "fulvestrant": "Fulvestrant",
    "faslodex": "Faslodex",
    "elacestrant": "Elacestrant",
    "orserdu": "Orserdu",
    "camizestrant": "Camizestrant",
    # CDK4/6
    "palbociclib": "Palbociclib",
    "ibrance": "Ibrance",
    "ribociclib": "Ribociclib",
    "kisqali": "Kisqali",
    "abemaciclib": "Abemaciclib",
    "verzenio": "Verzenio",
    # PI3K/AKT
    "alpelisib": "Alpelisib",
    "piqray": "Piqray",
    "capivasertib": "Capivasertib",
    "truqap": "Truqap",
    "inavolisib": "Inavolisib",
    "itovebi": "Itovebi",
    # Checkpoint
    "pembrolizumab": "Pembrolizumab",
    "keytruda": "Keytruda",
    "atezolizumab": "Atezolizumab",
    "tecentriq": "Tecentriq",
    # PARP
    "olaparib": "Olaparib",
    "lynparza": "Lynparza",
    "talazoparib": "Talazoparib",
    "talzenna": "Talzenna",
}


# --- Conferences ---
_CONFERENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ASCO (annual + specialty)
    (re.compile(r"^asco(\d{2,4}|-annual|-\d+)?$"), "ASCO"),
    (re.compile(r"^asco-gu(\d{2,4})?$"), "ASCO-GU"),
    (re.compile(r"^asco-gi(\d{2,4})?$"), "ASCO-GI"),
    # ESMO
    (re.compile(r"^esmo(\d{2,4}|-annual|-\d+)?$"), "ESMO"),
    (re.compile(r"^esmo-breast(\d{2,4})?$"), "ESMO-Breast"),
    # SABCS (San Antonio Breast Cancer Symposium)
    (re.compile(r"^sabcs(\d{2,4}|-annual)?$"), "SABCS"),
    (re.compile(r"^san-antonio(\d{2,4})?$"), "SABCS"),
    # AACR
    (re.compile(r"^aacr(\d{2,4})?$"), "AACR"),
    # ASH (hematology, sometimes referenced from BC content)
    (re.compile(r"^ash(\d{2,4})?$"), "ASH"),
]


# --- Trials — recognize by prefix/pattern rather than enumerate ---
_TRIAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"^destiny-(breast|lung|gastric|crc)-?\d*$"),
    re.compile(r"^serena-?\d+$"),
    re.compile(r"^keynote-?\d+$"),
    re.compile(r"^checkmate-?\d+$"),
    re.compile(r"^solar-?\d+$"),
    re.compile(r"^emerald-?\d+$"),
    re.compile(r"^tropion-(breast|lung)-?\d*$"),
    re.compile(r"^monarch(e|-\d+)$"),
    re.compile(r"^paloma-?\d+$"),
    re.compile(r"^monaleesa-?\d+$"),
    re.compile(r"^embrace$"),
    re.compile(r"^inavo\d+$"),
    re.compile(r"^olympia$"),
    re.compile(r"^olympiad$"),
    re.compile(r"^attain$"),
    re.compile(r"^capitello-?\d+$"),
    re.compile(r"^persevera$"),
]


# --- Stage / disease state ---
_STAGE_EXACT: dict[str, str] = {
    "mbc": "metastatic",
    "metastatic": "metastatic",
    "advanced": "advanced",
    "early-stage": "early-stage",
    "ebc": "early-stage",
    "high-risk": "high-risk",
    "high-risk-cns": "high-risk-cns",
    "adjuvant": "adjuvant",
    "neoadjuvant": "neoadjuvant",
    "post-neoadjuvant": "post-neoadjuvant",
    "recurrent": "recurrent",
    "de-novo-metastatic": "de-novo-metastatic",
}


# --- Rule application ---


def _apply_biomarker_rules(slug: str) -> TagMapping | None:
    if slug in _BIOMARKER_EXACT:
        return TagMapping(NAMESPACE_BIOMARKER, _BIOMARKER_EXACT[slug], "rule:biomarker_exact")
    return None


def _apply_drug_rules(slug: str) -> TagMapping | None:
    if slug in _DRUG_EXACT:
        return TagMapping(NAMESPACE_DRUG, _DRUG_EXACT[slug], "rule:drug_exact")
    return None


def _apply_trial_rules(slug: str) -> TagMapping | None:
    for pattern in _TRIAL_PATTERNS:
        if pattern.match(slug):
            # Preserve the slug's shape but uppercase the trial ID prefix.
            # e.g. destiny-breast-06 → DESTINY-Breast-06, serena-6 → SERENA-6
            return TagMapping(NAMESPACE_TRIAL, _trial_display_form(slug), "rule:trial_pattern")
    return None


def _apply_conference_rules(slug: str) -> TagMapping | None:
    for pattern, canonical in _CONFERENCE_PATTERNS:
        m = pattern.match(slug)
        if not m:
            continue
        # Preserve year if present in the slug.
        year_part = m.group(1) if m.lastindex else None
        if year_part and year_part.strip("-").isdigit():
            year = year_part.strip("-")
            return TagMapping(
                NAMESPACE_CONFERENCE,
                f"{canonical}-{year}",
                "rule:conference_pattern",
            )
        return TagMapping(NAMESPACE_CONFERENCE, canonical, "rule:conference_pattern")
    return None


def _apply_stage_rules(slug: str) -> TagMapping | None:
    if slug in _STAGE_EXACT:
        return TagMapping(NAMESPACE_STAGE, _STAGE_EXACT[slug], "rule:stage_exact")
    return None


def _trial_display_form(slug: str) -> str:
    """Convert a lowercase trial slug into its editorial display form.

    Rules:
      - Split on `-`.
      - Uppercase the first token (the trial family name: DESTINY, SERENA, etc.).
      - Capitalize meaningful mid-tokens (Breast, Lung, etc.) — heuristic: any
        token that's not purely numeric.
      - Keep purely numeric tokens as-is (numbering).
    """
    parts = slug.split("-")
    out: list[str] = []
    for i, p in enumerate(parts):
        if not p:
            continue
        if p.isdigit():
            out.append(p)
        elif i == 0:
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    return "-".join(out)


# Rule pipeline — first match wins.
_RULE_PIPELINE: list[Callable[[str], TagMapping | None]] = [
    _apply_biomarker_rules,
    _apply_drug_rules,
    _apply_trial_rules,
    _apply_conference_rules,
    _apply_stage_rules,
]


def classify_wp_tag(slug: str) -> TagMapping | None:
    """Run the rulebook against a single WP tag slug.

    Returns a TagMapping if any rule matches, else None (caller should
    fall back to `wp:<slug>`).
    """
    if not slug:
        return None
    slug = slug.strip().lower()
    for rule in _RULE_PIPELINE:
        result = rule(slug)
        if result is not None:
            return result
    return None


def classify_batch(slugs: list[str]) -> dict[str, TagMapping]:
    """Classify many slugs at once. Returns only the ones that matched a rule.

    Unmapped slugs are simply absent from the returned dict — the caller
    handles the `wp:*` fallback.
    """
    out: dict[str, TagMapping] = {}
    for slug in slugs:
        result = classify_wp_tag(slug)
        if result is not None:
            out[slug] = result
    return out
