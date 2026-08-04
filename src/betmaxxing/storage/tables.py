"""Persistence schema.

Design notes:

* ``odds_snapshots`` is append-only. There is no update path in the repository
  layer, and ``fingerprint`` is UNIQUE so replaying an ingest is idempotent.
* Every timestamp column stores UTC. SQLite has no native tz-aware type, so the
  repository layer normalises on the way in and out rather than trusting the
  driver.
* ``scan_runs`` keeps the full result document plus the config fingerprint, which
  is what makes a run reproducible after the fact.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    canonical_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sport: Mapped[str] = mapped_column(String(32), index=True)
    competition: Mapped[str] = mapped_column(String(160))
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    surface: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sets_to_win: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_name: Mapped[str] = mapped_column(String(160))
    away_name: Mapped[str] = mapped_column(String(160))
    home_canonical_id: Mapped[str] = mapped_column(String(160), index=True)
    away_canonical_id: Mapped[str] = mapped_column(String(160), index=True)
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    mapping_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    source_ids: Mapped[dict] = mapped_column(JSON, default=dict)


class OddsSnapshotRow(Base):
    """Immutable. Never updated — a new price is a new row."""

    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_odds_fingerprint"),
        Index("ix_odds_event_selection", "event_canonical_id", "selection_key"),
        Index("ix_odds_observed_at", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64), index=True)
    bookmaker: Mapped[str] = mapped_column(String(64), index=True)
    event_canonical_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("events.canonical_id"), index=True
    )
    event_source_id: Mapped[str] = mapped_column(String(128))
    selection_key: Mapped[str] = mapped_column(String(160))
    market: Mapped[str] = mapped_column(String(48))
    period: Mapped[str] = mapped_column(String(32))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    selection_code: Mapped[str] = mapped_column(String(48))
    selection_label: Mapped[str] = mapped_column(String(200))
    decimal_odds: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    event_status: Mapped[str] = mapped_column(String(32), default="scheduled")
    provider_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ScanRunRow(Base):
    __tablename__ = "scan_runs"

    scan_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    config_fingerprint: Mapped[str] = mapped_column(String(32), index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Full ScanResult document, for exact reproduction and audit.
    document: Mapped[dict] = mapped_column(JSON)


class CandidateRow(Base):
    __tablename__ = "candidates"
    __table_args__ = (Index("ix_candidate_scan", "scan_id"),)

    candidate_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scan_id: Mapped[str] = mapped_column(String(32), ForeignKey("scan_runs.scan_id"))
    alert_key: Mapped[str] = mapped_column(String(32), index=True)
    event_canonical_id: Mapped[str] = mapped_column(String(64), index=True)
    selection_key: Mapped[str] = mapped_column(String(160))
    bookmaker: Mapped[str] = mapped_column(String(64))
    decimal_odds: Mapped[float] = mapped_column(Float)
    model_probability: Mapped[float] = mapped_column(Float)
    ev: Mapped[float] = mapped_column(Float, index=True)
    ev_conservative: Mapped[float] = mapped_column(Float)
    data_quality: Mapped[float] = mapped_column(Float)
    model_id: Mapped[str] = mapped_column(String(64))
    validation_status: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    document: Mapped[dict] = mapped_column(JSON)


class RejectionRow(Base):
    __tablename__ = "rejections"
    __table_args__ = (Index("ix_rejection_scan", "scan_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(String(32), ForeignKey("scan_runs.scan_id"))
    event_canonical_id: Mapped[str] = mapped_column(String(64), index=True)
    event_label: Mapped[str] = mapped_column(String(320))
    selection_key: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(48), index=True)
    detail: Mapped[str] = mapped_column(Text)


class AlertRow(Base):
    """What has been notified, so repeat scans stay quiet."""

    __tablename__ = "alerts"

    alert_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    decimal_odds: Mapped[float] = mapped_column(Float)
    ev: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChallengeRow(Base):
    __tablename__ = "challenges"

    challenge_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    document: Mapped[dict] = mapped_column(JSON)


class ChallengeStepRow(Base):
    __tablename__ = "challenge_steps"
    __table_args__ = (UniqueConstraint("challenge_id", "step_index", name="uq_challenge_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    challenge_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("challenges.challenge_id"), index=True
    )
    step_index: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
