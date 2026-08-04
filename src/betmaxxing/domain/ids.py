"""Canonical identifiers.

Reconciling the same event across providers is the single largest source of
silent error in a betting pipeline. The rule here: a canonical id is derived
deterministically from normalised, stable attributes (sport, date, both
participants), so two providers describing the same match land on the same id
without a shared key — and when normalisation cannot decide, the caller marks the
event ``mapping_ambiguous`` rather than guessing.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime

from betmaxxing.domain.timeutil import ensure_utc

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: Tokens that carry no discriminating information in team/player names.
_NOISE_TOKENS = frozenset(
    {
        "fc",
        "cf",
        "sc",
        "ac",
        "afc",
        "cd",
        "ud",
        "us",
        "sv",
        "vfl",
        "vfb",
        "bsc",
        "club",
        "de",
        "the",
    }
)


def slugify(value: str) -> str:
    """Lower-case, accent-free, punctuation-free token stream."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub("-", ascii_only.lower()).strip("-")


def normalize_participant(name: str) -> str:
    """Normalised participant key used for matching across sources.

    Drops common club-name noise tokens but never drops the last remaining
    token, so "FC" alone would still normalise to something non-empty.
    """
    slug = slugify(name)
    tokens = [t for t in slug.split("-") if t]
    meaningful = [t for t in tokens if t not in _NOISE_TOKENS]
    return "-".join(meaningful or tokens)


def participant_id(sport: str, name: str) -> str:
    return f"{sport}:{normalize_participant(name)}"


def event_canonical_id(
    sport: str,
    home_name: str,
    away_name: str,
    start_time_utc: datetime,
) -> str:
    """Deterministic event id.

    The UTC calendar date — not the exact kick-off — is part of the key so that
    providers disagreeing by a few minutes still reconcile, while two different
    fixtures between the same sides on different days stay distinct.
    """
    day = ensure_utc(start_time_utc).strftime("%Y%m%d")
    home = normalize_participant(home_name)
    away = normalize_participant(away_name)
    raw = f"{slugify(sport)}|{day}|{home}|{away}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"{slugify(sport)}-{day}-{digest}"


def candidate_id(scan_id: str, event_id: str, selection_key: str, bookmaker: str) -> str:
    raw = f"{scan_id}|{event_id}|{selection_key}|{bookmaker}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def alert_key(event_id: str, selection_key: str, bookmaker: str) -> str:
    """Stable identity of a candidate across scans, used to deduplicate alerts."""
    raw = f"{event_id}|{selection_key}|{bookmaker}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]
