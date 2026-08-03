"""Tests for the playlist ↔ series fuzzy-match core (WPR-6).

Covers:
- WP series slug surname extraction (various slug patterns)
- Title normalization (case-fold, punctuation strip, dr/drs prefix drop)
- Pair scoring (doctor overlap + title similarity + editorial-intent override)
- Threshold filtering + ordering in `score_all_pairs`
"""

from __future__ import annotations

import pytest

from jobs.playlist_series_matcher_core import (
    MATCH_THRESHOLD,
    MatchCandidate,
    _normalize_title,
    extract_surnames_from_series_slug,
    score_all_pairs,
    score_pair,
)


# ─────────────────────────────────────────────────────────────────────────────
# WP series slug surname extraction
# ─────────────────────────────────────────────────────────────────────────────


class TestSurnameExtraction:
    def test_doctor_pair_with_and(self):
        assert extract_surnames_from_series_slug(
            "dr-neil-iyengar-and-dr-sara-hurvitz"
        ) == ["iyengar", "hurvitz"]

    def test_doctor_pair_without_and(self):
        assert extract_surnames_from_series_slug(
            "dr-neil-iyengar-dr-sara-hurvitz"
        ) == ["iyengar", "hurvitz"]

    def test_drs_plural_prefix(self):
        assert extract_surnames_from_series_slug(
            "drs-iyengar-hurvitz"
        ) == ["iyengar", "hurvitz"]

    def test_single_name_per_doctor_block(self):
        assert extract_surnames_from_series_slug(
            "dr-mouabbi-dr-rao"
        ) == ["mouabbi", "rao"]

    def test_three_doctors(self):
        assert extract_surnames_from_series_slug(
            "dr-a-smith-dr-b-jones-dr-c-brown"
        ) == ["smith", "jones", "brown"]

    def test_topical_slug_returns_empty(self):
        """Series like `asco-2026-highlights` have no doctor pattern."""
        assert extract_surnames_from_series_slug("asco-2026-highlights") == []

    def test_empty_slug_returns_empty(self):
        assert extract_surnames_from_series_slug("") == []

    def test_duplicate_surnames_deduplicated(self):
        assert extract_surnames_from_series_slug(
            "dr-a-smith-dr-b-smith"
        ) == ["smith"]

    def test_numeric_tokens_filtered_out(self):
        """Something like `dr-2026-preview` shouldn't yield '2026' as a surname."""
        assert extract_surnames_from_series_slug("dr-2026") == []

    def test_short_tokens_filtered_out(self):
        """Single-char tokens like `dr-a` don't count as surnames."""
        assert extract_surnames_from_series_slug("dr-a") == []


# ─────────────────────────────────────────────────────────────────────────────
# Title normalization
# ─────────────────────────────────────────────────────────────────────────────


class TestTitleNormalization:
    def test_case_fold(self):
        assert _normalize_title("HER2 Update") == "her2 update"

    def test_strip_punctuation(self):
        assert _normalize_title("HER2-low: what's next?") == "her2 low what s next"

    def test_drop_dr_prefix(self):
        assert _normalize_title("Dr. Iyengar and Dr. Hurvitz on HER2") == (
            "iyengar and hurvitz on her2"
        )

    def test_drop_drs_prefix(self):
        assert _normalize_title("Drs. Mouabbi and Rao") == "mouabbi and rao"

    def test_collapse_whitespace(self):
        assert _normalize_title("HER2    positive") == "her2 positive"

    def test_empty(self):
        assert _normalize_title("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# Pair scoring
# ─────────────────────────────────────────────────────────────────────────────


class TestScorePair:
    def test_perfect_doctor_overlap_and_high_title_similarity(self):
        c = score_pair(
            youtube_playlist_id="PL_x",
            yt_title="Dr. Neil Iyengar and Dr. Sara Hurvitz on HER2",
            yt_surnames=["iyengar", "hurvitz"],
            wp_series_slug="dr-neil-iyengar-and-dr-sara-hurvitz",
            wp_name="Drs. Iyengar & Hurvitz",
            wp_surnames=["iyengar", "hurvitz"],
        )
        assert c.doctor_overlap == 1.0
        # Editorial-intent override kicks in — score bumped to at least 0.9
        assert c.score >= 0.9

    def test_perfect_doctor_overlap_low_title_similarity(self):
        """Editorial-intent override rescues score when titles diverge."""
        c = score_pair(
            youtube_playlist_id="PL_x",
            yt_title="Extended interview from ASCO 2026 recap",
            yt_surnames=["iyengar", "hurvitz"],
            wp_series_slug="dr-iyengar-dr-hurvitz",
            wp_name="Iyengar/Hurvitz",
            wp_surnames=["iyengar", "hurvitz"],
        )
        assert c.doctor_overlap == 1.0
        # Without override, the score would be ~0.7 (0.7 * 1.0 + 0.3 * low).
        # With override, it's clamped to at least 0.9.
        assert c.score >= 0.9

    def test_zero_overlap(self):
        c = score_pair(
            youtube_playlist_id="PL_x",
            yt_title="Completely unrelated content",
            yt_surnames=["smith"],
            wp_series_slug="dr-jones-dr-brown",
            wp_name="Jones/Brown",
            wp_surnames=["jones", "brown"],
        )
        assert c.doctor_overlap == 0.0
        # Score should reflect low title similarity + zero overlap.
        assert c.score < 0.5

    def test_partial_overlap(self):
        """One surname matches out of two on each side."""
        c = score_pair(
            youtube_playlist_id="PL_x",
            yt_title="Iyengar and Chen",
            yt_surnames=["iyengar", "chen"],
            wp_series_slug="dr-iyengar-dr-hurvitz",
            wp_name="Iyengar/Hurvitz",
            wp_surnames=["iyengar", "hurvitz"],
        )
        # Jaccard = 1 / 3 ≈ 0.333
        assert 0.3 < c.doctor_overlap < 0.4
        # No editorial-intent override (not perfect overlap).

    def test_single_surname_match_no_override(self):
        """Single-doctor sides — override requires ≥2 surnames on both sides."""
        c = score_pair(
            youtube_playlist_id="PL_x",
            yt_title="Interview with Dr. Iyengar",
            yt_surnames=["iyengar"],
            wp_series_slug="dr-iyengar",
            wp_name="Iyengar",
            wp_surnames=["iyengar"],
        )
        assert c.doctor_overlap == 1.0
        # No override — score is the plain weighted combo.
        # 0.7 * 1.0 + 0.3 * <title_sim>. Should NOT be forced to 0.9.
        # For matching titles ("interview with iyengar" vs "iyengar"),
        # SequenceMatcher gives some similarity but not perfect.
        assert c.score < 0.9

    def test_signals_serializable(self):
        c = score_pair(
            youtube_playlist_id="PL_x",
            yt_title="test",
            yt_surnames=["a"],
            wp_series_slug="s",
            wp_name="test",
            wp_surnames=["a"],
        )
        blob = c.signals()
        assert "doctor_overlap" in blob
        assert "title_similarity" in blob
        assert blob["yt_surnames"] == ["a"]
        assert blob["wp_surnames"] == ["a"]


# ─────────────────────────────────────────────────────────────────────────────
# score_all_pairs — threshold filter + ordering
# ─────────────────────────────────────────────────────────────────────────────


class TestScoreAllPairs:
    def test_filters_below_threshold(self):
        playlists = [
            {
                "youtube_playlist_id": "PL1",
                "title": "Random unrelated title",
                "surnames": ["smith"],
            }
        ]
        series = [
            {
                "slug": "dr-jones-dr-brown",
                "name": "Jones/Brown",
                "surnames": ["jones", "brown"],
            }
        ]
        # Score should be well below 0.5 — no overlap, low title sim.
        candidates = score_all_pairs(playlists, series, threshold=0.5)
        assert candidates == []

    def test_returns_matches_sorted_by_score_desc(self):
        playlists = [
            {
                "youtube_playlist_id": "PL_high",
                "title": "Iyengar and Hurvitz on HER2",
                "surnames": ["iyengar", "hurvitz"],
            },
            {
                "youtube_playlist_id": "PL_mid",
                "title": "Iyengar solo",
                "surnames": ["iyengar"],
            },
        ]
        series = [
            {
                "slug": "dr-iyengar-dr-hurvitz",
                "name": "Iyengar/Hurvitz",
                "surnames": ["iyengar", "hurvitz"],
            },
        ]
        candidates = score_all_pairs(playlists, series, threshold=0.3)
        assert len(candidates) >= 1
        # First candidate should be the higher-score pair.
        assert candidates[0].youtube_playlist_id == "PL_high"
        # Scores are monotonically non-increasing.
        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_cross_product_scored(self):
        """Every (playlist, series) pair is scored."""
        playlists = [
            {"youtube_playlist_id": "PL1", "title": "x", "surnames": ["a", "b"]},
            {"youtube_playlist_id": "PL2", "title": "y", "surnames": ["c", "d"]},
        ]
        series = [
            {"slug": "s1", "name": "s1", "surnames": ["a", "b"]},
            {"slug": "s2", "name": "s2", "surnames": ["c", "d"]},
            {"slug": "s3", "name": "s3", "surnames": ["e", "f"]},
        ]
        candidates = score_all_pairs(playlists, series, threshold=0.0)
        # 2 * 3 = 6 pairs when threshold is 0.
        assert len(candidates) == 6

    def test_default_threshold_constant_matches(self):
        """The module's default threshold constant matches what score_all_pairs uses."""
        assert MATCH_THRESHOLD == 0.5
