"""Parse doctor names out of a CHM YouTube playlist title.

The CHM YouTube channel is the canonical source of truth for which doctors
participated in which shoot. Each curated playlist's title spells out the
doctors. This module distills those titles into a stable list of canonical
surnames that downstream code uses to tag every clip in the playlist.

Three real-world patterns we have to handle (sampled from the live channel):

  A) Full names, ampersand-joined:
       "Dr. Mark Pegram & Dr. Neil Iyengar"
       → ["Pegram", "Iyengar"]

  B) Surname-only chain after "Drs.":
       "Drs. Mouabbi, O'Shaughnessy & Rimawi Rethink First-Line..."
       → ["Mouabbi", "O'Shaughnessy", "Rimawi"]

  C) Full names in a chain after "Drs.":
       "Cleopatra, DESTINY-Breast09 & What Comes Next with Drs. Bill Gradishar,
        Tarah Ballinger, & Megan Kruse"
       → ["Gradishar", "Ballinger", "Kruse"]

  D) Doctors at the end after a topic prefix:
       "Is HER2+ MBC Curable? - Dr. Gregory Vidal & Dr. Nusayba Bagegni"
       → ["Vidal", "Bagegni"]

The output is the **canonical surname** for each doctor — with apostrophes
preserved (O'Shaughnessy, O'Dea), hyphens preserved (Garrido-Castro), and
typo corrections applied (Kree→Krie, Maklin→Makhlin, etc.) from the
DOCTOR_TAG_CORRECTIONS map in services.doctor_tag_corrections.

Pure function, no I/O. Easy to test.
"""

from __future__ import annotations

import re
from typing import Iterable

from services.doctor_tag_corrections import DOCTOR_TAG_CORRECTIONS


# Words that commonly follow "Drs. <name list>" and signal end-of-chain.
# Case-insensitive. Lower-case here; we add IGNORECASE on the regex.
_END_OF_CHAIN_WORDS = (
    "discussing",
    "discuss",
    "rethink",
    "explain",
    "examine",
    "exploring",
    "explore",
    "talking",
    "rewriting",
    "presenting",
    "present",
    "addresses",
    "address",
    "navigate",
    "discusses",
    "discussed",
    "are",
    "with",
    "from",
    "redefining",
    "leading",
    "review",
    "reviewing",
    "delivers",
    "rewrites",
)


def _normalize_quotes(text: str) -> str:
    """Map smart/curly punctuation to plain ASCII for stable regex matching."""
    return (
        text.replace("‘", "'")  # left single curly
        .replace("’", "'")  # right single curly
        .replace("“", '"')   # left double curly
        .replace("”", '"')   # right double curly
        .replace("–", "-")   # en-dash
        .replace("—", "-")   # em-dash
    )


# A doctor surname is one capitalized word, possibly with an internal
# apostrophe (O'Shaughnessy, O'Dea) or hyphen (Garrido-Castro).
# We allow the apostrophe / hyphen to appear right after the first capital
# (so "O'Dea" — only one letter, then apostrophe — still matches).
_SURNAME = r"[A-Z](?:[a-zA-Z'\-][a-zA-Z]*)+"

# A "human name" is one or two whitespace-separated tokens that start with
# uppercase. Handles "Mark Pegram", "VK Gadi", "Mark Robson", "V K Gadi",
# "Ana Garrido-Castro".
_HUMAN_NAME = rf"(?:[A-Z][a-zA-Z']*\.?\s+){{0,3}}{_SURNAME}"

# A surname-as-typed-in-title: same as _SURNAME but also accepts a lowercase
# first letter. Used ONLY when we're sure we're inside a doctor name (after
# "Dr." or as part of a "Drs. ..." chain) — never to seed a match. This
# tolerates real CHM titles with a typo like "Dr. Neil lyengar" (lowercase L).
_SURNAME_LOOSE = r"[A-Za-z](?:[a-zA-Z'\-][a-zA-Z]*)+"

# A "human name" that allows a lowercase-starting LAST token (the surname).
# Requires at least one capitalized prefix token to avoid matching random
# lowercase words; the relaxed surname is anchored at the end.
_HUMAN_NAME_LOOSE = rf"(?:[A-Z][a-zA-Z']*\.?\s+){{1,3}}{_SURNAME_LOOSE}"


# Pattern A: "Dr. <First> <Last>" or "Dr. <Last>" — one doctor at a time.
# Captures the FULL captured name; surname is the last whitespace token.
# Try loose first (greedy — extends through lowercase typos like "Dr. Neil
# lyengar"); _surname_from_full_name filters out stopword trailing tokens.
_RE_DOCTOR_NAME = re.compile(rf"\bDr\.\s+({_HUMAN_NAME_LOOSE}|{_HUMAN_NAME})")

# Stopwords that may trail a captured doctor name when the regex over-extends
# into "Dr. Erika Hamilton and Dr. ..." — strip these from the END of a
# captured name. Case-insensitive.
_TRAILING_STOPWORDS = frozenset(
    {
        "and",
        "with",
        "discuss",
        "discusses",
        "discussed",
        "discussing",
        "explain",
        "explains",
        "explaining",
        "explore",
        "explores",
        "exploring",
        "rethink",
        "rethinks",
        "rethinking",
        "review",
        "reviews",
        "reviewing",
        "talking",
        "talk",
        "talks",
        "presenting",
        "presents",
        "present",
        "rewriting",
        "rewrites",
        "rewrite",
        "discussing",
        "from",
        "are",
        "the",
        "a",
        "an",
        "to",
        "of",
        "in",
        "on",
        "at",
    }
)

# Pattern B/C: "Drs. <name>[, <name>[, ...]] [&|and] <name>"
# We anchor on "Drs." and stop at the first word from _END_OF_CHAIN_WORDS
# or at the end of the string. Inside the captured chunk we split on commas
# and "&"/"and".
_RE_DRS_CHAIN = re.compile(
    r"\bDrs\.\s+"
    r"((?:" + _HUMAN_NAME + r")"          # first name in chain
    r"(?:\s*,\s*(?:" + _HUMAN_NAME + r"))*"  # comma-separated middle
    r"(?:\s*(?:&|and|,\s*and|,\s*&)\s*(?:" + _HUMAN_NAME + r"))?"  # & last
    r")",
    re.IGNORECASE,
)


def _canonical_surname(raw_surname: str) -> str:
    """Apply DOCTOR_TAG_CORRECTIONS so typo variants normalize to the
    canonical spelling. Returns the canonical form (case + apostrophe +
    hyphen preserved)."""
    s = raw_surname.strip().rstrip(".,;")
    return DOCTOR_TAG_CORRECTIONS.get(s, s)


def _surname_from_full_name(name: str) -> str | None:
    """Given 'Mark Pegram', 'V K Gadi', or just 'Pegram', return the surname.

    If the captured name over-extends into a stopword (e.g. "Erika Hamilton
    and" — the regex grabbed the trailing "and" because we accept lowercase
    surnames to handle title typos), strip the stopword and use the token
    before it.
    """
    if not name:
        return None
    name = name.strip().rstrip(".,;")
    toks = [t.strip().rstrip(".,;") for t in name.split() if t.strip()]
    # Drop trailing stopwords ("and", "discuss", "with", ...).
    while toks and toks[-1].lower() in _TRAILING_STOPWORDS:
        toks.pop()
    if not toks:
        return None
    last = toks[-1]
    if not last or not last[0].isalpha():
        return None
    return _canonical_surname(last)


def extract_doctors_from_playlist_title(title: str) -> list[str]:
    """Return the ordered, deduplicated surname list extracted from a CHM
    playlist title.

    Order matches the first appearance of each surname in the title (so the
    output reflects how the playlist owner ordered the names). Surnames
    appear in their canonical form (typos corrected).
    """
    if not title:
        return []

    text = _normalize_quotes(title)

    seen: dict[str, None] = {}  # ordered set

    def _add(surname: str | None) -> None:
        if not surname:
            return
        if surname in seen:
            return
        seen[surname] = None

    # Pass 1: "Drs. <chain>" — grab the chunk, trim at the first
    # end-of-chain word, then split on commas/ands.
    for m in _RE_DRS_CHAIN.finditer(text):
        chunk = m.group(1)
        # Cut off at the first end-of-chain word
        cut_idx = len(chunk)
        for word in _END_OF_CHAIN_WORDS:
            wm = re.search(rf"\b{re.escape(word)}\b", chunk, re.IGNORECASE)
            if wm and wm.start() < cut_idx:
                cut_idx = wm.start()
        chunk = chunk[:cut_idx]
        # Split: commas, ampersands, "and"
        parts = re.split(r"\s*(?:,\s*&|,\s*and|&|,| and )\s*", chunk)
        for p in parts:
            p = p.strip().rstrip(".,;")
            if not p:
                continue
            # A part may itself start with "Dr." — strip prefix
            p = re.sub(r"^Drs?\.\s+", "", p)
            _add(_surname_from_full_name(p))

    # Pass 2: "Dr. <Name>" — pick up doctors not in a Drs. chain
    # (e.g. "Dr. Mark Pegram & Dr. Neil Iyengar" — & is between two
    # separate "Dr." prefixes, not inside a "Drs." chain).
    for m in _RE_DOCTOR_NAME.finditer(text):
        _add(_surname_from_full_name(m.group(1)))

    return list(seen.keys())


def doctor_tags_from_playlist_title(title: str) -> list[str]:
    """Convenience: same as extract_doctors_from_playlist_title but prefixed
    with `doctor:` to produce the canonical tag form."""
    return [f"doctor:{s}" for s in extract_doctors_from_playlist_title(title)]
