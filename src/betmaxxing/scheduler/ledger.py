"""Durable scheduler ledger.

Replaces the previous ``plan(now)`` + ``due_jobs(now)`` pair, which could never
fire: planning dropped occurrences at or before ``now`` while selection kept only
occurrences at or before ``now``, so the intersection was empty by construction.

The model here is the standard one for reliable job execution:

* occurrences are **materialised** into a table ahead of time by
  :meth:`JobLedger.materialise`, with a unique constraint on
  ``(job_type, scheduled_for, scope_id)`` making enqueue idempotent — including
  when two workers insert the same occurrence at the same instant;
* a worker **claims** due occurrences atomically, taking a lease *and* a fresh
  **fencing token**;
* a job is marked ``SUCCEEDED`` only *after* its work is durably persisted, and
  only by the holder of the token the claim handed out;
* an expired lease is reclaimable, so a crashed worker does not strand a job.

Two properties the previous version claimed but did not have
-----------------------------------------------------------
**No starvation.** Claimable states are filtered in SQL, *before* ``ORDER BY``
and ``LIMIT``. The old query selected the oldest rows regardless of state and
filtered in Python, so a few dozen ``SUCCEEDED`` rows filled the window and a
genuinely due job was never reached.

**No stale completion.** Every terminal transition is a conditional UPDATE on
``(job_id, state=RUNNING, lease_owner, claim_token)``. A worker that lost its
lease during a pause changes zero rows and gets :class:`StaleLeaseError`. Simply
re-asserting ``state = 'RUNNING'`` was not enough: that is what the row already
said, so both a stale holder and a second reclaimer matched.

Concurrency guarantee, stated precisely
---------------------------------------
Multiple workers against **one** database are safe on PostgreSQL (row locking,
with ``SKIP LOCKED`` on the selection) and on SQLite (database-level write lock).
Both are exercised by tests; only SQLite is exercised in CI. Nothing here
coordinates across databases, and the catch-up policy is deliberately bounded
rather than replaying an unbounded backlog. See docs/scheduler.md.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError

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
#: Base delay before a retryable failure becomes claimable again. Doubles per
#: attempt. Without it the runner claims, fails and re-claims in a tight loop.
DEFAULT_RETRY_BACKOFF = timedelta(minutes=5)


class JobType(StrEnum):
    DAILY_SCAN = "DAILY_SCAN"
    EVENT_MILESTONE = "EVENT_MILESTONE"


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    #: Waiting for an external window to open — today, the provider's daily
    #: budget reset. Deliberately **not** a failure: it consumes no attempt and
    #: can never become ``FAILED_FINAL``. Folding "we are out of credits" into the
    #: provider-failure counter parked healthy jobs after three refusals.
    DEFERRED = "DEFERRED"
    #: Terminal: the budget was exhausted and the job will have no value by the
    #: time the budget returns (its event has started, or its catch-up window has
    #: closed). Recorded with a reason rather than deferred into irrelevance.
    SKIPPED_BUDGET = "SKIPPED_BUDGET"


#: The only states a claim may transition out of. ``SUCCEEDED``, ``FAILED_FINAL``
#: and ``SKIPPED_BUDGET`` are terminal and must never enter the selection window.
CLAIMABLE_STATES = frozenset(
    {
        JobState.PENDING,
        JobState.FAILED_RETRYABLE,
        JobState.RUNNING,
        JobState.DEFERRED,
    }
)


class StaleLeaseError(RuntimeError):
    """The caller no longer owns this job.

    Raised when a completion is attempted with a token that is not the current
    one — the job was reclaimed by another worker, or already finished.
    """


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A job this worker now owns for the duration of its lease."""

    job_id: str
    job_type: JobType
    scheduled_for: datetime
    #: Event internal id for a milestone, ``None`` for a global scan.
    scope_id: str | None
    attempts: int
    #: Fencing token. Required to complete the job; a stale holder does not have it.
    claim_token: str
    lease_expires_at: datetime | None = None

    @property
    def is_event_scoped(self) -> bool:
        return self.job_type is JobType.EVENT_MILESTONE and bool(self.scope_id)


def occurrence_id(job_type: JobType, scheduled_for: datetime, scope_id: str) -> str:
    """Deterministic id for one occurrence — the idempotency key."""
    stamp = ensure_utc(scheduled_for).replace(second=0, microsecond=0).isoformat()
    raw = f"{job_type}|{stamp}|{scope_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def new_claim_token() -> str:
    return uuid.uuid4().hex[:32]


class JobLedger:
    """SQL-backed occurrence store."""

    def __init__(
        self,
        settings: Settings,
        lease: timedelta = DEFAULT_LEASE,
        retry_backoff: timedelta = DEFAULT_RETRY_BACKOFF,
    ) -> None:
        self._settings = settings
        self._lease = lease
        self._retry_backoff = retry_backoff

    @property
    def lease(self) -> timedelta:
        """How long a claim is valid. The heartbeat derives its cadence from this."""
        return self._lease

    def assert_owns(self, job: ClaimedJob) -> None:
        """Raise unless this claim still owns the job.

        Checked before any **external** effect — a notification, anything that
        cannot be rolled back. A fencing token can stop a stale worker writing to
        the ledger; only asking first can stop it sending a message.
        """
        with session_scope(self._settings) as session:
            row = session.get(SchedulerJobRow, job.job_id)
            if (
                row is None
                or row.state != str(JobState.RUNNING)
                or row.claim_token != job.claim_token
            ):
                raise StaleLeaseError(
                    f"job {job.job_id} n'est plus détenu par ce worker — "
                    "aucun effet externe n'est autorisé."
                )

    # -- writing ------------------------------------------------------------
    def enqueue(
        self,
        *,
        job_type: JobType,
        scheduled_for: datetime,
        scope_id: str | None,
        now: datetime | None = None,
    ) -> str | None:
        """Insert one occurrence. Returns its id, or ``None`` if it already existed.

        "Already existed" covers the race: two workers materialising the same
        instant both see an empty table, both insert, and the unique constraint
        on ``(job_type, scheduled_for, scope_id)`` picks a winner. The loser
        treats the ``IntegrityError`` as "someone else enqueued it", which is
        exactly what happened.
        """
        moment = ensure_utc(now or utc_now())
        scope = scope_id or ""
        when = ensure_utc(scheduled_for).replace(second=0, microsecond=0)
        job_id = occurrence_id(job_type, when, scope)

        try:
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
        except IntegrityError:
            logger.debug("occurrence %s already enqueued by another worker", job_id)
            return None
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

        Due means ``scheduled_for <= now`` and one of:

        * ``PENDING``;
        * ``DEFERRED`` whose window has opened — no attempt ceiling applies,
          because waiting for a budget reset is not a failed attempt;
        * ``FAILED_RETRYABLE`` whose backoff has elapsed and which is under the
          attempt ceiling;
        * ``RUNNING`` with a genuinely expired lease (crashed-worker recovery).
        """
        moment = ensure_utc(now)
        expiry = moment + self._lease
        claimed: list[ClaimedJob] = []

        ready = SchedulerJobRow.next_attempt_at.is_(None) | (
            SchedulerJobRow.next_attempt_at <= moment
        )

        with session_scope(self._settings) as session:
            statement = (
                select(SchedulerJobRow)
                .where(
                    SchedulerJobRow.scheduled_for <= moment,
                    # Filtered here, in SQL, *before* ORDER BY and LIMIT. Doing
                    # it in Python let terminal rows fill the window.
                    or_(
                        (SchedulerJobRow.state == str(JobState.PENDING)) & ready,
                        (SchedulerJobRow.state == str(JobState.DEFERRED)) & ready,
                        (SchedulerJobRow.state == str(JobState.FAILED_RETRYABLE))
                        & (SchedulerJobRow.attempts < MAX_ATTEMPTS)
                        & ready,
                        (SchedulerJobRow.state == str(JobState.RUNNING))
                        & (SchedulerJobRow.attempts < MAX_ATTEMPTS)
                        & SchedulerJobRow.lease_expires_at.is_not(None)
                        & (SchedulerJobRow.lease_expires_at <= moment),
                    ),
                )
                .order_by(SchedulerJobRow.scheduled_for)
                .limit(limit)
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                # Two workers then never even see the same row. SQLite has no
                # equivalent and relies on the compare-and-swap below.
                statement = statement.with_for_update(skip_locked=True)

            rows = session.scalars(statement).all()

            for row in rows:
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
                expected_token = row.claim_token
                token = new_claim_token()

                # Compare-and-swap on state *and* token. Re-asserting the state
                # alone is not enough when reclaiming an expired RUNNING lease:
                # RUNNING is what the row already says, so a second reclaimer
                # would also match.
                condition = (
                    SchedulerJobRow.claim_token.is_(None)
                    if expected_token is None
                    else SchedulerJobRow.claim_token == expected_token
                )
                result = session.execute(
                    update(SchedulerJobRow)
                    .where(
                        SchedulerJobRow.job_id == job_id,
                        SchedulerJobRow.state == expected_state,
                        condition,
                    )
                    .values(
                        state=str(JobState.RUNNING),
                        attempts=next_attempt,
                        started_at=moment,
                        lease_owner=worker,
                        lease_expires_at=expiry,
                        claim_token=token,
                        next_attempt_at=None,
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
                        claim_token=token,
                        lease_expires_at=expiry,
                    )
                )
        return claimed

    # -- completion ---------------------------------------------------------
    def mark_succeeded(
        self,
        job: ClaimedJob | str,
        *,
        claim_token: str | None = None,
        scan_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Call only after the corresponding work is durably persisted.

        Accepts the :class:`ClaimedJob` itself so the token cannot be forgotten.
        """
        job_id, token = _identify(job, claim_token)
        moment = ensure_utc(now or utc_now())
        values: dict[str, object] = {
            "state": str(JobState.SUCCEEDED),
            "finished_at": moment,
            "lease_owner": None,
            "lease_expires_at": None,
            "claim_token": None,
            "next_attempt_at": None,
            "error": None,
        }
        if scan_id:
            values["scan_id"] = scan_id
        self._complete(job_id, token, values)

    def mark_failed(
        self,
        job: ClaimedJob | str,
        *,
        error: str,
        claim_token: str | None = None,
        retryable: bool = True,
        retry_after: timedelta | None = None,
        now: datetime | None = None,
    ) -> None:
        job_id, token = _identify(job, claim_token)
        moment = ensure_utc(now or utc_now())

        with session_scope(self._settings) as session:
            row = session.get(SchedulerJobRow, job_id)
            if row is None:
                raise StaleLeaseError(f"job {job_id} n'existe plus")
            attempts = row.attempts

        final = not retryable or attempts >= MAX_ATTEMPTS
        backoff = retry_after if retry_after is not None else self._backoff_for(attempts)
        self._complete(
            job_id,
            token,
            {
                "state": str(JobState.FAILED_FINAL if final else JobState.FAILED_RETRYABLE),
                "finished_at": moment,
                "error": error[:2000],
                "lease_owner": None,
                "lease_expires_at": None,
                "claim_token": None,
                "next_attempt_at": None if final else moment + backoff,
            },
        )

    def mark_deferred(
        self,
        job: ClaimedJob | str,
        *,
        reason: str,
        next_attempt_at: datetime,
        claim_token: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Park the job until an external window opens, consuming no attempt.

        The attempt counter is *decremented back* to what it was before the
        claim. That is the point: "the provider's daily budget is gone" is not a
        provider failure, and three of them in a row must not park a healthy job
        as ``FAILED_FINAL``.
        """
        job_id, token = _identify(job, claim_token)
        moment = ensure_utc(now or utc_now())
        self._complete(
            job_id,
            token,
            {
                "state": str(JobState.DEFERRED),
                "finished_at": moment,
                "error": reason[:2000],
                "lease_owner": None,
                "lease_expires_at": None,
                "claim_token": None,
                "next_attempt_at": ensure_utc(next_attempt_at),
                "attempts": _decremented_attempts(),
            },
        )

    def mark_skipped(
        self,
        job: ClaimedJob | str,
        *,
        reason: str,
        claim_token: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Terminal, and explicitly not a failure: the work lost its value."""
        job_id, token = _identify(job, claim_token)
        moment = ensure_utc(now or utc_now())
        self._complete(
            job_id,
            token,
            {
                "state": str(JobState.SKIPPED_BUDGET),
                "finished_at": moment,
                "error": reason[:2000],
                "lease_owner": None,
                "lease_expires_at": None,
                "claim_token": None,
                "next_attempt_at": None,
                "attempts": _decremented_attempts(),
            },
        )

    def renew_lease(self, job: ClaimedJob, *, now: datetime | None = None) -> datetime:
        """Extend a lease that is about to expire while work is still running.

        Guarded by the same fencing token: a worker whose lease already lapsed
        cannot take it back from whoever picked the job up.
        """
        moment = ensure_utc(now or utc_now())
        expiry = moment + self._lease
        self._complete(
            job.job_id,
            job.claim_token,
            {"lease_expires_at": expiry},
            keep_running=True,
        )
        return expiry

    def _backoff_for(self, attempts: int) -> timedelta:
        return self._retry_backoff * (2 ** max(attempts - 1, 0))

    def _complete(
        self,
        job_id: str,
        token: str | None,
        values: dict[str, object],
        *,
        keep_running: bool = False,
    ) -> None:
        """Conditional transition guarded by the fencing token."""
        with session_scope(self._settings) as session:
            result = session.execute(
                update(SchedulerJobRow)
                .where(
                    SchedulerJobRow.job_id == job_id,
                    SchedulerJobRow.state == str(JobState.RUNNING),
                    SchedulerJobRow.claim_token == token,
                )
                .values(**values)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise StaleLeaseError(
                    f"job {job_id} n'est plus détenu par ce worker (jeton périmé) — "
                    "aucune ligne modifiée. Une autre tentative est peut-être en cours."
                )
        if keep_running:
            return

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


def _identify(job: ClaimedJob | str, claim_token: str | None) -> tuple[str, str | None]:
    if isinstance(job, ClaimedJob):
        return job.job_id, job.claim_token
    return job, claim_token


def _decremented_attempts() -> Any:
    """SQL expression giving back the attempt this claim consumed, floored at 0.

    Expressed in SQL rather than read-then-write so it stays inside the same
    conditional UPDATE that checks the fencing token: two statements would let a
    reclaim slip between them.
    """
    return case(
        (SchedulerJobRow.attempts > 0, SchedulerJobRow.attempts - 1),
        else_=0,
    )
