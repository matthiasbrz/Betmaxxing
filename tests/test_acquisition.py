"""The single acquisition path.

Covers the invariant that motivated it: **real source data is persisted even
when nothing can price it.** Snapshots cannot be re-downloaded; an analysis can
always be re-run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from betmaxxing.config import RunMode, Settings
from betmaxxing.domain.enums import CollectionStatus, ScanStatus, Sport
from betmaxxing.engine.acquisition import AcquisitionService
from betmaxxing.models_ml.registry import ModelRegistry
from betmaxxing.providers.demo import DemoContextProvider, DemoOddsProvider, DemoResultsProvider
from betmaxxing.providers.factory import ProviderBundle
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.repositories import (
    BatchRepository,
    EventRepository,
    OddsRepository,
    ScanRepository,
)
from betmaxxing.storage.tables import EventRow

NOW = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)


def demo_bundle(now: datetime, models: ModelRegistry | None = None) -> ProviderBundle:
    return ProviderBundle(
        odds=DemoOddsProvider(now),
        context=DemoContextProvider(now),
        results=DemoResultsProvider(),
        models=models if models is not None else ModelRegistry(models={}),
        warnings=[],
    )


class TestSourceDataIsPersisted:
    def test_events_and_snapshots_are_written(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        assert result.snapshots_persisted > 0
        with session_scope(db_settings) as session:
            assert OddsRepository(session).count() == result.snapshots_persisted
            assert EventRepository(session).count() == result.events_persisted

    def test_the_batch_is_recorded(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        with session_scope(db_settings) as session:
            row = BatchRepository(session).get(result.batch.batch_id)
            assert row is not None
            assert row.snapshots_persisted == result.snapshots_persisted
            assert row.provider == "demo"

    def test_the_scan_references_its_batch(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        assert result.scan.batch_id == result.batch.batch_id

    def test_reingesting_the_same_batch_writes_nothing_new(self, db_settings: Settings) -> None:
        """Idempotence comes from the snapshot fingerprint, not a memory cache."""
        service = AcquisitionService(db_settings)
        first = service.run(now=NOW)
        second = service.run(now=NOW)
        assert first.snapshots_persisted > 0
        assert second.snapshots_persisted == 0
        with session_scope(db_settings) as session:
            assert OddsRepository(session).count() == first.snapshots_persisted

    def test_a_snapshot_never_references_a_missing_event(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        with session_scope(db_settings) as session:
            stored = {row.canonical_id for row in session.scalars(select(EventRow)).all()}
        assert result.batch.snapshots
        for snapshot in result.batch.snapshots:
            assert snapshot.event_internal_id in stored


class TestCollectionWithoutModels:
    """The case that used to lose data: real prices, no model to price them."""

    def test_a_batch_with_no_model_is_still_stored(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(
            now=NOW, bundle=demo_bundle(NOW, ModelRegistry(models={}))
        )
        assert result.snapshots_persisted > 0
        assert result.scan.collection_status is CollectionStatus.COLLECTED_NO_MODEL

    def test_no_candidate_is_invented_to_fill_the_gap(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(
            now=NOW, bundle=demo_bundle(NOW, ModelRegistry(models={}))
        )
        assert result.scan.candidates == []
        assert result.scan.status is ScanStatus.NO_CANDIDATE

    def test_every_selection_is_rejected_with_an_explicit_code(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(
            now=NOW, bundle=demo_bundle(NOW, ModelRegistry(models={}))
        )
        assert result.scan.rejections_summary.get("NO_MODEL_AVAILABLE", 0) > 0

    def test_the_scan_is_persisted_too(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(
            now=NOW, bundle=demo_bundle(NOW, ModelRegistry(models={}))
        )
        with session_scope(db_settings) as session:
            assert ScanRepository(session).get(result.scan.scan_id) is not None


class TestCollectionStatus:
    def test_a_normal_demo_run_is_ok(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        assert result.scan.collection_status is CollectionStatus.OK

    def test_strict_thresholds_give_no_candidate_not_an_error(self, db_settings: Settings) -> None:
        strict = db_settings.model_copy(update={"min_ev": 0.95})
        result = AcquisitionService(strict).run(now=NOW)
        assert result.scan.collection_status is CollectionStatus.NO_CANDIDATE
        assert result.scan.status is ScanStatus.NO_CANDIDATE

    @pytest.mark.parametrize("mode", [RunMode.PAPER, RunMode.LIVE_ANALYSIS])
    def test_an_unconfigured_real_mode_is_a_provider_error(
        self, db_settings: Settings, mode: RunMode
    ) -> None:
        result = AcquisitionService(db_settings.model_copy(update={"mode": mode})).run(now=NOW)
        assert result.scan.collection_status is CollectionStatus.PROVIDER_ERROR
        assert result.scan.status is ScanStatus.DATA_UNAVAILABLE
        assert result.snapshots_persisted == 0


class TestEventScoping:
    def test_a_scoped_run_analyses_only_that_event(self, db_settings: Settings) -> None:
        """What a milestone job needs: the previous scheduler carried an event id
        and then ran a global scan anyway."""
        service = AcquisitionService(db_settings)
        full = service.run(now=NOW)
        target = full.scan.candidates[0].event.internal_id

        scoped = service.run(now=NOW, scope_event_id=target)
        assert scoped.scan.data_health.events_in_window == 1
        assert {c.event.internal_id for c in scoped.scan.candidates} == {target}

    def test_an_unknown_scope_yields_no_candidate(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW, scope_event_id="nope")
        assert result.scan.candidates == []


class TestPersistenceCanBeSkipped:
    def test_persist_false_writes_nothing(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW, persist=False)
        assert result.snapshots_persisted == 0
        with session_scope(db_settings) as session:
            assert OddsRepository(session).count() == 0


class TestIdentityIsResolvedBeforePersistence:
    def test_persisted_events_use_internal_ids(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        for event in result.batch.events:
            # Opaque identity, not the provider's own fixture key.
            assert event.internal_id.startswith("evt_")

    def test_repeated_runs_keep_one_identity_per_event(self, db_settings: Settings) -> None:
        service = AcquisitionService(db_settings)
        first = service.run(now=NOW)
        second = service.run(now=NOW + timedelta(minutes=1))
        assert {e.internal_id for e in first.batch.events} == {
            e.internal_id for e in second.batch.events
        }


class TestWindowFiltering:
    def test_events_outside_the_window_are_stored_but_not_analysed(
        self, db_settings: Settings
    ) -> None:
        """Collected data is kept whole; only the analysis is scoped."""
        result = AcquisitionService(db_settings).run(now=NOW)
        assert result.scan.data_health.events_discovered > (
            result.scan.data_health.events_in_window
        )
        assert result.scan.rejections_summary.get("OUTSIDE_WINDOW", 0) >= 1


class TestSportsInScope:
    def test_both_sports_are_collected(self, db_settings: Settings) -> None:
        result = AcquisitionService(db_settings).run(now=NOW)
        sports = {e.sport for e in result.batch.events}
        assert sports == {Sport.FOOTBALL, Sport.TENNIS}
