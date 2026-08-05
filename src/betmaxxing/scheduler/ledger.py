"""Durable scheduler ledger.

Replaces the previous ``plan(now)`` + ``due_jobs(now)`` pair, which could never
fire: planning dropped occurrences at or before ``now`` while selection kept only
occurrences at or before ``now``, so the intersection was empty by construction.

The model here is the standard one for reliable job execution:

* occurrences are **materialised** into a table ahead of time by
  :meth:`JobLedger.materialise`, with a unique constraint on
  ``(job_type, scheduled_for, scope_id)`` making enqueue idempotent;
* a worker **claims** due occurrences atomically and takes a **lease**;
* a job is marked ``SUCCEEDED`` only *after* its work is durably persisted;
* an expired lease is reclaimable, so a crashed worker does not strand a job.

Concurrency guarantee, stated precisely
---------------------------------------
Claiming does a conditional UPDATE (``WHERE job_id = ... AND state = 'PENDING'``)
and treats "0 rows updated" as "someone else took it". On PostgreSQL this is
serialised by row locking. On SQLite it is serialised by the database-level write
lock. Both are safe for **multiple workers against one database**.

What is *not* claimed: nothing here coordinates across databases, and the
catch-up policy is deliberately bounded rather than replaying an unbounded
backlog. See docs/scheduler.md.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update

from betmaxxing.config import Settings
from betmaxxing.domain.timeutil import PARIS, ensure_utc, from_storage, to_display, utc_now
from betmaxxing.storage.db import session_scope
from betmaxxing.storage.tables import SchedulerJobRow

logger = logging.getLogger("betmaxxing.scheduler")

#: How long a claimed job may run before another worker may reclaim it.
DEFAULT_LEASE = timedelta(minutes=15)
#: Occurrences older than this at materialisation time are dropped rather than
#: replayed. Prevents a restart after a long outage firing a burst of stale scans.
DEFAULT_CATCHUP_GRACE = timedelta(hours=2)
#: Retry ceiling before a job is parked as FAILED_FINAL.
MAX_ATTEMPTS = 3


class JobType(StrEnum):
    DAILY_SCAN = "DAILY_SCAN"
    EVENT_MILESTONE = "EVENT_MILESTONE"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A job this worker now owns for the duration of its lease."""

    job_id: str
    job_type: JobType
    scheduled_for: datetime
    #: Event internal id for a milestone, ``None`` for a global scan.
    scope_id: str | None
    attempts: int

    @property
    def is_event_scoped(self) -> bool:
        return self.job_type is JobType.EVENT_MILESTONE and bool(self.scope_id)


def occurrence_id(job_type: JobType, scheduled_for: datetime, scope_id: str) -> str:
    """Deterministic id for one occurrence — the idempotency key."""
    stamp = ensure_utc(scheduled_for).replace(second=0, microsecond=0).isoformat()
    raw = f"{job_type}|{stamp}|{scope_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class JobLedger:
    """SQL-backed occurrence store."""

    def __init__(self, settings: Settings, lease: timedelta = DEFAULT_LEASE) -> None:
        self._settings = settings
        self._lease = lease

    # -- writing ------------------------------------------------------------
    def enqueue(
        self,
        *,
        job_type: JobType,
        scheduled_for: datetime,
        scope_id: str | None,
        now: datetime | None = None,
    ) -> str | None:
        """Insert one occurrence. Returns its id, or ``None`` if it already existed."""
        moment = ensure_utc(now or utc_now())
        scope = scope_id or ""
        when = ensure_utc(scheduled_for).replace(second=0, microsecond=0)
        job_id = occurrence_id(job_type, when, scope)

        with session_scope(self._settings) as session:
            if session.get(SchedulerJobRow, job_id) is not None:
                return None
            session.add(
                SchedulerJobRow(
                    job_id=job_id,
                    job_type=str(job_type),
                    scheduled_for=when,
                    scope_id=scope,
                    state=str(JobState.PENDING),
                    attempts=0,
                    created_at=moment,
                )
            )
        return job_id

    def materialise(
        self,
        *,
        now: datetime,
        daily_times: list[str],
        milestones: list[tuple[str, datetime]],
        horizon: timedelta = timedelta(days=2),
        catchup_grace: timedelta = DEFAULT_CATCHUP_GRACE,
    ) -> int:
        """Create the occurrences that should exist, and return how many are new.

        Daily times are interpreted in ``Europe/Paris`` and converted to UTC, so
        "08:00" stays 08:00 locally across a DST change. Occurrences older than
        ``catchup_grace`` are skipped: replaying a day of missed scans after an
        outage would burn provider quota to produce stale analyses.
        """
        moment = ensure_utc(now)
        created = 0
        earliest = moment - catchup_grace

        local_now = to_display(moment, PARIS)
        for day_offset in range(-1, int(horizon.days) + 1):
            day = (local_now + timedelta(days=day_offset)).date()
            for entry in daily_times:
                hour_str, _, minute_str = entry.partition(":")
                try:
                    hour, minute = int(hour_str), int(minute_str or 0)
                except ValueError:
                    logger.warning("ignoring malformed scan time %r", entry)
                    continue
                local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS)
                run_at = ensure_utc(local)
                if run_at < earliest or run_at > moment + horizon:
                    continue
                if self.enqueue(
                    job_type=JobType.DAILY_SCAN,
                    scheduled_for=run_at,
                    scope_id=None,
                    now=moment,
                ):
                    created += 1

        for event_id, run_at in milestones:
            run_at = ensure_utc(run_at)
            if run_at < earliest or run_at > moment + horizon:
                continue
            if self.enqueue(
                job_type=JobType.EVENT_MILESTONE,
                scheduled_for=run_at,
                scope_id=event_id,
                now=moment,
            ):
                created += 1

        return created

    # -- reading / claiming -------------------------------------------------
    def claim_due(self, *, now: datetime, worker: str, limit: int = 10) -> list[ClaimedJob]:
        """Atomically take ownership of up to ``limit`` due occurrences.

        Due means ``scheduled_for <= now`` and either ``PENDING``,
        ``FAILED_RETRYABLE`` under the attempt ceiling, or ``RUNNING`` with an
        expired lease (the crashed-worker recovery path).
        """
        moment = ensure_utc(now)
        expiry = moment + self._lease
        claimed: list[ClaimedJob] = []

        with session_scope(self._settings) as session:
            rows = session.scalars(
                select(SchedulerJobRow)
                .where(SchedulerJobRow.scheduled_for <= moment)
                .order_by(SchedulerJobRow.scheduled_for)
                .limit(limit * 4)
            ).all()

            for row in rows:
                if len(claimed) >= limit:
                    break
                if not self._is_claimable(row, moment):
                    continue

                # Snapshot everything needed *before* the UPDATE: SQLAlchemy
                # synchronises matching in-session objects, so reading
                # `row.attempts` afterwards returns the already-incremented
                # value and would double-count the attempt.
                job_id = row.job_id
                job_type = JobType(row.job_type)
                scheduled_for = from_storage(row.scheduled_for)
                scope = row.scope_id or None
                next_attempt = row.attempts + 1
                expected_state = row.state

                # Conditional update: whoever changes the row first wins.
                result = session.execute(
                    update(SchedulerJobRow)
                    .where(
                        SchedulerJobRow.job_id == job_id,
                        SchedulerJobRow.state == expected_state,
                    )
                    .values(
                        state=str(JobState.RUNNING),
                        attempts=next_attempt,
                        started_at=moment,
                        lease_owner=worker,
                        lease_expires_at=expiry,
                    )
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    continue

                claimed.append(
                    ClaimedJob(
                        job_id=job_id,
                        job_type=job_type,
                        scheduled_for=scheduled_for,
                        scope_id=scope,
                        attempts=next_attempt,
                    )
                )
        return claimed

    def _is_claimable(self, row: SchedulerJobRow, moment: datetime) -> bool:
        state = JobState(row.state)
        if state is JobState.PENDING:
            return True
        if state is JobState.FAILED_RETRYABLE:
            return row.attempts < MAX_ATTEMPTS
        if state is JobState.RUNNING:
            # Reclaim only after the lease has genuinely expired.
            return (
                row.lease_expires_at is not None
                and from_storage(row.lease_expires_at) <= moment
                and row.attempts < MAX_ATTEMPTS
            )
        return False

    # -- completion ---------------------------------------------------------
    def mark_succeeded(
        self, job_id: str, *, scan_id: str | None = None, now: datetime | None = None
    ) -> None:
        """Call only after the corresponding work is durably persisted."""
        self._finish(job_id, JobState.SUCCEEDED, now=now, scan_id=scan_id)

    def mark_failed(
        self, job_id: str, *, error: str, retryable: bool = True, now: datetime | None = None
    ) -> None:
        with session_scope(self._settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            if row is None:
                return
            final = not retryable or row.attempts >= MAX_ATTEMPTS
            row.state = str(JobState.FAILED_FINAL if final else JobState.FAILED_RETRYABLE)
            row.finished_at = ensure_utc(now or utc_now())
            row.error = error[:2000]
            row.lease_owner = None
            row.lease_expires_at = None

    def _finish(
        self,
        job_id: str,
        state: JobState,
        *,
        now: datetime | None,
        scan_id: str | None = None,
    ) -> None:
        with session_scope(self._settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            if row is None:
                return
            row.state = str(state)
            row.finished_at = ensure_utc(now or utc_now())
            row.lease_owner = None
            row.lease_expires_at = None
            row.error = None
            if scan_id:
                row.scan_id = scan_id

    # -- inspection ---------------------------------------------------------
    def get_state(self, job_id: str) -> JobState | None:
        with session_scope(self._settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            return JobState(row.state) if row else None

    def counts_by_state(self) -> dict[str, int]:
        with session_scope(self._settings) as session:
            rows = session.scalars(select(SchedulerJobRow)).all()
            out: dict[str, int] = {}
            for row in rows:
                out[row.state] = out.get(row.state, 0) + 1
            return out

    def pending_count(self, now: datetime | None = None) -> int:
        moment = ensure_utc(now or utc_now())
        with session_scope(self._settings) as session:
            rows = session.scalars(
                select(SchedulerJobRow).where(
                    SchedulerJobRow.state == str(JobState.PENDING),
                    SchedulerJobRow.scheduled_for <= moment,
                )
            ).all()
            return len(rows)
