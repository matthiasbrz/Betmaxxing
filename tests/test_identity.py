"""Stable event identity.

The old scheme hashed ``(sport, UTC date, participants)``. Two consequences it
could not avoid: a postponement across midnight minted a second event, and two
fixtures between the same sides on one day collided into one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betmaxxing.config import Settings
from betmaxxing.domain.enums import EventStatus, Sport
from betmaxxing.ingestion.identity import (
    CROSS_PROVIDER_TOLERANCE,
    EventIdentityService,
    new_internal_id,
    participant_pair_key,
)

KICKOFF = datetime(2026, 8, 4, 23, 30, tzinfo=UTC)


@pytest.fixture
def service(db_settings: Settings) -> EventIdentityService:
    return EventIdentityService(db_settings)


def resolve(service: EventIdentityService, **overrides: object):  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "provider": "p",
        "provider_event_id": "X1",
        "sport": Sport.FOOTBALL,
        "competition": "Ligue 1",
        "home_name": "Olympique Lyonnais",
        "away_name": "Stade Rennais",
        "start_time_utc": KICKOFF,
    }
    payload.update(overrides)
    return service.resolve(**payload)  # type: ignore[arg-type]


class TestInternalIds:
    def test_ids_are_opaque(self) -> None:
        assert new_internal_id().startswith("evt_")

    def test_ids_are_unique(self) -> None:
        assert len({new_internal_id() for _ in range(100)}) == 100

    def test_ids_carry_no_date(self) -> None:
        """Nothing in the id may encode a kick-off, or a reschedule changes it."""
        generated = new_internal_id()
        assert "2026" not in generated
        assert "0804" not in generated


class TestPostponement:
    def test_a_reschedule_across_midnight_keeps_one_event(
        self, service: EventIdentityService
    ) -> None:
        before = resolve(service)
        after = resolve(service, start_time_utc=KICKOFF + timedelta(hours=1))
        assert before.internal_id == after.internal_id
        assert after.rescheduled

    def test_a_long_postponement_keeps_one_event(self, service: EventIdentityService) -> None:
        before = resolve(service)
        after = resolve(service, start_time_utc=KICKOFF + timedelta(days=14))
        assert before.internal_id == after.internal_id

    def test_the_reschedule_is_recorded_in_history(self, service: EventIdentityService) -> None:
        first = resolve(service)
        resolve(service, start_time_utc=KICKOFF + timedelta(hours=2))
        history = service.schedule_history(first.internal_id)
        assert len(history) >= 2
        assert history[-1]["previous_start_time_utc"] is not None

    def test_an_unchanged_kick_off_is_not_flagged(self, service: EventIdentityService) -> None:
        resolve(service)
        again = resolve(service)
        assert not again.rescheduled


class TestDistinctFixtures:
    def test_two_provider_ids_on_one_day_stay_distinct(self, service: EventIdentityService) -> None:
        """The collision the old date-based hash produced."""
        morning = resolve(
            service,
            provider_event_id="L1",
            start_time_utc=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
        )
        evening = resolve(
            service,
            provider_event_id="L2",
            start_time_utc=datetime(2026, 8, 4, 20, 0, tzinfo=UTC),
        )
        assert morning.internal_id != evening.internal_id

    def test_a_reversed_fixture_is_a_different_event(self, service: EventIdentityService) -> None:
        home = resolve(service, provider_event_id="H")
        away = resolve(
            service,
            provider_event_id="A",
            home_name="Stade Rennais",
            away_name="Olympique Lyonnais",
        )
        assert home.internal_id != away.internal_id

    def test_different_sports_never_share_identity(self, service: EventIdentityService) -> None:
        football = resolve(service, provider_event_id="F")
        tennis = resolve(service, provider_event_id="T", sport=Sport.TENNIS)
        assert football.internal_id != tennis.internal_id


class TestCrossProviderMatching:
    def test_two_providers_converge_on_one_event(self, service: EventIdentityService) -> None:
        first = resolve(service, provider="p1", provider_event_id="AAA")
        second = resolve(
            service,
            provider="p2",
            provider_event_id="BBB",
            start_time_utc=KICKOFF + timedelta(minutes=15),
        )
        assert first.internal_id == second.internal_id
        assert not second.created

    def test_a_distant_kick_off_does_not_merge(self, service: EventIdentityService) -> None:
        """The tolerance is tight on purpose — a wide one re-creates the collision."""
        first = resolve(service, provider="p1", provider_event_id="AAA")
        second = resolve(
            service,
            provider="p2",
            provider_event_id="BBB",
            start_time_utc=KICKOFF + CROSS_PROVIDER_TOLERANCE + timedelta(hours=1),
        )
        assert first.internal_id != second.internal_id

    def test_a_later_lookup_uses_the_mapping_not_the_heuristic(
        self, service: EventIdentityService
    ) -> None:
        first = resolve(service, provider="p1", provider_event_id="AAA")
        resolve(service, provider="p2", provider_event_id="BBB")
        # p2 is now mapped; moving its kick-off must not create a new event.
        again = resolve(
            service,
            provider="p2",
            provider_event_id="BBB",
            start_time_utc=KICKOFF + timedelta(days=3),
        )
        assert again.internal_id == first.internal_id


class TestAmbiguity:
    def test_multiple_matches_are_refused_not_guessed(self, db_settings: Settings) -> None:
        """Two plausible matches means we decline, because guessing which
        fixture a price belongs to is worse than not pricing it."""
        service = EventIdentityService(db_settings)
        resolve(service, provider="p1", provider_event_id="A")
        resolve(
            service,
            provider="p2",
            provider_event_id="B",
            start_time_utc=KICKOFF + timedelta(days=30),
        )
        # Pull the second event back into the matching window.
        resolve(
            service,
            provider="p2",
            provider_event_id="B",
            start_time_utc=KICKOFF + timedelta(hours=1),
        )
        # A third provider whose kick-off sits between both existing events.
        outcome = resolve(
            service,
            provider="p9",
            provider_event_id="C",
            start_time_utc=KICKOFF + timedelta(minutes=30),
        )
        assert outcome.ambiguous
        assert "rapprochement refusé" in outcome.detail
        # An ambiguity carries no identity at all: there is nothing to attach to.
        assert outcome.internal_id is None
        assert len(outcome.candidate_internal_ids) == 2


class TestSameProviderNeverMerges:
    def test_two_ids_from_one_provider_stay_distinct(self, service: EventIdentityService) -> None:
        """A provider knows its own catalogue: two ids mean two fixtures."""
        first = resolve(service, provider="p1", provider_event_id="LEG1")
        second = resolve(
            service,
            provider="p1",
            provider_event_id="LEG2",
            start_time_utc=KICKOFF + timedelta(hours=1),
        )
        assert first.internal_id != second.internal_id
        assert second.created


class TestParticipantKey:
    def test_key_is_order_sensitive(self) -> None:
        assert participant_pair_key(Sport.FOOTBALL, "A", "B") != participant_pair_key(
            Sport.FOOTBALL, "B", "A"
        )

    def test_naming_variants_normalise_together(self) -> None:
        assert participant_pair_key(
            Sport.FOOTBALL, "FC Augsburg", "VfB Stuttgart"
        ) == participant_pair_key(Sport.FOOTBALL, "Augsburg", "Stuttgart")


class TestStatusHistory:
    def test_a_status_change_is_recorded(self, service: EventIdentityService) -> None:
        first = resolve(service)
        resolve(service, status=EventStatus.POSTPONED)
        history = service.schedule_history(first.internal_id)
        assert any(entry["status"] == "postponed" for entry in history)
