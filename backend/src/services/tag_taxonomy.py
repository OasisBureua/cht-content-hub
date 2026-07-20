"""Canonical tag taxonomy + validator (SCRUM-73).

Every tag on Clip.tags / Post.tags / PlaylistTag.tags belongs to one of six
namespaces: biomarker, drug, trial, doctor, conference, topic. Anything
outside these six is rejected on write (with a reason).

Within each namespace:
  - values are lowercased on write (except doctor:, which is Title-cased on
    the surname to match the parser output and CHM curator convention);
  - known typo variants are corrected via per-namespace correction dicts;
  - namespace-specific value shape is enforced (e.g. drug: is kebab-case,
    trial: is `NCT[0-9]+`);
  - duplicates within a tag set are deduped, preserving first-seen order.

The tagger + admin write APIs (SCRUM-74/75) call `normalize_tags(tags)` or
`normalize_and_validate_tags(tags)` before persisting to enforce these
invariants at every write site. Read-side already trusts stored tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.doctor_tag_corrections import DOCTOR_TAG_CORRECTIONS

# The six canonical namespaces. Add here (and to _NAMESPACE_VALIDATORS) if
# ever extending — never accept a namespace that isn't in this set.
CANONICAL_NAMESPACES: frozenset[str] = frozenset(
    {"biomarker", "drug", "trial", "doctor", "conference", "topic"}
)

# Per-namespace typo/alias corrections. Values are looked up post-normalize
# (so lookups are case-consistent). Extend as new variants surface.
BIOMARKER_CORRECTIONS: dict[str, str] = {
    "her2low": "her2-low",
    "her2-ultralow": "her2-ultra-low",
    "her2ultralow": "her2-ultra-low",
    "tripleneg": "triple-negative",
    "tnbc": "triple-negative",
    "hrpos": "hr-positive",
    "hrneg": "hr-negative",
}

DRUG_CORRECTIONS: dict[str, str] = {
    "t-dxd": "t-dxd",
    "trastuzumab-deruxtecan": "t-dxd",
    "enhertu": "t-dxd",
    "sacituzumab-govitecan": "sg",
    "trodelvy": "sg",
    "capivasertib": "truqap",
}

TRIAL_CORRECTIONS: dict[str, str] = {
    # Placeholder — trial IDs are already canonical (NCT-numbered).
}

CONFERENCE_CORRECTIONS: dict[str, str] = {
    "asco2026": "asco-2026",
    "sabcs2025": "sabcs-2025",
    "sabcs-25": "sabcs-2025",
    "esmo2026": "esmo-2026",
}

TOPIC_CORRECTIONS: dict[str, str] = {
    # Curator-facing — extend as topics drift.
}

_KEBAB_VALUE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRIAL_ID_RE = re.compile(r"^nct[0-9]{6,10}$")


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
    """Return `(namespace, value)` or None if the tag is malformed."""
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
    return "'".join(sub[:1].upper() + sub[1:].lower() if sub else sub for sub in segment.split("'"))


def _normalize_doctor(value: str) -> str:
    """doctor: values are Title-cased surname; hyphens and apostrophes
    are preserved as segment separators. Corrections applied post-normalize.
    """
    parts = value.strip().split("-")
    titled = "-".join(_title_segment(p) for p in parts)
    return DOCTOR_TAG_CORRECTIONS.get(titled, titled)


def _normalize_biomarker(value: str) -> str:
    v = value.strip().lower()
    return BIOMARKER_CORRECTIONS.get(v, v)


def _normalize_drug(value: str) -> str:
    v = value.strip().lower()
    return DRUG_CORRECTIONS.get(v, v)


def _normalize_trial(value: str) -> str:
    v = value.strip().lower()
    return TRIAL_CORRECTIONS.get(v, v)


def _normalize_conference(value: str) -> str:
    v = value.strip().lower()
    return CONFERENCE_CORRECTIONS.get(v, v)


def _normalize_topic(value: str) -> str:
    v = value.strip().lower()
    return TOPIC_CORRECTIONS.get(v, v)


def _validate_kebab(value: str) -> str | None:
    return None if _KEBAB_VALUE_RE.match(value) else "value must be lowercase kebab-case"


def _validate_trial(value: str) -> str | None:
    return None if _TRIAL_ID_RE.match(value) else "trial value must match NCT<digits>"


def _validate_doctor(value: str) -> str | None:
    if not value or not value[0].isalpha():
        return "doctor value must start with a letter"
    return None


_NAMESPACE_NORMALIZERS = {
    "biomarker": _normalize_biomarker,
    "drug": _normalize_drug,
    "trial": _normalize_trial,
    "doctor": _normalize_doctor,
    "conference": _normalize_conference,
    "topic": _normalize_topic,
}

_NAMESPACE_VALIDATORS = {
    "biomarker": _validate_kebab,
    "drug": _validate_kebab,
    "trial": _validate_trial,
    "doctor": _validate_doctor,
    "conference": _validate_kebab,
    "topic": _validate_kebab,
}


def normalize_and_validate_tags(tags: list[str] | None) -> TagValidationResult:
    """Canonicalize a tag list.

    Rejects tags whose namespace isn't in CANONICAL_NAMESPACES, or whose
    value fails the per-namespace shape check. Applies typo corrections.
    Dedupes on the normalized form, preserving first-seen order.

    Used by admin write APIs to give the curator a clear "these tags were
    rejected because…" error path. The tagger's daily loop uses the
    tolerant `normalize_tags()` instead.
    """
    result = TagValidationResult()
    seen: set[str] = set()

    for original in list(tags or []):
        parts = _split_namespace(original)
        if parts is None:
            result.rejected.append((original, "not namespaced (expected 'namespace:value')"))
            continue
        ns, value = parts
        if ns not in CANONICAL_NAMESPACES:
            result.rejected.append((original, f"unknown namespace '{ns}'"))
            continue
        normalized_value = _NAMESPACE_NORMALIZERS[ns](value)
        error = _NAMESPACE_VALIDATORS[ns](normalized_value)
        if error:
            result.rejected.append((original, error))
            continue
        canonical = f"{ns}:{normalized_value}"
        if canonical in seen:
            continue
        seen.add(canonical)
        result.normalized.append(canonical)

    return result


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Tolerant normalizer: apply corrections + dedupe, but silently drop
    malformed/unknown-namespace tags instead of erroring.

    Used by the tagger's daily loop so a legacy row with one bad tag
    doesn't block the whole shoot's propagation. Admin-write paths call
    `normalize_and_validate_tags()` to surface rejects to the user.
    """
    return normalize_and_validate_tags(tags).normalized
