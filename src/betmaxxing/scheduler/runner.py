"""Scheduler process.

Runs as a **separate process** from the web server: N web workers would fire
every job N times, and a scan holding a worker blocks request serving.

The execution loop is now ledger-driven:

1. **materialise** the occurrences that should exist in the near future;
2. **claim** the ones that are due, atomically, taking a lease;
3. **execute** each one — a milestone runs scoped to *its* event;
4. **acknowledge** only after the acquisition has durably persisted.

Step 4 is the ordering that matters. Marking success before persistence would
let a crash lose a batch that the ledger believes was collected.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime, timedelta

from betmaxxing.config import Settings, get_settings
from betmaxxing.domain.timeutil import ensure_utc, utc_now
from betmaxxing.engine.acquisition import SPORTS_IN_SCOPE, AcquisitionService
from betmaxxing.scheduler.ledger import ClaimedJob, JobLedger, JobType
from betmaxxing.storage.db import create_all

logger = logging.getLogger("betmaxxing.scheduler")

POLL_SECONDS = 30


def worker_name() -> str:
    """Identifies the lease holder in logs and in the ledger."""
    return f"{socket.gethostname()}:{os.getpid()}"


def milestones_for(
    settings: Settings, events: list[object], now: datetime
) -> list[tuple[str, datetime]]:
    """Pre-event rescoring instants that still lie in the future."""
    out: list[tuple[str, datetime]] = []
    moment = ensure_utc(now)
    for event in events:
        start = ensure_utc(event.start_time_utc)  # type: ignore[attr-defined]
        for hours in settings.milestone_hours:
            run_at = start - timedelta(hours=hours)
            if run_at <= moment or run_at >= start:
                continue
            out.append((event.internal_id, run_at))  # type: ignore[attr-defined]
    return out


def discover_events(settings: Settings, now: datetime) -> list[object]:
    """List upcoming events for milestone planning, tolerating provider failure."""
    from betmaxxing.domain.timeutil import scan_window
    from betmaxxing.providers.base import ProviderError
    from betmaxxing.providers.factory import build_providers

    try:
        bundle = build_providers(settings, now)
        window = scan_window(now, settings.window_hours)
        return list(bundle.odds.list_events(SPORTS_IN_SCOPE, window))  # type: ignore[attr-defined]
    except ProviderError as exc:
        logger.warning("event discovery unavailable, daily scans only: %s", exc)
        return []


def execute(job: ClaimedJob, service: AcquisitionService) -> str:
    """Run one occurrence. A milestone is scoped to its own event."""
    scope = job.scope_id if job.is_event_scoped else None
    logger.info(
        "running job",
        extra={"job_key": job.job_id, "kind": str(job.job_type), "scope": scope},
    )
    result = service.run(scope_event_id=scope)
    logger.info(
        "job complete",
        extra={
            "job_key": job.job_id,
            "scan_id": result.scan.scan_id,
            "status": str(result.scan.status),
            "collection_status": str(result.scan.collection_status),
            "candidates": len(result.scan.candidates),
            "snapshots_persisted": result.snapshots_persisted,
        },
    )
    return result.scan.scan_id


def tick(
    settings: Settings,
    now: datetime,
    *,
    ledger: JobLedger | None = None,
    service: AcquisitionService | None = None,
    worker: str | None = None,
) -> list[ClaimedJob]:
    """One planning + execution pass. Returns the jobs actually executed."""
    ledger = ledger or JobLedger(settings)
    service = service or AcquisitionService(settings)
    who = worker or worker_name()
    moment = ensure_utc(now)

    events = discover_events(settings, moment)
    ledger.materialise(
        now=moment,
        daily_times=settings.scan_time_list,
        milestones=milestones_for(settings, events, moment),
    )

    executed: list[ClaimedJob] = []
    for job in ledger.claim_due(now=moment, worker=who):
        try:
            scan_id = execute(job, service)
        except Exception as exc:
            logger.exception("job failed", extra={"job_key": job.job_id})
            ledger.mark_failed(job.job_id, error=repr(exc), now=moment)
            continue
        # Acknowledge only after the acquisition persisted its batch and scan.
        ledger.mark_succeeded(job.job_id, scan_id=scan_id, now=moment)
        executed.append(job)
    return executed


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
