"""Event identity when the answer is *not* obvious.

``tests/test_identity.py`` covers the two clean paths: an authoritative
``(provider, provider_event_id)`` hit, and a single cross-provider match. This
file covers the case the audit found silently wrong — more than one plausible
match — plus the matching signals that were declared but never consulted.

The rule being pinned: **an ambiguity resolves to nothing.** No mapping row, no
mutated candidate event, no snapshot attached to whichever row sorted first. A
price we cannot attribute is a price we decline to use.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from betmaxxing.config import Settings
from betmaxxing.domain.enums import (
    EventStatus,
    MarketType,
    Period,
    ProviderHealth,
    RejectionCode,
    Sport,
)
from betmaxxing.domain.models import (
    CanonicalEvent,
    OddsSnapshot,
    Participant,
    ProviderStatus,
    Selection,
)
from betmaxxing.engine.acquisition import AcquisitionService
from betmaxxing.ingestion.identity import EventIdentityService
from betmaxxing.providers.base import CollectionBatch
from betmaxxing.providers.factory import ProviderBundle, build_providers
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import (
    EventRow,
    EventSourceMapRow,
    OddsSnapshotRow,
    ParticipantAliasRow,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def identity(db_settings: Settings) -> EventIdentityService:
    return EventIdentityService(db_settings)


@pytest.fixture
def ambiguous_pair(db_settings: Settings, identity: EventIdentityService) -> tuple[str, str]:
    return seed_two_plausible_fixtures(
        identity,
        first_start=NOW + timedelta(hours=6),
        second_start=NOW + timedelta(hours=9),
    )


def seed_two_plausible_fixtures(
    identity: EventIdentityService,
    *,
    first_start: datetime,
    second_start: datetime,
    competition_a: str = "Ligue 1",
    competition_b: str = "Ligue 1",
) -> tuple[str, str]:
    """Two meetings of the same pair, both inside the matching tolerance."""
    first = identity.resolve(
        provider="provider_a",
        provider_event_id="a-1",
        sport=Sport.FOOTBALL,
        competition=competition_a,
        home_name="Olympique Lyonnais",
        away_name="Stade Rennais",
        start_time_utc=first_start,
    )
    second = identity.resolve(
        provider="provider_a",
        provider_event_id="a-2",
        sport=Sport.FOOTBALL,
        competition=competition_b,
        home_name="Olympique Lyonnais",
        away_name="Stade Rennais",
        start_time_utc=second_start,
    )
    return first.internal_id, second.internal_id


class TestAmbiguityResolvesToNothing:
    def test_no_internal_id_is_chosen(self, identity: EventIdentityService) -> None:
        seed_two_plausible_fixtures(
            identity,
            first_start=NOW + timedelta(hours=6),
            second_start=NOW + timedelta(hours=9),
        )
        result = identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7, minutes=30),
        )
        assert result.ambiguous
        assert result.internal_id is None, (
            "an ambiguous resolution returned candidates[0] — a price would be "
            "attributed to whichever row happened to sort first"
        )

    def test_no_mapping_row_is_created(
        self, db_settings: Settings, identity: EventIdentityService
    ) -> None:
        seed_two_plausible_fixtures(
            identity,
            first_start=NOW + timedelta(hours=6),
            second_start=NOW + timedelta(hours=9),
        )
        identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7, minutes=30),
        )
        with session_scope(db_settings) as session:
            rows = session.scalars(
                select(EventSourceMapRow).where(EventSourceMapRow.provider == "provider_b")
            ).all()
        assert list(rows) == []

    def test_no_candidate_event_is_modified(
        self, db_settings: Settings, identity: EventIdentityService
    ) -> None:
        first_start = NOW + timedelta(hours=6)
        second_start = NOW + timedelta(hours=9)
        seed_two_plausible_fixtures(identity, first_start=first_start, second_start=second_start)
        identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7, minutes=30),
            status=EventStatus.POSTPONED,
        )
        with session_scope(db_settings) as session:
            starts = sorted(
                r.start_time_utc.replace(tzinfo=UTC)
                for r in session.scalars(select(EventRow)).all()
            )
            statuses = {r.status for r in session.scalars(select(EventRow)).all()}
        assert starts == [first_start, second_start]
        assert statuses == {str(EventStatus.SCHEDULED)}

    def test_the_ambiguity_is_queued_for_review(self, identity: EventIdentityService) -> None:
        seed_two_plausible_fixtures(
            identity,
            first_start=NOW + timedelta(hours=6),
            second_start=NOW + timedelta(hours=9),
        )
        identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7, minutes=30),
        )
        pending = identity.pending_review()
        assert len(pending) == 1
        assert pending[0]["provider"] == "provider_b"
        assert pending[0]["provider_event_id"] == "b-1"
        assert len(pending[0]["candidate_internal_ids"]) == 2


class _AmbiguousOdds:
    """Returns one event that plausibly matches two stored fixtures."""

    name = "provider_b"
    bookmaker = "winamax_fr"

    def __init__(self, moment: datetime) -> None:
        self._now = moment

    def collect(self, sports: list[Sport], window: tuple[datetime, datetime]) -> CollectionBatch:
        start = self._now + timedelta(hours=7, minutes=30)
        event = CanonicalEvent(
            internal_id="provider_b:b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home=Participant(canonical_id="football:olympique-lyonnais", name="Olympique Lyonnais"),
            away=Participant(canonical_id="football:stade-rennais", name="Stade Rennais"),
            start_time_utc=start,
            source_ids={"provider_b": "b-1"},
        )
        selection = Selection(
            market=MarketType.MATCH_RESULT_1X2,
            period=Period.FULL_TIME,
            code="home",
            label="Olympique Lyonnais",
        )
        snapshot = OddsSnapshot(
            provider="provider_b",
            bookmaker="winamax_fr",
            event_internal_id=event.internal_id,
            event_source_id="b-1",
            selection=selection,
            decimal_odds=1.80,
            currency="EUR",
            observed_at=self._now,
            received_at=self._now,
        )
        return CollectionBatch(
            provider="provider_b",
            collected_at=self._now,
            events=[event],
            snapshots=[snapshot],
            bookmakers=["winamax_fr"],
        )

    def health(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, kind="odds", health=ProviderHealth.OK)


def ambiguous_bundle(settings: Settings, moment: datetime) -> ProviderBundle:
    bundle = build_providers(settings, moment)
    bundle.odds = _AmbiguousOdds(moment)
    return bundle


class TestAmbiguityInAScan:
    def test_no_snapshot_is_attached_to_an_ambiguous_event(self, db_settings: Settings) -> None:
        """End to end: a price we cannot attribute is never stored against a guess."""
        identity = EventIdentityService(db_settings)
        seed_two_plausible_fixtures(
            identity,
            first_start=NOW + timedelta(hours=6),
            second_start=NOW + timedelta(hours=9),
        )

        service = AcquisitionService(db_settings)
        result = service.run(now=NOW, bundle=ambiguous_bundle(db_settings, NOW))

        with session_scope(db_settings) as session:
            snapshots = session.scalars(select(OddsSnapshotRow)).all()
        assert list(snapshots) == [], "a snapshot was attached to an arbitrary event"
        assert any(r.code is RejectionCode.EVENT_MAPPING_AMBIGUOUS for r in result.scan.rejections)

    def test_the_ambiguous_event_is_never_persisted(self, db_settings: Settings) -> None:
        identity = EventIdentityService(db_settings)
        first, second = seed_two_plausible_fixtures(
            identity,
            first_start=NOW + timedelta(hours=6),
            second_start=NOW + timedelta(hours=9),
        )
        AcquisitionService(db_settings).run(now=NOW, bundle=ambiguous_bundle(db_settings, NOW))
        with session_scope(db_settings) as session:
            ids = {r.canonical_id for r in session.scalars(select(EventRow)).all()}
        assert ids == {first, second}


class TestMatchingSignals:
    """Signals that exist in the data must actually be consulted."""

    def test_a_different_competition_prevents_a_merge(self, identity: EventIdentityService) -> None:
        identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6),
        )
        result = identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Coupe de France",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7),
        )
        assert result.created, "two different competitions were merged into one event"

    def test_a_different_stage_prevents_a_merge(self, identity: EventIdentityService) -> None:
        identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue des Champions",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6),
            stage="1/8 aller",
        )
        result = identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue des Champions",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7),
            stage="1/8 retour",
        )
        assert result.created, "two legs of a tie were merged into one event"

    def test_a_different_season_prevents_a_merge(self, identity: EventIdentityService) -> None:
        identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6),
            season="2025-2026",
        )
        result = identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=7),
            season="2026-2027",
        )
        assert result.created

    def test_a_provider_alias_lets_two_spellings_match(
        self, db_settings: Settings, identity: EventIdentityService
    ) -> None:
        """``OL`` and ``Olympique Lyonnais`` are the same club, once declared."""
        with session_scope(db_settings) as session:
            session.add(
                ParticipantAliasRow(
                    sport=str(Sport.FOOTBALL),
                    alias="OL",
                    canonical_participant_id="football:olympique-lyonnais",
                    source="provider_b",
                )
            )

        first = identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6),
        )
        second = identity.resolve(
            provider="provider_b",
            provider_event_id="b-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="OL",
            away_name="Stade Rennais",
            start_time_utc=NOW + timedelta(hours=6, minutes=30),
        )
        assert not second.created
        assert second.internal_id == first.internal_id

    def test_two_providers_may_declare_the_same_alias_differently(
        self, db_settings: Settings
    ) -> None:
        """The unique constraint must not let one provider's alias evict another's."""
        with session_scope(db_settings) as session:
            session.add(
                ParticipantAliasRow(
                    sport=str(Sport.FOOTBALL),
                    alias="OL",
                    canonical_participant_id="football:olympique-lyonnais",
                    source="provider_a",
                )
            )
        with session_scope(db_settings) as session:
            session.add(
                ParticipantAliasRow(
                    sport=str(Sport.FOOTBALL),
                    alias="OL",
                    canonical_participant_id="football:olympique-lyonnais",
                    source="provider_b",
                )
            )
        with session_scope(db_settings) as session:
            rows = session.scalars(select(ParticipantAliasRow)).all()
        assert len(list(rows)) == 2


class TestPostponementAndRematch:
    def test_a_postponement_keeps_one_identity(self, identity: EventIdentityService) -> None:
        first = identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=datetime(2026, 8, 4, 23, 30, tzinfo=UTC),
        )
        moved = identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.FOOTBALL,
            competition="Ligue 1",
            home_name="Olympique Lyonnais",
            away_name="Stade Rennais",
            start_time_utc=datetime(2026, 8, 5, 0, 30, tzinfo=UTC),
            status=EventStatus.POSTPONED,
        )
        assert moved.internal_id == first.internal_id
        assert moved.rescheduled

    def test_a_rematch_far_apart_is_a_separate_event(self, identity: EventIdentityService) -> None:
        first = identity.resolve(
            provider="provider_a",
            provider_event_id="a-1",
            sport=Sport.TENNIS,
            competition="ATP",
            home_name="Joueur A",
            away_name="Joueur B",
            start_time_utc=NOW,
        )
        second = identity.resolve(
            provider="provider_a",
            provider_event_id="a-2",
            sport=Sport.TENNIS,
            competition="ATP",
            home_name="Joueur A",
            away_name="Joueur B",
            start_time_utc=NOW + timedelta(days=14),
        )
        assert second.internal_id != first.internal_id
