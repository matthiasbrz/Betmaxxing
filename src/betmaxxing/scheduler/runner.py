"""Scheduler process.

Runs as a **separate process** from the web server. Two reasons, both learned the
hard way by everyone who has not done it: a web server with N workers would fire
every job N times, and a scan holding a worker blocks request serving.

An in-process lock file provides the "distributed lock or equivalent" the design
calls for at single-host scale. It is deliberately simple and its limits are
stated in docs/scheduler.md: it protects against two workers on one machine, not
against two machines. Moving to a database advisory lock is a contained change.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from betmaxxing.config import Settings, get_settings
from betmaxxing.domain.timeutil import utc_now
from betmaxxing.engine.scan import run_scan
from betmaxxing.scheduler.planner import ScheduledJob, due_jobs, plan
from betmaxxing.storage.db import create_all, session_scope
from betmaxxing.storage.repositories import ScanRepository

logger = logging.getLogger("betmaxxing.scheduler")

LOCK_PATH = Path(os.environ.get("BETMAXXING_LOCK_PATH", "/tmp/betmaxxing-scheduler.lock"))
POLL_SECONDS = 30


class LockHeld(RuntimeError):
    """Another scheduler process holds the lock."""


class ProcessLock:
    """Exclusive lock via ``O_CREAT | O_EXCL``. Released on exit."""

    def __init__(self, path: Path = LOCK_PATH) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> ProcessLock:
        try:
            self._fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LockHeld(
                f"Un autre planificateur détient {self._path}. "
                "Supprimez le fichier si le processus précédent s'est arrêté brutalement."
            ) from exc
        os.write(self._fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
        self._path.unlink(missing_ok=True)


def execute(job: ScheduledJob, settings: Settings) -> str:
    """Run one job. Returns the scan id."""
    logger.info("running job", extra={"job_key": job.job_key, "kind": job.kind})
    result = run_scan(settings)
    with session_scope(settings) as session:
        ScanRepository(session).save(result)
    logger.info(
        "job complete",
        extra={
            "job_key": job.job_key,
            "scan_id": result.scan_id,
            "status": str(result.status),
            "candidates": len(result.candidates),
        },
    )
    return result.scan_id


def tick(settings: Settings, now: datetime, completed: set[str]) -> list[ScheduledJob]:
    """One planning + execution pass. Returns the jobs executed."""
    from betmaxxing.domain.timeutil import scan_window
    from betmaxxing.engine.scan import SPORTS_IN_SCOPE
    from betmaxxing.providers.base import ProviderUnavailable
    from betmaxxing.providers.factory import build_providers

    try:
        bundle = build_providers(settings, now)
        window = scan_window(now, settings.window_hours)
        events = bundle.odds.list_events(SPORTS_IN_SCOPE, window)  # type: ignore[attr-defined]
    except ProviderUnavailable as exc:
        logger.warning("providers unavailable, planning daily scans only: %s", exc)
        events = []

    jobs = plan(settings, now, events)
    ran: list[ScheduledJob] = []
    for job in due_jobs(jobs, now, completed):
        execute(job, settings)
        completed.add(job.job_key)
        ran.append(job)
    return ran


def main() -> None:  # pragma: no cover - long-running loop
    logging.basicConfig(
        level=get_settings().log_level,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.warning(
            "BETMAXXING_SCHEDULER_ENABLED est faux — le planificateur ne fera rien. "
            "Un ordinateur local éteint n'exécute aucune tâche : un hébergement "
            "persistant est requis pour des alertes continues."
        )
        return

    create_all(settings)
    completed: set[str] = set()
    with ProcessLock():
        logger.info("scheduler started")
        while True:
            try:
                tick(settings, utc_now(), completed)
            except Exception:
                logger.exception("scheduler tick failed; continuing")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":  # pragma: no cover
    main()
