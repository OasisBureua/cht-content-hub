"""Canonical doctor-surname typo corrections.

Extracted from legacy `services/post_tagger.py` — audit §5.2 flagged the
cross-service coupling (parser importing from post_tagger). Isolating the
corrections here so `playlist_title_parser` doesn't drag in the entire
post_tagger module on the producer stack.

When Marni (or any curator) types a doctor surname with a typo in a playlist
title, this map normalizes to the canonical spelling. Add new entries here as
new typo variants surface.
"""

from __future__ import annotations


DOCTOR_TAG_CORRECTIONS: dict[str, str] = {
    "Kree": "Krie",
    "Maklin": "Makhlin",
    "Cruz": "Kruse",
    "O'Shaughnessey": "O'Shaughnessy",
    "Odea": "O'Dea",
    "Garridocastro": "Garrido-Castro",
    "Garrido-castro": "Garrido-Castro",
}
