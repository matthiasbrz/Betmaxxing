"""Persistence: append-only snapshots, idempotent ingest, scan archival."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from betmaxxing.config import Settings
from betmaxxing.domain.enums import MarketType, Period, Sport
from betmaxxing.domain.models import (
    CanonicalEvent,
    OddsSnapshot,
    Participant,
    Selection,
)
from betmaxxing.engine.scan import run_scan
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.repositories import EventRepository, OddsRepository, ScanRepository

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
EVENT = CanonicalEvent(
    canonical_id="football-20260804-abc",
    sport=Sport.FOOTBALL,
    competition="Ligue 1",
    home=Participant(canonical_id="p1", name="Lyon"),
    away=Participant(canonical_id="p2", name="Rennes"),
    start_time_utc=NOW + timedelta(hours=6),
)


def snapshot(odds: float, observed: datetime | None = None) -> OddsSnapshot:
    return OddsSnapshot(
        provider="demo",
        bookmaker="DEMO_BOOK",
        event_canonical_id=EVENT.canonical_id,
        event_source_id="src",
        selection=Selection(
            market=MarketType.MATCH_RESULT_1X2,
            period=Period.FULL_TIME,
            code="home",
            label="Lyon",
        ),
        decimal_odds=odds,
        observed_at=observed or NOW,
        received_at=NOW,
    )


class TestOddsRepositoryIsAppendOnly:
    def test_stores_new_snapshots(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(EVENT)
            written = OddsRepository(session).store([snapshot(1.63)])
        assert written == 1

    def test_reingesting_the_same_snapshot_is_a_no_op(self, db_settings: Settings) -> None:
        """Idempotent ingest: replaying a fetch must not double-count."""
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(EVENT)
            OddsRepository(session).store([snapshot(1.63)])
        with session_scope(db_settings) as session:
            written = OddsRepository(session).store([snapshot(1.63)])
        assert written == 0
        with session_scope(db_settings) as session:
            assert OddsRepository(session).count() == 1

    def test_a_new_price_is_a_new_row_not_an_update(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(EVENT)
            OddsRepository(session).store([snapshot(1.63)])
            OddsRepository(session).store([snapshot(1.58, observed=NOW + timedelta(minutes=5))])
        with session_scope(db_settings) as session:
            history = OddsRepository(session).history(EVENT.canonical_id, "1x2|full_time|-|home")
        assert [row.decimal_odds for row in history] == [1.63, 1.58]

    def test_history_is_returned_in_chronological_order(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(EVENT)
            OddsRepository(session).store(
                [
                    snapshot(1.58, observed=NOW + timedelta(minutes=5)),
                    snapshot(1.63, observed=NOW),
                ]
            )
        with session_scope(db_settings) as session:
            history = OddsRepository(session).history(EVENT.canonical_id, "1x2|full_time|-|home")
        assert [row.observed_at for row in history] == sorted(row.observed_at for row in history)

    def test_storing_nothing_is_safe(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            assert OddsRepository(session).store([]) == 0


class TestEventRepository:
    def test_upsert_is_idempotent(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(EVENT)
            EventRepository(session).upsert(EVENT)
        with session_scope(db_settings) as session:
            assert EventRepository(session).get(EVENT.canonical_id) is not None

    def test_upsert_refreshes_mutable_fields(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(EVENT)
        with session_scope(db_settings) as session:
            EventRepository(session).upsert(
                EVENT.model_copy(update={"competition": "Coupe de France"})
            )
        with session_scope(db_settings) as session:
            row = EventRepository(session).get(EVENT.canonical_id)
            assert row is not None
            assert row.competition == "Coupe de France"


class TestScanRepository:
    def test_saves_and_reloads_a_scan(self, db_settings: Settings) -> None:
        result = run_scan(db_settings, now=NOW)
        with session_scope(db_settings) as session:
            ScanRepository(session).save(result)
        with session_scope(db_settings) as session:
            row = ScanRepository(session).get(result.scan_id)
            assert row is not None
            assert row.candidate_count == len(result.candidates)
            assert row.config_fingerprint == result.config_fingerprint

    def test_stores_the_full_document_for_reproduction(self, db_settings: Settings) -> None:
        result = run_scan(db_settings, now=NOW)
        with session_scope(db_settings) as session:
            ScanRepository(session).save(result)
        with session_scope(db_settings) as session:
            row = ScanRepository(session).get(result.scan_id)
            assert row is not None
            assert row.document["scan_id"] == result.scan_id
            assert len(row.document["candidates"]) == len(result.candidates)
            assert row.document["thresholds"]["min_ev"] == db_settings.min_ev

    def test_rejections_are_persisted_with_their_codes(self, db_settings: Settings) -> None:
        result = run_scan(db_settings, now=NOW)
        with session_scope(db_settings) as session:
            ScanRepository(session).save(result)
        with session_scope(db_settings) as session:
            rows = ScanRepository(session).rejections_for(result.scan_id)
        assert len(rows) == len(result.rejections)
        assert all(row.code for row in rows)

    def test_latest_returns_newest_first(self, db_settings: Settings) -> None:
        first = run_scan(db_settings, now=NOW)
        second = run_scan(db_settings, now=NOW + timedelta(hours=1))
        with session_scope(db_settings) as session:
            repo = ScanRepository(session)
            repo.save(first)
            repo.save(second)
        with session_scope(db_settings) as session:
            rows = ScanRepository(session).latest(10)
        assert rows[0].scan_id == second.scan_id

    def test_unknown_scan_returns_none(self, db_settings: Settings) -> None:
        with session_scope(db_settings) as session:
            assert ScanRepository(session).get("does-not-exist") is None
