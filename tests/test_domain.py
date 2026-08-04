"""Domain invariants: market identity, snapshot immutability, canonical ids."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from betmaxxing.domain.enums import EventStatus, MarketType, Period, Sport
from betmaxxing.domain.ids import (
    alert_key,
    event_canonical_id,
    normalize_participant,
    participant_id,
    slugify,
)
from betmaxxing.domain.models import CanonicalEvent, OddsSnapshot, Participant, Selection

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def make_selection(**overrides: object) -> Selection:
    base: dict[str, object] = {
        "market": MarketType.MATCH_RESULT_1X2,
        "period": Period.FULL_TIME,
        "code": "home",
        "label": "Olympique Lyonnais",
    }
    base.update(overrides)
    return Selection(**base)  # type: ignore[arg-type]


def make_snapshot(**overrides: object) -> OddsSnapshot:
    base: dict[str, object] = {
        "provider": "demo",
        "bookmaker": "DEMO_BOOK",
        "event_canonical_id": "football-20260804-abc123",
        "event_source_id": "src-1",
        "selection": make_selection(),
        "decimal_odds": 1.63,
        "observed_at": NOW,
        "received_at": NOW,
    }
    base.update(overrides)
    return OddsSnapshot(**base)  # type: ignore[arg-type]


class TestSelectionIdentity:
    def test_line_is_required_for_over_under_markets(self) -> None:
        with pytest.raises(ValidationError, match="requires an explicit line"):
            make_selection(market=MarketType.TOTAL_GOALS, code="over", label="+2.5")

    def test_line_is_forbidden_on_markets_that_have_none(self) -> None:
        with pytest.raises(ValidationError, match="must not carry a line"):
            make_selection(line=2.5)

    def test_key_distinguishes_period(self) -> None:
        full = make_selection(period=Period.FULL_TIME)
        half = make_selection(period=Period.FIRST_HALF)
        assert full.key != half.key

    def test_key_distinguishes_line(self) -> None:
        over_25 = make_selection(market=MarketType.TOTAL_GOALS, code="over", label="+2.5", line=2.5)
        over_35 = make_selection(market=MarketType.TOTAL_GOALS, code="over", label="+3.5", line=3.5)
        assert over_25.key != over_35.key

    def test_key_distinguishes_market(self) -> None:
        one_x_two = make_selection(market=MarketType.MATCH_RESULT_1X2)
        dnb = make_selection(market=MarketType.DRAW_NO_BET)
        assert one_x_two.key != dnb.key


class TestSnapshotImmutability:
    def test_snapshot_cannot_be_mutated(self) -> None:
        snapshot = make_snapshot()
        with pytest.raises(ValidationError):
            snapshot.decimal_odds = 2.0  # type: ignore[misc]

    def test_rejects_odds_at_or_below_one(self) -> None:
        with pytest.raises(ValidationError):
            make_snapshot(decimal_odds=1.0)

    def test_rejects_naive_timestamps(self) -> None:
        with pytest.raises(ValidationError):
            make_snapshot(observed_at=datetime(2026, 8, 4, 9, 0))

    def test_implied_probability_is_reciprocal_of_odds(self) -> None:
        assert make_snapshot(decimal_odds=2.0).implied_probability_raw == pytest.approx(0.5)


class TestSnapshotFingerprint:
    def test_identical_observations_share_a_fingerprint(self) -> None:
        assert make_snapshot().fingerprint == make_snapshot().fingerprint

    def test_a_different_price_changes_the_fingerprint(self) -> None:
        assert make_snapshot().fingerprint != make_snapshot(decimal_odds=1.64).fingerprint

    def test_a_different_instant_changes_the_fingerprint(self) -> None:
        later = make_snapshot(observed_at=NOW + timedelta(seconds=1))
        assert make_snapshot().fingerprint != later.fingerprint

    def test_a_different_bookmaker_changes_the_fingerprint(self) -> None:
        assert make_snapshot().fingerprint != make_snapshot(bookmaker="OTHER").fingerprint


class TestCanonicalIds:
    def test_slugify_strips_accents_and_punctuation(self) -> None:
        assert slugify("Olympique Lyonnais") == "olympique-lyonnais"
        assert slugify("Hellas Vérona!") == "hellas-verona"

    def test_normalisation_drops_club_noise_tokens(self) -> None:
        assert normalize_participant("FC Augsburg") == "augsburg"
        assert normalize_participant("Getafe CF") == "getafe"

    def test_normalisation_never_returns_empty(self) -> None:
        assert normalize_participant("FC") == "fc"

    def test_same_fixture_from_two_sources_reconciles(self) -> None:
        # Two providers, different naming conventions and a few minutes apart.
        first = event_canonical_id(
            "football", "FC Augsburg", "VfB Stuttgart", datetime(2026, 8, 4, 18, 30, tzinfo=UTC)
        )
        second = event_canonical_id(
            "football", "Augsburg", "Stuttgart", datetime(2026, 8, 4, 18, 45, tzinfo=UTC)
        )
        assert first == second

    def test_different_fixtures_on_different_days_stay_distinct(self) -> None:
        first = event_canonical_id(
            "football", "Augsburg", "Stuttgart", datetime(2026, 8, 4, 18, 30, tzinfo=UTC)
        )
        second = event_canonical_id(
            "football", "Augsburg", "Stuttgart", datetime(2026, 12, 4, 18, 30, tzinfo=UTC)
        )
        assert first != second

    def test_reversed_fixture_is_a_different_event(self) -> None:
        home_away = event_canonical_id(
            "football", "Augsburg", "Stuttgart", datetime(2026, 8, 4, 18, 30, tzinfo=UTC)
        )
        away_home = event_canonical_id(
            "football", "Stuttgart", "Augsburg", datetime(2026, 8, 4, 18, 30, tzinfo=UTC)
        )
        assert home_away != away_home

    def test_participant_id_is_sport_scoped(self) -> None:
        assert participant_id("tennis", "Alcaraz") != participant_id("football", "Alcaraz")

    def test_alert_key_is_stable_across_scans(self) -> None:
        first = alert_key("evt-1", "1x2|full_time|-|home", "DEMO_BOOK")
        second = alert_key("evt-1", "1x2|full_time|-|home", "DEMO_BOOK")
        assert first == second


class TestCanonicalEvent:
    def test_label_reads_naturally(self) -> None:
        event = CanonicalEvent(
            canonical_id="e1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home=Participant(canonical_id="p1", name="Lyon"),
            away=Participant(canonical_id="p2", name="Rennes"),
            start_time_utc=NOW,
            status=EventStatus.SCHEDULED,
        )
        assert event.label == "Lyon vs Rennes"
