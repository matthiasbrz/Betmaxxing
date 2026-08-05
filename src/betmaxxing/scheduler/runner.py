"""Scheduler process.

Runs as a **separate process** from the web server: N web workers would fire
every job N times, and a scan holding a worker blocks request serving.

The execution loop is ledger-driven:

1. **discover** upcoming events and resolve them onto internal identity;
2. **materialise** the occurrences that should exist in the near future;
3. **claim** the ones that are due, atomically, taking a lease and a token;
4. **execute** each one — a milestone runs scoped to *its* event;
5. **acknowledge** only after the acquisition has durably persisted, and only
   when the result is explicitly a success.

Steps 1 and 5 are the ones the audit found wrong.

Step 1 previously passed the *provider's* event id straight into the job's
scope, while the analysis filter compares **internal** ids. The two are
different strings, so every milestone scan analysed zero events. Discovery now
resolves identity before planning, so a job's scope id is always an internal id.

Step 5 previously acknowledged anything that returned without raising. A
provider outage produces a scan document, so an outage was recorded as a
success and never retried. :func:`execute` now returns a typed
:class:`ExecutionResult` and only :data:`ExecutionOutcome.SUCCESS` acknowledges.
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from betmaxxing.config import Settings, get_settings
from betmaxxing.domain.enums import CollectionStatus
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.engine.acquisition import SPORTS_IN_SCOPE, AcquisitionService, FailureKind
from betmaxxing.scheduler.ledger import (
    DEFAULT_CATCHUP_GRACE,
    ClaimedJob,
    JobLedger,
    JobType,
    StaleLeaseError,
)
from betmaxxing.storage.db import create_all

logger = logging.getLogger("betmaxxing.scheduler")

POLL_SECONDS = 30

#: Collection statuses that describe a *completed* collection, whatever it found.
#: "No candidate", "no model" and "the bookmaker was absent from a valid
#: response" are answers, not faults, and must not be retried.
SUCCESSFUL_STATUSES = frozenset(
    {
        CollectionStatus.OK,
        CollectionStatus.NO_CANDIDATE,
        CollectionStatus.COLLECTED_NO_MODEL,
        CollectionStatus.COVERAGE_MISSING,
        CollectionStatus.DATA_STALE,
    }
)

#: Spread deferred jobs over this window past the reset boundary, so a fleet of
#: workers does not all wake at 00:00:00 and race for the fresh budget.
BUDGET_RESET_JITTER = timedelta(minutes=10)


class ExecutionOutcome(StrEnum):
    """What the runner must do next with a job it just executed."""

    SUCCESS = "SUCCESS"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    FINAL_FAILURE = "FINAL_FAILURE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    #: The lease expired while the work was running and another worker took over.
    #: Not a failure of the work — it may well have finished — but this attempt no
    #: longer owns the job and may not speak for it.
    LEASE_LOST = "LEASE_LOST"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    outcome: ExecutionOutcome
    scan_id: str | None
    collection_status: CollectionStatus | None
    detail: str = ""
    #: Deliberately no `retry_after`: when the budget is the blocker, *when* to
    #: try again is a property of the UTC reset boundary and of the job's own
    #: deadline, not of the result. Carrying a flat delay here is what produced
    #: "six hours" and called it "past midnight".

    @property
    def is_success(self) -> bool:
        return self.outcome is ExecutionOutcome.SUCCESS


def worker_name() -> str:
    """Identifies the lease holder in logs and in the ledger."""
    return f"{socket.gethostname()}:{os.getpid()}"


class LeaseGuard:
    """Keeps a claimed job's lease alive for as long as the work is running.

    Exposing :meth:`JobLedger.renew_lease` was not enough, because nothing called
    it. A scan that outlived its 15-minute lease was reclaimed and **executed a
    second time**: the fencing token stopped the first worker from acknowledging,
    but it could not undo the provider requests it had already paid for, the rows
    it had written, or the messages it had sent. Protecting the bookkeeping while
    the side effects happen twice is not protection.

    Properties this guarantees, each covered by a test:

    * renewal cadence strictly shorter than the lease (a third of it, floored at
      100 ms), derived from the lease rather than configured separately so the
      two cannot drift apart;
    * started before the long work and stopped-and-joined in a ``finally``, on
      success, on exception, and on lease loss;
    * every renewal reads the clock **at renewal time**, never a ``now`` captured
      when the pass began;
    * a lost lease is recorded rather than raised in the worker's thread, so the
      caller decides what to do with a result it can no longer publish.
    """

    #: Fraction of the lease between renewals.
    RENEWAL_FRACTION = 3
    MINIMUM_INTERVAL = timedelta(milliseconds=100)

    def __init__(
        self,
        ledger: JobLedger,
        job: ClaimedJob,
        *,
        clock: Any = utc_now,
        interval: timedelta | None = None,
    ) -> None:
        self._ledger = ledger
        self._job = job
        self._clock = clock
        self.interval = interval or max(ledger.lease / self.RENEWAL_FRACTION, self.MINIMUM_INTERVAL)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lost = False
        self.renewals = 0

    # -- state --------------------------------------------------------------
    @property
    def lost(self) -> bool:
        """True once a renewal was refused: another worker owns the job."""
        return self._lost

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def owns_lease(self) -> bool:
        """Whether it is still legitimate to produce an external effect."""
        if self._lost:
            return False
        try:
            self._ledger.assert_owns(self._job)
        except StaleLeaseError:
            self._lost = True
            return False
        return True

    # -- context manager -----------------------------------------------------
    def __enter__(self) -> LeaseGuard:
        self._stop.clear()
        # Renew once, synchronously, before the work starts. The claim stamped the
        # lease with the *planning* instant; the work runs on the wall clock, and
        # the gap between them is a window in which the lease can look expired to
        # another worker. Closing it here means the lease is valid from the first
        # instant of the work, not from one renewal interval in.
        self._renew_once()
        self._thread = threading.Thread(
            target=self._loop, name=f"lease-{self._job.job_id[:8]}", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=self.interval.total_seconds() * 5 + 5)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval.total_seconds()):
            if not self._renew_once():
                return

    def _renew_once(self) -> bool:
        """One renewal, reading the clock now. ``False`` means stop trying."""
        try:
            self._ledger.renew_lease(self._job, now=self._clock())
        except StaleLeaseError:
            logger.warning(
                "lease renewal refused; another worker owns this job",
                extra={"job_key": self._job.job_id},
            )
            self._lost = True
            return False
        except Exception:  # pragma: no cover - defensive
            logger.exception("lease renewal failed", extra={"job_key": self._job.job_id})
            return False
        self.renewals += 1
        return True


def milestones_for(
    settings: Settings, events: list[object], now: datetime
) -> list[tuple[str, datetime]]:
    """Pre-event rescoring instants for the given events.

    An instant equal to ``now`` is **due**, not past. An instant already behind
    us but inside the catch-up grace window is kept: with a 24 h scan window,
    the T-24 h milestone of an event inside that window is always slightly in
    the past at discovery time, so dropping every past instant silently deleted
    a configured rescoring point. Anything older than the grace window is
    dropped, because acting on it would produce a stale analysis.
    """
    out: list[tuple[str, datetime]] = []
    moment = ensure_utc(now)
    earliest = moment - DEFAULT_CATCHUP_GRACE
    for event in events:
        start = ensure_utc(event.start_time_utc)  # type: ignore[attr-defined]
        for hours in settings.milestone_hours:
            run_at = start - timedelta(hours=hours)
            if run_at >= start or run_at < earliest:
                continue
            out.append((event.internal_id, run_at))  # type: ignore[attr-defined]
    return out


def discover_events(
    settings: Settings, now: datetime, service: AcquisitionService | None = None
) -> list[object]:
    """List upcoming events **already resolved onto internal identity**.

    Returning provider ids here is what made every milestone analyse nothing:
    the job carried ``the_odds_api:evt-42`` while the analysis filter compares
    ``evt_9f3…``. Resolution happens once, here, so a milestone's scope id and
    the analysis filter always live in the same id space.
    """
    from betmaxxing.domain.timeutil import scan_window
    from betmaxxing.providers.base import ProviderError
    from betmaxxing.providers.factory import build_providers

    try:
        bundle = build_providers(settings, now)
        window = scan_window(now, settings.window_hours)
        events = list(bundle.odds.list_events(SPORTS_IN_SCOPE, window))  # type: ignore[attr-defined]
    except ProviderError as exc:
        logger.warning("event discovery unavailable, daily scans only: %s", exc)
        return []

    resolver = service or AcquisitionService(settings)
    return list(resolver.resolve_identities(events, provider=getattr(bundle.odds, "name", "")))


def execute(job: ClaimedJob, service: AcquisitionService) -> ExecutionResult:
    """Run one occurrence. A milestone is scoped to its own event."""
    scope = job.scope_id if job.is_event_scoped else None
    logger.info(
        "running job",
        extra={"job_key": job.job_id, "kind": str(job.job_type), "scope": scope},
    )
    result = service.run(scope_event_id=scope)
    scan = result.scan

    logger.info(
        "job complete",
        extra={
            "job_key": job.job_id,
            "scan_id": scan.scan_id,
            "status": str(scan.status),
            "collection_status": str(scan.collection_status),
            "candidates": len(scan.candidates),
            "snapshots_persisted": result.snapshots_persisted,
        },
    )

    if scan.collection_status in SUCCESSFUL_STATUSES:
        return ExecutionResult(
            outcome=ExecutionOutcome.SUCCESS,
            scan_id=scan.scan_id,
            collection_status=scan.collection_status,
        )

    detail = "; ".join(scan.warnings) or str(scan.collection_status)
    if result.failure is FailureKind.BUDGET:
        return ExecutionResult(
            outcome=ExecutionOutcome.BUDGET_EXHAUSTED,
            scan_id=scan.scan_id,
            collection_status=scan.collection_status,
            detail=detail,
        )
    if result.failure is FailureKind.CONFIGURATION:
        return ExecutionResult(
            outcome=ExecutionOutcome.FINAL_FAILURE,
            scan_id=scan.scan_id,
            collection_status=scan.collection_status,
            detail=detail,
        )
    return ExecutionResult(
        outcome=ExecutionOutcome.RETRYABLE_FAILURE,
        scan_id=scan.scan_id,
        collection_status=scan.collection_status,
        detail=detail,
    )


def tick(
    settings: Settings,
    now: datetime,
    *,
    ledger: JobLedger | None = None,
    service: AcquisitionService | None = None,
    worker: str | None = None,
    clock: Any = utc_now,
) -> list[ClaimedJob]:
    """One planning + execution pass. Returns the jobs that **succeeded**.

    ``now`` is the *planning* instant: it decides which occurrences exist and
    which are due. Completion uses ``clock()`` instead, read when the work
    actually ends — a scan can run for minutes, and stamping it with the instant
    the pass began makes the ledger's timestamps fiction.
    """
    ledger = ledger or JobLedger(settings)
    service = service or AcquisitionService(settings)
    who = worker or worker_name()
    moment = ensure_utc(now)

    events = discover_events(settings, moment, service)
    ledger.materialise(
        now=moment,
        daily_times=settings.scan_time_list,
        milestones=milestones_for(settings, events, moment),
    )

    executed: list[ClaimedJob] = []
    for job in ledger.claim_due(now=moment, worker=who):
        guard = LeaseGuard(ledger, job, clock=clock)
        try:
            with guard:
                outcome = execute(job, service)
        except Exception as exc:
            logger.exception("job raised", extra={"job_key": job.job_id})
            _finish(ledger, job, _failure(exc), now=clock(), settings=settings)
            continue

        if guard.lost:
            # The work already happened and cannot be recalled; what we must not
            # do is claim it as this attempt's result. Whoever holds the lease now
            # owns the outcome.
            logger.warning("lease lost during execution", extra={"job_key": job.job_id})
            continue

        if outcome.is_success:
            # Acknowledge only after the acquisition persisted its batch and scan.
            try:
                ledger.mark_succeeded(job, scan_id=outcome.scan_id, now=clock())
            except StaleLeaseError:
                logger.warning("lease lost before ack", extra={"job_key": job.job_id})
                continue
            executed.append(job)
            continue

        logger.warning(
            "job did not succeed",
            extra={
                "job_key": job.job_id,
                "outcome": str(outcome.outcome),
                "collection_status": str(outcome.collection_status),
            },
        )
        _finish(ledger, job, outcome, now=clock(), settings=settings)
    return executed


def _failure(exc: BaseException) -> ExecutionResult:
    return ExecutionResult(
        outcome=ExecutionOutcome.RETRYABLE_FAILURE,
        scan_id=None,
        collection_status=None,
        detail=repr(exc),
    )


def _finish(
    ledger: JobLedger,
    job: ClaimedJob,
    outcome: ExecutionResult,
    *,
    now: datetime,
    settings: Settings,
) -> None:
    """Apply a non-success outcome, tolerating a lease that already moved on."""
    detail = f"{outcome.outcome}: {outcome.detail}"
    try:
        if outcome.outcome is ExecutionOutcome.BUDGET_EXHAUSTED:
            _defer_for_budget(ledger, job, detail=detail, now=now, settings=settings)
        elif outcome.outcome is ExecutionOutcome.FINAL_FAILURE:
            ledger.mark_failed(job, error=detail, retryable=False, now=now)
        else:
            ledger.mark_failed(job, error=detail, retryable=True, now=now)
    except StaleLeaseError:
        logger.warning("lease lost before the outcome was recorded", extra={"job_key": job.job_id})


def _defer_for_budget(
    ledger: JobLedger,
    job: ClaimedJob,
    *,
    detail: str,
    now: datetime,
    settings: Settings,
) -> None:
    """Wait for the budget window, or admit the job has expired.

    Retrying inside the same UTC day cannot succeed, so the next attempt is the
    next reset boundary. But a job whose value expires before that boundary must
    not be deferred into irrelevance: a milestone whose event kicks off tonight,
    or a scan whose catch-up window closes first, is finished as
    ``SKIPPED_BUDGET`` with a reason.
    """
    reset = next_budget_reset(now, job_id=job.job_id)
    deadline = _job_deadline(settings, job)
    if deadline is not None and deadline <= reset:
        ledger.mark_skipped(
            job,
            reason=(
                f"{detail} — budget épuisé et l'occurrence perd sa valeur avant le "
                f"prochain reset ({reset.isoformat()} > échéance {deadline.isoformat()}). "
                "Aucune nouvelle tentative."
            ),
            now=now,
        )
        return
    ledger.mark_deferred(
        job,
        reason=f"{detail} — report au prochain reset budgétaire UTC ({reset.isoformat()}).",
        next_attempt_at=reset,
        now=now,
    )


def _job_deadline(settings: Settings, job: ClaimedJob) -> datetime | None:
    """After this instant the occurrence has no value. ``None`` when unbounded."""
    if job.is_event_scoped and job.scope_id:
        start = _event_start(settings, job.scope_id)
        if start is not None:
            return start
    return ensure_utc(job.scheduled_for) + DEFAULT_CATCHUP_GRACE


def _event_start(settings: Settings, internal_id: str) -> datetime | None:
    from betmaxxing.domain.timeutil import from_storage
    from betmaxxing.storage.db import session_scope
    from betmaxxing.storage.tables import EventRow

    with session_scope(settings) as session:
        row = session.get(EventRow, internal_id)
        return from_storage(row.start_time_utc) if row is not None else None


def next_budget_reset(moment: datetime, *, job_id: str) -> datetime:
    """The next instant the provider's daily quota starts over, plus jitter.

    The provider's quota window is a UTC calendar day, so the boundary is the
    next UTC midnight — not "six hours from now", which was the previous
    behaviour and lands at 14:00 when the budget runs out at 08:00, squarely
    inside the same exhausted window.

    The jitter is derived from the job id, so it is stable across restarts (a
    random one would move the deadline on every pass) and spreads a fleet of
    workers over a few minutes instead of releasing them all at 00:00:00.
    """
    current = ensure_utc(moment)
    boundary = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    digest = hashlib.sha256(job_id.encode()).digest()
    jitter = int.from_bytes(digest[:2], "big") % int(BUDGET_RESET_JITTER.total_seconds())
    return boundary + timedelta(seconds=jitter)


def main() -> None:  # pragma: no cover - long-running loop
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    if not settings.scheduler_enabled:
        logger.warning(
            "BETMAXXING_SCHEDULER_ENABLED est faux — le planificateur ne fera rien. "
            "Un ordinateur local éteint n'exécute aucune tâche : un hébergement "
            "persistant est requis pour des alertes continues."
        )
        return

    create_all(settings)
    ledger = JobLedger(settings)
    service = AcquisitionService(settings)
    who = worker_name()
    logger.info("scheduler started as %s", who)

    while True:
        try:
            tick(settings, utc_now(), ledger=ledger, service=service, worker=who)
        except Exception:
            logger.exception("scheduler tick failed; continuing")
        time.sleep(POLL_SECONDS)


__all__ = [
    "BUDGET_RESET_JITTER",
    "ExecutionOutcome",
    "ExecutionResult",
    "JobType",
    "LeaseGuard",
    "discover_events",
    "execute",
    "main",
    "milestones_for",
    "next_budget_reset",
    "tick",
    "worker_name",
]


if __name__ == "__main__":  # pragma: no cover
    main()
