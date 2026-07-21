"""Namespaced tag taxonomy + validator (SCRUM-73, revised 2026-07-21).

Every tag on Clip.tags / Post.tags / PlaylistTag.tags is `namespace:value`.
Recognized namespaces:

  Source-of-truth (editorial + curator):
  - `biomarker` — biomarkers (HER2+, HER2-low, HR+, triple-negative, etc.)
  - `drug`      — brand or generic drug name (T-DXd, Enhertu, sacituzumab)
  - `trial`     — clinical trial ID or nickname (DESTINY-Breast09, NCT01234)
  - `doctor`    — canonical surname (Traina, Pegram, O'Shaughnessy)
  - `conference`— conference tag (ASCO 2026, SABCS 2025)
  - `topic`     — free-form topical bucket (metastatic breast cancer, CNS)
  - `stage`     — disease stage (mBC, EBC, resectable)

  Ingested-from-editorial (distinguish source in the DB):
  - `wp`        — WordPress **tag** slug (from wordpress_events.tags)
  - `yt`        — YouTube video snippet.tag (from YouTube Data API)

  Curator/system:
  - `other`     — catch-all for imported tags that don't fit any namespace

## Design choice: freeform values

Values are **freeform strings** after normalization. We do NOT enforce
kebab-case, because:

  1. Existing seed data uses freeform (`biomarker:HER2+`, `drug:T-DXd`,
     `topic:metastatic breast cancer`, `stage:mBC`).
  2. Ingested tags from WP + YouTube are curator-controlled on external
     surfaces (WP admin, YouTube studio) — they can legitimately contain
     spaces, mixed case, `+`, `/`, and other punctuation.
  3. The value of this validator is namespace enforcement + typo
     correction + dedupe, NOT case-normalization for its own sake.

The doctor namespace is the one exception — surnames are Title-cased on
write to match the parser output and CHM curator convention (`Pegram`,
`O'Shaughnessy`), because doctor:* tags come from playlist_doctor_tagger
which produces canonical casing.

## Dedupe strategy

Two tags compare equal if their normalized forms are identical. Namespace
is always lowercased. Value is preserved as-is (whitespace trimmed) for
freeform namespaces. Doctor namespace normalizes to Title-case + typo
correction. Correction dicts collapse aliases (Enhertu → t-dxd) so
different curator inputs converge to one canonical string per concept.

## Entry points

- `normalize_and_validate_tags(tags)` — admin write path. Returns
  `TagValidationResult` with `.rejected` populated for per-tag reasons.
- `normalize_tags(tags)` — tolerant. Malformed tags dropped silently.
  Used by the tagger loop where one bad legacy row shouldn't block a
  whole shoot's propagation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.doctor_tag_corrections import DOCTOR_TAG_CORRECTIONS

# Every namespace we're willing to write to Clip.tags / Post.tags /
# PlaylistTag.tags. Anything else is rejected. Order not meaningful.
CANONICAL_NAMESPACES: frozenset[str] = frozenset(
    {
        # Editorial / curator semantic
        "biomarker",
        "drug",
        "trial",
        "doctor",
        "conference",
        "topic",
        "stage",
        # Ingested from external editorial surfaces
        "wp",
        "yt",
        # Catch-all
        "other",
    }
)

# Per-namespace typo/alias corrections. Applied after lowercasing the
# lookup key so `Enhertu`, `enhertu`, `ENHERTU` all collapse to `t-dxd`.
# Values are preserved verbatim in the output tag.
DRUG_CORRECTIONS: dict[str, str] = {
    "enhertu": "t-dxd",
    "trastuzumab-deruxtecan": "t-dxd",
    "trastuzumab deruxtecan": "t-dxd",
    "trodelvy": "sg",
    "sacituzumab-govitecan": "sg",
    "sacituzumab govitecan": "sg",
    "capivasertib": "truqap",
}

# Biomarker aliases — the DB has both `HER2+` and `HER2-positive`,
# `HER2-low` and `HER2low`. Collapse to a canonical spelling on write.
BIOMARKER_CORRECTIONS: dict[str, str] = {
    "her2low": "HER2-low",
    "her2 low": "HER2-low",
    "her2-ultralow": "HER2-ultralow",
    "her2 ultralow": "HER2-ultralow",
    "her2 ultra low": "HER2-ultralow",
    "her2 ultra-low": "HER2-ultralow",
    "tripleneg": "triple-negative",
    "triple neg": "triple-negative",
    "tnbc": "triple-negative",
    "hrpos": "HR+",
    "hr pos": "HR+",
    "hrneg": "HR-",
    "hr neg": "HR-",
}

CONFERENCE_CORRECTIONS: dict[str, str] = {
    "asco2026": "ASCO 2026",
    "asco-2026": "ASCO 2026",
    "sabcs2025": "SABCS 2025",
    "sabcs-25": "SABCS 2025",
    "sabcs-2025": "SABCS 2025",
    "esmo2026": "ESMO 2026",
    "esmo-2026": "ESMO 2026",
}

# topic/stage/trial/wp/yt/other — no corrections by default. Add as needed.


@dataclass
class TagValidationResult:
    """Outcome of validating a tag list.

    - normalized: tags kept + rewritten to canonical form, deduped in
      first-seen order
    - rejected: [(original_tag, reason)] for tags that failed validation
    """

    normalized: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


def _split_namespace(tag: str) -> tuple[str, str] | None:
    """Return `(namespace, value)` or None if malformed.

    Namespace is lowercased. Value is stripped but otherwise untouched.
    """
    if not isinstance(tag, str):
        return None
    stripped = tag.strip()
    if ":" not in stripped:
        return None
    ns, _, value = stripped.partition(":")
    ns = ns.strip().lower()
    value = value.strip()
    if not ns or not value:
        return None
    return ns, value


def _title_segment(segment: str) -> str:
    """Title-case a segment across apostrophes (`o'shaughnessy` → `O'Shaughnessy`)."""
    if not segment:
        return segment
    return "'".join(
        sub[:1].upper() + sub[1:].lower() if sub else sub
        for sub in segment.split("'")
    )


def _normalize_doctor(value: str) -> str:
    """doctor: surname is Title-cased; hyphens + apostrophes preserved.

    Typo corrections applied post-normalize so `Kree` → `Krie` regardless
    of curator casing.
    """
    parts = value.strip().split("-")
    titled = "-".join(_title_segment(p) for p in parts)
    return DOCTOR_TAG_CORRECTIONS.get(titled, titled)


def _normalize_via_alias_dict(value: str, corrections: dict[str, str]) -> str:
    """Freeform normalize: preserve casing, apply alias correction on lc lookup."""
    key = value.strip().lower()
    if key in corrections:
        return corrections[key]
    return value.strip()


_NAMESPACE_NORMALIZERS = {
    "doctor": _normalize_doctor,
    "biomarker": lambda v: _normalize_via_alias_dict(v, BIOMARKER_CORRECTIONS),
    "drug": lambda v: _normalize_via_alias_dict(v, DRUG_CORRECTIONS),
    "conference": lambda v: _normalize_via_alias_dict(v, CONFERENCE_CORRECTIONS),
    # Freeform (whitespace-strip only) — no alias dict wired yet.
    "trial": lambda v: v.strip(),
    "topic": lambda v: v.strip(),
    "stage": lambda v: v.strip(),
    "wp": lambda v: v.strip(),
    "yt": lambda v: v.strip(),
    "other": lambda v: v.strip(),
}


def _validate_value(value: str) -> str | None:
    """Reject only truly malformed values (empty, control chars, newlines).

    We accept spaces, mixed case, `+`, `/`, punctuation — those are all
    legitimate in freeform editorial tags.
    """
    if not value:
        return "value cannot be empty"
    if any(c in value for c in ("\n", "\r", "\t")):
        return "value cannot contain newlines or tabs"
    return None


def normalize_and_validate_tags(tags: list[str] | None) -> TagValidationResult:
    """Canonicalize a tag list.

    Rejects tags whose namespace isn't in CANONICAL_NAMESPACES, or whose
    value is empty / contains control chars. Applies typo corrections.
    Dedupes on the normalized form (case-insensitive on value), preserving
    first-seen order.

    Used by admin write APIs to give the curator a clear "these tags were
    rejected because…" error path.
    """
    result = TagValidationResult()
    seen: set[str] = set()

    for original in list(tags or []):
        parts = _split_namespace(original)
        if parts is None:
            result.rejected.append(
                (original, "not namespaced (expected 'namespace:value')")
            )
            continue
        ns, value = parts
        if ns not in CANONICAL_NAMESPACES:
            result.rejected.append((original, f"unknown namespace '{ns}'"))
            continue
        normalized_value = _NAMESPACE_NORMALIZERS[ns](value)
        error = _validate_value(normalized_value)
        if error:
            result.rejected.append((original, error))
            continue
        canonical = f"{ns}:{normalized_value}"
        # Case-insensitive dedupe key so `biomarker:HER2+` and
        # `biomarker:her2+` collapse to whichever came first.
        dedupe_key = f"{ns}:{normalized_value.lower()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.normalized.append(canonical)

    return result


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Tolerant normalizer: apply corrections + dedupe, silently drop malformed.

    Used by the tagger's daily loop so a legacy row with one bad tag
    doesn't block the whole shoot's propagation. Admin-write paths call
    `normalize_and_validate_tags()` to surface rejects to the user.
    """
    return normalize_and_validate_tags(tags).normalized
