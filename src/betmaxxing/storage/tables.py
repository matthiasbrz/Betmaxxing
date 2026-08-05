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
    #: Order-sensitive participant key, used only for cross-provider matching.
    #: Identity itself is the opaque `canonical_id`, never this key.
    participant_pair_key: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    #: Matching signal: two fixtures between the same pair in different seasons
    #: are different fixtures, however close their kick-offs happen to be.
    season: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    #: Canonical decimal text of the line. Identity uses THIS, never `line`:
    #: a float rendering must not decide whether two prices are the same market.
    line_canonical: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    #: Collection batch that wrote this row, for provenance.
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class ScanRunRow(Base):
    __tablename__ = "scan_runs"

    scan_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    config_fingerprint: Mapped[str] = mapped_column(String(32), index=True)
    collection_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
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
    #: Nullable: no usable uncertainty method means no conservative EV (D-019).
    ev_conservative: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality: Mapped[float] = mapped_column(Float)
    model_id: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32))
    uncertainty_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    #: Optimistic concurrency token. Every mutation bumps it conditionally, so a
    #: rung cannot be settled twice by two concurrent requests.
    version: Mapped[int] = mapped_column(Integer, default=1)
    bank_cents: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class EventSourceMapRow(Base):
    """``(provider, provider_event_id) -> internal_id``.

    The authoritative resolution path. A provider keeping its own id stable
    across a postponement gives us a stable internal identity for free.
    """

    __tablename__ = "event_source_map"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_event_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(128))
    internal_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("events.canonical_id"), index=True
    )


class EventScheduleHistoryRow(Base):
    """Append-only trail of kick-off and status changes.

    A reschedule updates the event row *and* appends here, so "this match moved"
    stays visible instead of being overwritten.
    """

    __tablename__ = "event_schedule_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    internal_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("events.canonical_id"), index=True
    )
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_start_time_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ParticipantAliasRow(Base):
    """Alternate spellings of a team or player, per provider.

    The key includes ``source``: two providers may legitimately ship the same
    short form, and a ``(sport, alias)`` key let whichever was inserted first
    silently own it for everyone.
    """

    __tablename__ = "participant_aliases"
    __table_args__ = (
        UniqueConstraint("sport", "source", "alias", name="uq_participant_alias_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sport: Mapped[str] = mapped_column(String(32), index=True)
    alias: Mapped[str] = mapped_column(String(200))
    canonical_participant_id: Mapped[str] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(String(64), default="manual")


class SchedulerJobRow(Base):
    """Durable scheduler ledger.

    Replaces the in-memory ``completed`` set. The unique constraint on
    ``(job_type, scheduled_for, scope_id)`` is what makes enqueueing idempotent,
    and ``lease_expires_at`` is what lets a crashed worker's job be recovered.
    """

    __tablename__ = "scheduler_jobs"
    __table_args__ = (
        UniqueConstraint("job_type", "scheduled_for", "scope_id", name="uq_scheduler_occurrence"),
        Index("ix_scheduler_state_due", "state", "scheduled_for"),
        # Supports the claim query, which filters on state first so terminal
        # rows never enter the ORDER BY / LIMIT window.
        Index("ix_scheduler_claimable", "state", "scheduled_for", "next_attempt_at"),
    )

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: Event internal id for a milestone; empty string for a global scan
    #: (SQL treats NULLs as distinct, which would defeat the unique constraint).
    scope_id: Mapped[str] = mapped_column(String(64), default="")
    state: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Fencing token, regenerated on every claim. Completing a job requires
    #: presenting the token the claim handed out, so a worker that lost its
    #: lease cannot finish (or fail) the attempt that replaced it.
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Earliest instant a FAILED_RETRYABLE job may be claimed again. Without it
    #: the runner re-claims a failing job on the very next loop iteration.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CollectionBatchRow(Base):
    """One provider collection, whether or not it produced candidates.

    Recorded even when no model exists: the source data is the irreplaceable
    part, and "we collected and stored real prices" must be provable.
    """

    __tablename__ = "collection_batches"

    batch_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mode: Mapped[str] = mapped_column(String(32))
    events_seen: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_seen: Mapped[int] = mapped_column(Integer, default=0)
    events_persisted: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_persisted: Mapped[int] = mapped_column(Integer, default=0)
    coverage_status: Mapped[str] = mapped_column(String(32), default="OK")
    partial_errors: Mapped[dict] = mapped_column(JSON, default=dict)
    quota: Mapped[dict] = mapped_column(JSON, default=dict)


class EventMappingReviewRow(Base):
    """Provider events whose internal identity could not be decided.

    An ambiguity creates a row here and *nothing else*: no mapping, no event, no
    snapshot. Attributing a price to whichever fixture sorted first is worse
    than declining to price it, so the decision is deferred to a human.
    """

    __tablename__ = "event_mapping_reviews"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_mapping_review"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(128))
    sport: Mapped[str] = mapped_column(String(32))
    competition: Mapped[str] = mapped_column(String(160))
    home_name: Mapped[str] = mapped_column(String(160))
    away_name: Mapped[str] = mapped_column(String(160))
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    candidate_internal_ids: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    #: Audit trail of the human decision. A queue with no record of who decided
    #: what, and when, is not reviewable after the fact.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_internal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class NotificationOutboxRow(Base):
    """At-most-once external effects, keyed by the job that produced them.

    A fencing token stops a worker that lost its lease from acknowledging. It
    cannot unsend a message. So the send itself has to be idempotent: claiming a
    row here is what authorises one delivery, and the unique constraint is what
    makes a re-executed job silent rather than noisy.
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("job_id", "alert_key", "channel", name="uq_notification_effect"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    alert_key: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderBudgetDayRow(Base):
    """The **synchronisation point** for one provider's daily spend.

    Exactly one row per ``(provider, day_utc)``. Reserving is a single
    conditional UPDATE against it:

    .. code-block:: sql

        UPDATE provider_budget_days
           SET reserved_total = reserved_total + :cost
         WHERE provider = :p AND day_utc = :d
           AND reserved_total + :cost <= :ceiling

    That is atomic on both engines. PostgreSQL takes a row lock and
    **re-evaluates the WHERE clause against the updated row** once the lock is
    released, so a second transaction sees the first one's increment and its own
    condition fails. SQLite serialises writers outright.

    The previous design read ``SELECT SUM(...)`` over the detail table and then
    inserted. Under SQLite that happens to look atomic because every writer is
    serialised anyway; under PostgreSQL in ``READ COMMITTED`` both transactions
    read the same total and both insert, so two reservations that each fit alone
    together overshoot the ceiling. The detail table is still written — it is the
    audit trail — but it is no longer the primitive anything synchronises on.
    """

    __tablename__ = "provider_budget_days"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: ``YYYY-MM-DD`` in UTC: the provider's quota window is a UTC calendar day,
    #: so a local-time window would leak spend across the boundary.
    day_utc: Mapped[str] = mapped_column(String(10), primary_key=True)
    #: Authoritative committed spend for the day. Never negative.
    reserved_total: Mapped[int] = mapped_column(Integer, default=0)
    #: Sum of costs the provider actually reported, for reconciliation reporting.
    observed_total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderBudgetLedgerRow(Base):
    """Audit detail: one row per attempted provider request.

    Reserved cost, the cost the provider reported, and whether the reservation
    was released because the request demonstrably never arrived. Read for
    reporting and reconciliation; never used as a lock.
    """

    __tablename__ = "provider_budget_ledger"
    __table_args__ = (Index("ix_budget_provider_day", "provider", "day_utc"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64))
    #: UTC calendar day, ``YYYY-MM-DD``. The provider's quota window is UTC, so
    #: a local-time window would leak spend across the boundary.
    day_utc: Mapped[str] = mapped_column(String(10))
    request: Mapped[str] = mapped_column(String(200))
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    reserved_cost: Mapped[int] = mapped_column(Integer, default=0)
    #: ``None`` until the response is reconciled; 0 once released.
    observed_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelRegistryRow(Base):
    """Persistent validation status per model version.

    The source of truth for whether a model's output may be published. A model
    absent from this table is treated as ``BACKTEST_ONLY``.
    """

    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    sport: Mapped[str] = mapped_column(String(32), index=True)
    validation_status: Mapped[str] = mapped_column(String(32), default="BACKTEST_ONLY")
    uncertainty_method: Mapped[str] = mapped_column(String(64), default="none")
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
