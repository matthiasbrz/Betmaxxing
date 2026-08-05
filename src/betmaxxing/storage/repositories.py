"""Repositories.

The snapshot repository is the one place that enforces append-only + idempotent
ingest: :meth:`OddsRepository.store` skips fingerprints already present instead of
updating them, so replaying a fetch never rewrites history or double-counts.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from betmaxxing.domain.ids import alert_key as make_alert_key
from betmaxxing.domain.models import CanonicalEvent, OddsSnapshot, ScanResult
from betmaxxing.domain.timeutil import ensure_utc
from betmaxxing.ingestion.identity import participant_pair_key
from betmaxxing.storage.tables import (
    CandidateRow,
    CollectionBatchRow,
    EventRow,
    ModelRegistryRow,
    OddsSnapshotRow,
    RejectionRow,
    ScanRunRow,
)


def _json_safe(value: object) -> object:
    """Round-trip through Pydantic's JSON encoder so datetimes/enums serialise."""
    return json.loads(json.dumps(value, default=str))


class EventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, event: CanonicalEvent) -> None:
        row = self._session.get(EventRow, event.internal_id)
        if row is None:
            row = EventRow(canonical_id=event.internal_id)
            self._session.add(row)
        row.sport = str(event.sport)
        row.competition = event.competition
        row.stage = event.stage
        row.surface = event.surface
        row.sets_to_win = event.sets_to_win
        row.home_name = event.home.name
        row.away_name = event.away.name
        row.home_canonical_id = event.home.canonical_id
        row.away_canonical_id = event.away.canonical_id
        row.participant_pair_key = participant_pair_key(
            event.sport, event.home.name, event.away.name
        )
        row.start_time_utc = ensure_utc(event.start_time_utc)
        row.status = str(event.status)
        row.mapping_ambiguous = event.mapping_ambiguous
        row.source_ids = dict(event.source_ids)

    def get(self, internal_id: str) -> EventRow | None:
        return self._session.get(EventRow, internal_id)

    def count(self) -> int:
        return len(list(self._session.scalars(select(EventRow.canonical_id)).all()))


class OddsRepository:
    """Append-only store of immutable snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def store(self, snapshots: list[OddsSnapshot], batch_id: str | None = None) -> int:
        """Insert new snapshots. Returns the number actually written.

        Existing fingerprints are skipped, never updated: a recorded price is a
        historical fact.
        """
        if not snapshots:
            return 0
        incoming = {s.fingerprint: s for s in snapshots}
        existing = set(
            self._session.scalars(
                select(OddsSnapshotRow.fingerprint).where(
                    OddsSnapshotRow.fingerprint.in_(list(incoming))
                )
            ).all()
        )
        written = 0
        for fingerprint, snapshot in incoming.items():
            if fingerprint in existing:
                continue
            selection = snapshot.selection
            self._session.add(
                OddsSnapshotRow(
                    fingerprint=fingerprint,
                    provider=snapshot.provider,
                    bookmaker=snapshot.bookmaker,
                    event_canonical_id=snapshot.event_internal_id,
                    event_source_id=snapshot.event_source_id,
                    selection_key=selection.key,
                    market=str(selection.market),
                    period=str(selection.period),
                    line=float(selection.line) if selection.line is not None else None,
                    line_canonical=selection.line_canonical,
                    selection_code=selection.code,
                    selection_label=selection.label,
                    decimal_odds=snapshot.decimal_odds,
                    currency=snapshot.currency,
                    event_status=str(snapshot.event_status),
                    provider_updated_at=snapshot.provider_updated_at,
                    observed_at=snapshot.observed_at,
                    received_at=snapshot.received_at,
                    source_meta=dict(snapshot.source_meta),
                    batch_id=batch_id,
                )
            )
            written += 1
        return written

    def history(self, event_canonical_id: str, selection_key: str) -> list[OddsSnapshotRow]:
        stmt = (
            select(OddsSnapshotRow)
            .where(
                OddsSnapshotRow.event_canonical_id == event_canonical_id,
                OddsSnapshotRow.selection_key == selection_key,
            )
            .order_by(OddsSnapshotRow.observed_at)
        )
        return list(self._session.scalars(stmt).all())

    def count(self) -> int:
        return len(list(self._session.scalars(select(OddsSnapshotRow.id)).all()))


class ScanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, result: ScanResult) -> None:
        document = _json_safe(result.model_dump(mode="json"))
        self._session.add(
            ScanRunRow(
                scan_id=result.scan_id,
                status=str(result.status),
                mode=result.mode,
                generated_at=ensure_utc(result.generated_at),
                window_from=ensure_utc(result.window["from"]),
                window_to=ensure_utc(result.window["to"]),
                config_fingerprint=result.config_fingerprint,
                collection_status=str(result.collection_status),
                batch_id=result.batch_id,
                candidate_count=len(result.candidates),
                rejection_count=len(result.rejections),
                document=document,
            )
        )
        # The scan row must exist before anything references it. These tables are
        # linked by plain ForeignKey columns rather than ORM relationships, so
        # SQLAlchemy's unit of work has no dependency to sort on and would emit
        # the child inserts first (mappers are ordered by name: candidates and
        # rejections both sort before scan_runs), tripping the FK constraint.
        self._session.flush()

        for candidate in result.candidates:
            self._session.add(
                CandidateRow(
                    candidate_id=candidate.candidate_id,
                    scan_id=result.scan_id,
                    alert_key=make_alert_key(
                        candidate.event.internal_id,
                        candidate.selection.key,
                        candidate.bookmaker,
                    ),
                    event_canonical_id=candidate.event.internal_id,
                    selection_key=candidate.selection.key,
                    bookmaker=candidate.bookmaker,
                    decimal_odds=candidate.value.decimal_odds,
                    model_probability=candidate.value.conditional_win_probability,
                    ev=candidate.value.ev,
                    ev_conservative=candidate.value.ev_conservative,
                    data_quality=candidate.data_quality.score,
                    model_id=candidate.model_id,
                    model_version=candidate.model_version,
                    validation_status=str(candidate.probability.validation_status),
                    uncertainty_status=str(candidate.probability.uncertainty.status),
                    observed_at=ensure_utc(candidate.observed_at),
                    document=_json_safe(candidate.model_dump(mode="json")),
                )
            )
        for rejection in result.rejections:
            self._session.add(
                RejectionRow(
                    scan_id=result.scan_id,
                    event_canonical_id=rejection.event_internal_id,
                    event_label=rejection.event_label,
                    selection_key=rejection.selection_key,
                    code=str(rejection.code),
                    detail=rejection.detail,
                )
            )

    def get(self, scan_id: str) -> ScanRunRow | None:
        return self._session.get(ScanRunRow, scan_id)

    def latest(self, limit: int = 20) -> list[ScanRunRow]:
        stmt = select(ScanRunRow).order_by(ScanRunRow.generated_at.desc()).limit(limit)
        return list(self._session.scalars(stmt).all())

    def candidates_since(self, moment: datetime) -> list[CandidateRow]:
        stmt = (
            select(CandidateRow)
            .where(CandidateRow.observed_at >= ensure_utc(moment))
            .order_by(CandidateRow.ev.desc())
        )
        return list(self._session.scalars(stmt).all())

    def rejections_for(self, scan_id: str) -> list[RejectionRow]:
        stmt = select(RejectionRow).where(RejectionRow.scan_id == scan_id)
        return list(self._session.scalars(stmt).all())


class BatchRepository:
    """Records every collection, including ones that produced no candidate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        batch: object,
        *,
        mode: str,
        events_persisted: int,
        snapshots_persisted: int,
    ) -> None:
        if self._session.get(CollectionBatchRow, batch.batch_id) is not None:  # type: ignore[attr-defined]
            return
        self._session.add(
            CollectionBatchRow(
                batch_id=batch.batch_id,  # type: ignore[attr-defined]
                provider=batch.provider,  # type: ignore[attr-defined]
                collected_at=ensure_utc(batch.collected_at),  # type: ignore[attr-defined]
                mode=mode,
                events_seen=len(batch.events),  # type: ignore[attr-defined]
                snapshots_seen=len(batch.snapshots),  # type: ignore[attr-defined]
                events_persisted=events_persisted,
                snapshots_persisted=snapshots_persisted,
                coverage_status=str(batch.coverage),  # type: ignore[attr-defined]
                partial_errors={"errors": list(batch.partial_errors)},  # type: ignore[attr-defined]
                quota=batch.quota.as_dict(),  # type: ignore[attr-defined]
            )
        )

    def get(self, batch_id: str) -> CollectionBatchRow | None:
        return self._session.get(CollectionBatchRow, batch_id)

    def count(self) -> int:
        return len(list(self._session.scalars(select(CollectionBatchRow.batch_id)).all()))


class ModelRegistryRepository:
    """Persisted validation status. Absent means BACKTEST_ONLY."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        *,
        model_id: str,
        version: str,
        sport: str,
        validation_status: str,
        uncertainty_method: str = "none",
        notes: str | None = None,
    ) -> None:
        row = self._session.scalar(
            select(ModelRegistryRow).where(
                ModelRegistryRow.model_id == model_id,
                ModelRegistryRow.version == version,
            )
        )
        if row is None:
            row = ModelRegistryRow(model_id=model_id, version=version, sport=sport)
            self._session.add(row)
        row.sport = sport
        row.validation_status = validation_status
        row.uncertainty_method = uncertainty_method
        row.notes = notes

    def all(self) -> list[ModelRegistryRow]:
        return list(self._session.scalars(select(ModelRegistryRow)).all())
