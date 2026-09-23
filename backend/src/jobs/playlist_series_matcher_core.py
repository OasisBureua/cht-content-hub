"""Fuzzy-match reusable core — YouTube playlist ↔ WordPress series scoring.

Reusable module (not a Lambda handler). Callable from:
  - sync/jobs/wordpress_series_playlist_match/handler.py (production Lambda)
  - backend/tests/test_playlist_series_matcher.py (unit tests)
  - admin endpoints if we ever want on-demand rescoring

## Scoring model (deterministic, no ML)

For each (YT playlist, WP series) pair we compute two signals:

  1. **Doctor overlap** — parse doctor surnames from the YT playlist title
     (using the existing playlist_title_parser) and from the WP series slug
     (which is normalized as `dr-<first>-<last>-and-dr-<first>-<last>` or
     `dr-<first>-<last>-dr-<first>-<last>`). Compute Jaccard similarity
     over the surname sets.

  2. **Title similarity** — SequenceMatcher ratio between normalized YT
     playlist title and normalized WP series name (case-folded, punctuation
     stripped, "drs./dr." prefixes removed to avoid biasing every pair).

  Combined score = 0.7 * doctor_overlap + 0.3 * title_similarity.
  Doctor overlap is weighted higher because it's the editorial intent —
  the whole point of series is to group doctor-pair episodes.

## Match thresholds

  - `MATCH_THRESHOLD = 0.5` — candidates at or above this score become
    pending review rows. Below is discarded (too noisy to review).
  - A **perfect doctor match** (Jaccard = 1.0 over ≥2 surnames on both
    sides) always makes the cut, even if title similarity is low — the
    editorial signal outweighs the string signal.

## Idempotency

The Lambda's job is to insert PENDING review rows for pairs above threshold.
Duplicates (same playlist_id + series_slug already pending) are skipped —
enforced by the composite unique index on playlist_series_match_review
(youtube_playlist_id, wp_series_slug, status).

Rows already in status='approved' or 'rejected' are also treated as decided:
the matcher does NOT re-propose pairs the curator has already ruled on.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

log = logging.getLogger(__name__)

MATCH_THRESHOLD: float = 0.5
DOCTOR_WEIGHT: float = 0.7
TITLE_WEIGHT: float = 0.3


@dataclass
class MatchCandidate:
    """One scored (playlist, series) pair with signals for the review row."""

    youtube_playlist_id: str
    wp_series_slug: str
    score: float
    doctor_overlap: float
    title_similarity: float
    yt_surnames: list[str]
    wp_surnames: list[str]
    yt_title: str
    wp_name: str

    def signals(self) -> dict:
        """Serializable blob for the review row's signals JSONB column."""
        return {
            "doctor_overlap": self.doctor_overlap,
            "title_similarity": self.title_similarity,
            "yt_surnames": self.yt_surnames,
            "wp_surnames": self.wp_surnames,
            "yt_title": self.yt_title,
            "wp_name": self.wp_name,
        }


# ─────────────────────────────────────────────────────────────────────────────
# WP series slug → surname extraction
# ─────────────────────────────────────────────────────────────────────────────

# WordPress slugs for doctor-pair series follow patterns like:
#   dr-neil-iyengar-dr-sara-hurvitz
#   dr-neil-iyengar-and-dr-sara-hurvitz
#   drs-iyengar-hurvitz
#   dr-mouabbi-dr-rao
# The parser walks tokens between "dr" markers and takes each block's
# last token as the surname. Robust to missing/present "and" connectors.

_DR_MARKER_RE = re.compile(r"^drs?$", re.IGNORECASE)
_STOP_TOKENS = frozenset({"and", "with", "featuring", "feat", "the"})


def extract_surnames_from_series_slug(slug: str) -> list[str]:
    """Return ordered de-duped surname list parsed from a WP series slug.

    Behavior:
    - Splits slug on `-`, walks tokens.
    - Requires at least one `dr`/`drs` marker to consider the slug a
      doctor pattern at all — topical slugs like `asco-2026-highlights`
      return empty.
    - Each `dr` marker starts a single-doctor block: block's final
      non-stopword token is the surname.
    - The `drs` (plural) marker signals a chained-surname block: every
      non-stopword token in the block is treated as a surname (handles
      slugs like `drs-iyengar-hurvitz`).
    - Numeric-only or single-char tokens are filtered out.
    """
    if not slug:
        return []
    tokens = [t for t in slug.lower().split("-") if t]
    if not tokens:
        return []

    # Require a dr/drs marker somewhere — reject topical slugs outright.
    if not any(_DR_MARKER_RE.match(t) for t in tokens):
        return []

    surnames: list[str] = []
    current_block: list[str] = []
    current_marker: str | None = None  # tracks whether last marker was 'dr' or 'drs'

    def _accept(candidate: str) -> None:
        if len(candidate) < 2 or candidate.isdigit():
            return
        if candidate not in surnames:
            surnames.append(candidate)

    def _commit_block() -> None:
        if not current_block:
            return
        block = [t for t in current_block if t not in _STOP_TOKENS]
        if not block:
            return
        if current_marker == "drs":
            # Plural marker: every remaining token in the block is a surname.
            for candidate in block:
                _accept(candidate)
        else:
            # Singular marker: last token is the surname (first + middle names precede).
            _accept(block[-1])

    for tok in tokens:
        if _DR_MARKER_RE.match(tok):
            _commit_block()
            current_marker = tok
            current_block = []
            continue
        current_block.append(tok)
    _commit_block()

    return surnames


# ─────────────────────────────────────────────────────────────────────────────
# Title normalization
# ─────────────────────────────────────────────────────────────────────────────

_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9\s]+")
_TITLE_DR_PREFIX_RE = re.compile(r"\bdrs?\.?\s+", re.IGNORECASE)


def _normalize_title(text: str) -> str:
    """Case-fold, drop punctuation, drop dr/drs prefixes, collapse whitespace."""
    if not text:
        return ""
    text = _TITLE_DR_PREFIX_RE.sub("", text)
    text = text.lower()
    text = _TITLE_NORMALIZE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_pair(
    *,
    youtube_playlist_id: str,
    yt_title: str,
    yt_surnames: list[str],
    wp_series_slug: str,
    wp_name: str,
    wp_surnames: list[str],
) -> MatchCandidate:
    """Score one (playlist, series) pair. Pure function, deterministic."""
    yt_set = set(yt_surnames)
    wp_set = set(wp_surnames)
    doctor_overlap = _jaccard(yt_set, wp_set)

    title_similarity = SequenceMatcher(
        None, _normalize_title(yt_title), _normalize_title(wp_name)
    ).ratio()

    score = DOCTOR_WEIGHT * doctor_overlap + TITLE_WEIGHT * title_similarity

    # Editorial-intent override: a perfect doctor overlap over ≥2 surnames
    # on both sides is a near-certain match, even if the title similarity
    # is low (WP series names are terse, YT titles are verbose).
    if (
        doctor_overlap == 1.0
        and len(yt_set) >= 2
        and len(wp_set) >= 2
    ):
        score = max(score, 0.9)

    return MatchCandidate(
        youtube_playlist_id=youtube_playlist_id,
        wp_series_slug=wp_series_slug,
        score=score,
        doctor_overlap=doctor_overlap,
        title_similarity=title_similarity,
        yt_surnames=yt_surnames,
        wp_surnames=wp_surnames,
        yt_title=yt_title,
        wp_name=wp_name,
    )


def score_all_pairs(
    playlists: list[dict],
    series: list[dict],
    *,
    threshold: float = MATCH_THRESHOLD,
) -> list[MatchCandidate]:
    """Score every (playlist, series) pair; return only those at/above threshold.

    Inputs are plain dicts to keep this module independent of the ORM /
    Lambda-runtime concerns:
      - playlists: [{youtube_playlist_id, title, surnames}, ...]
      - series:    [{slug, name, surnames}, ...]

    Returns candidates sorted by score descending — makes the review queue
    "highest confidence first" by default.
    """
    candidates: list[MatchCandidate] = []
    for p in playlists:
        for s in series:
            c = score_pair(
                youtube_playlist_id=p["youtube_playlist_id"],
                yt_title=p.get("title", ""),
                yt_surnames=p.get("surnames", []),
                wp_series_slug=s["slug"],
                wp_name=s.get("name", ""),
                wp_surnames=s.get("surnames", []),
            )
            if c.score >= threshold:
                candidates.append(c)
    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates
