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

import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

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

#: How long to wait after hitting the provider's daily ceiling. Retrying inside
#: the same UTC day cannot succeed, so the next attempt is pushed past midnight.
BUDGET_RETRY_DELAY = timedelta(hours=6)


class ExecutionOutcome(StrEnum):
    """What the runner must do next with a job it just executed."""

    SUCCESS = "SUCCESS"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    FINAL_FAILURE = "FINAL_FAILURE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    outcome: ExecutionOutcome
    scan_id: str | None
    collection_status: CollectionStatus | None
    detail: str = ""
    retry_after: timedelta | None = None

    @property
    def is_success(self) -> bool:
        return self.outcome is ExecutionOutcome.SUCCESS


def worker_name() -> str:
    """Identifies the lease holder in logs and in the ledger."""
    return f"{socket.gethostname()}:{os.getpid()}"


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
            retry_after=BUDGET_RETRY_DELAY,
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
) -> list[ClaimedJob]:
    """One planning + execution pass. Returns the jobs that **succeeded**."""
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
        try:
            outcome = execute(job, service)
        except Exception as exc:
            logger.exception("job raised", extra={"job_key": job.job_id})
            _safe_fail(ledger, job, error=repr(exc), retryable=True, now=moment)
            continue

        if outcome.is_success:
            # Acknowledge only after the acquisition persisted its batch and scan.
            try:
                ledger.mark_succeeded(job, scan_id=outcome.scan_id, now=moment)
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
        _safe_fail(
            ledger,
            job,
            error=f"{outcome.outcome}: {outcome.detail}",
            retryable=outcome.outcome is not ExecutionOutcome.FINAL_FAILURE,
            retry_after=outcome.retry_after,
            now=moment,
        )
    return executed


def _safe_fail(
    ledger: JobLedger,
    job: ClaimedJob,
    *,
    error: str,
    retryable: bool,
    now: datetime,
    retry_after: timedelta | None = None,
) -> None:
    """Record a failure, tolerating the case where the lease already moved on."""
    try:
        ledger.mark_failed(job, error=error, retryable=retryable, retry_after=retry_after, now=now)
    except StaleLeaseError:
        logger.warning("lease lost before failure was recorded", extra={"job_key": job.job_id})


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
    "ExecutionOutcome",
    "ExecutionResult",
    "JobType",
    "discover_events",
    "execute",
    "main",
    "milestones_for",
    "tick",
    "worker_name",
]


if __name__ == "__main__":  # pragma: no cover
    main()
