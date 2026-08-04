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
from betmaxxing.storage.tables import (
    CandidateRow,
    EventRow,
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
        row = self._session.get(EventRow, event.canonical_id)
        if row is None:
            row = EventRow(canonical_id=event.canonical_id)
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
        row.start_time_utc = ensure_utc(event.start_time_utc)
        row.status = str(event.status)
        row.mapping_ambiguous = event.mapping_ambiguous
        row.source_ids = dict(event.source_ids)

    def get(self, canonical_id: str) -> EventRow | None:
        return self._session.get(EventRow, canonical_id)


class OddsRepository:
    """Append-only store of immutable snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def store(self, snapshots: list[OddsSnapshot]) -> int:
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
                    event_canonical_id=snapshot.event_canonical_id,
                    event_source_id=snapshot.event_source_id,
                    selection_key=selection.key,
                    market=str(selection.market),
                    period=str(selection.period),
                    line=selection.line,
                    selection_code=selection.code,
                    selection_label=selection.label,
                    decimal_odds=snapshot.decimal_odds,
                    currency=snapshot.currency,
                    event_status=str(snapshot.event_status),
                    provider_updated_at=snapshot.provider_updated_at,
                    observed_at=snapshot.observed_at,
                    received_at=snapshot.received_at,
                    source_meta=dict(snapshot.source_meta),
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
                        candidate.event.canonical_id,
                        candidate.selection.key,
                        candidate.bookmaker,
                    ),
                    event_canonical_id=candidate.event.canonical_id,
                    selection_key=candidate.selection.key,
                    bookmaker=candidate.bookmaker,
                    decimal_odds=candidate.value.decimal_odds,
                    model_probability=candidate.value.model_probability,
                    ev=candidate.value.ev,
                    ev_conservative=candidate.value.ev_conservative,
                    data_quality=candidate.data_quality.score,
                    model_id=candidate.model_id,
                    validation_status=str(candidate.probability.validation_status),
                    observed_at=ensure_utc(candidate.observed_at),
                    document=_json_safe(candidate.model_dump(mode="json")),
                )
            )
        for rejection in result.rejections:
            self._session.add(
                RejectionRow(
                    scan_id=result.scan_id,
                    event_canonical_id=rejection.event_canonical_id,
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
