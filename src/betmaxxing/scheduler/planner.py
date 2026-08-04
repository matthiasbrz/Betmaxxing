"""Scan planning.

The planner is pure: it turns "now + the events I know about" into "the instants
at which I should scan", with no side effects. That makes the schedule testable
and keeps the runner (which does have side effects) trivial.

Two kinds of trigger:

* **daily scans** at configured local times, converted through ``Europe/Paris``
  so a DST change moves them by the right amount rather than drifting an hour;
* **milestones** before each event (T-24h, T-12h, ... T-15min), which is where
  prices actually move.

Every job carries a deterministic ``job_key``. The runner uses it as an
idempotency key, so a restart mid-run cannot double-execute a milestone, and a
second worker process cannot duplicate one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from betmaxxing.config import Settings
from betmaxxing.domain.models import CanonicalEvent
from betmaxxing.domain.timeutil import PARIS, ensure_utc, to_display


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """One planned scan."""

    run_at_utc: datetime
    kind: str
    job_key: str
    event_canonical_id: str | None = None
    detail: str = ""


def _job_key(kind: str, run_at: datetime, subject: str) -> str:
    raw = f"{kind}|{run_at.replace(second=0, microsecond=0).isoformat()}|{subject}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def daily_jobs(settings: Settings, now: datetime, days: int = 2) -> list[ScheduledJob]:
    """Daily scans at the configured local times, for the next ``days`` days.

    Times are interpreted in the display timezone and converted back to UTC, so
    "08:00 Paris" stays 08:00 Paris across a DST boundary.
    """
    out: list[ScheduledJob] = []
    local_now = to_display(now, PARIS)
    for day_offset in range(days + 1):
        day = (local_now + timedelta(days=day_offset)).date()
        for entry in settings.scan_time_list:
            hour_str, _, minute_str = entry.partition(":")
            try:
                hour, minute = int(hour_str), int(minute_str or 0)
            except ValueError:
                continue
            local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS)
            run_at = ensure_utc(local)
            if run_at <= now:
                continue
            out.append(
                ScheduledJob(
                    run_at_utc=run_at,
                    kind="daily",
                    job_key=_job_key("daily", run_at, entry),
                    detail=f"Scan quotidien {entry} (Europe/Paris).",
                )
            )
    return sorted(out, key=lambda j: j.run_at_utc)


def milestone_jobs(
    settings: Settings, now: datetime, events: list[CanonicalEvent]
) -> list[ScheduledJob]:
    """Pre-event rescoring milestones that still lie in the future."""
    out: list[ScheduledJob] = []
    for event in events:
        start = ensure_utc(event.start_time_utc)
        for hours in settings.milestone_hours:
            run_at = start - timedelta(hours=hours)
            if run_at <= now or run_at >= start:
                continue
            label = f"T-{hours:g}h"
            out.append(
                ScheduledJob(
                    run_at_utc=run_at,
                    kind="milestone",
                    job_key=_job_key("milestone", run_at, f"{event.canonical_id}|{label}"),
                    event_canonical_id=event.canonical_id,
                    detail=f"Rescoring {label} — {event.label}.",
                )
            )
    return sorted(out, key=lambda j: j.run_at_utc)


def plan(
    settings: Settings, now: datetime, events: list[CanonicalEvent], days: int = 2
) -> list[ScheduledJob]:
    """Full schedule, deduplicated on ``job_key``."""
    if not settings.scheduler_enabled:
        return []
    seen: set[str] = set()
    out: list[ScheduledJob] = []
    for job in daily_jobs(settings, now, days) + milestone_jobs(settings, now, events):
        if job.job_key in seen:
            continue
        seen.add(job.job_key)
        out.append(job)
    return sorted(out, key=lambda j: j.run_at_utc)


def due_jobs(jobs: list[ScheduledJob], now: datetime, completed: set[str]) -> list[ScheduledJob]:
    """Jobs whose time has come and that have not already run.

    ``completed`` is the idempotency ledger: passing the previously executed
    ``job_key`` set makes re-entry after a crash a no-op for work already done.
    """
    moment = ensure_utc(now)
    return [j for j in jobs if j.run_at_utc <= moment and j.job_key not in completed]


def should_rescore(previous_odds: float, current_odds: float, threshold: float = 0.02) -> bool:
    """Whether a price move is large enough to justify an out-of-band rescore."""
    if previous_odds <= 0:
        return True
    return abs(current_odds - previous_odds) / previous_odds >= threshold
