"""Milestone/daily instant computation.

Superseded as an execution mechanism by :mod:`betmaxxing.scheduler.ledger`. The
old ``plan(now)`` + ``due_jobs(now)`` pair could never fire: planning dropped
occurrences at or before ``now`` while selection kept only occurrences at or
before ``now``, so the intersection was empty by construction.

What survives here is the pure time arithmetic — which instants *should* exist —
now consumed by :meth:`JobLedger.materialise`, which owns state, claiming and
idempotency.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from betmaxxing.config import Settings
from betmaxxing.domain.models import CanonicalEvent
from betmaxxing.domain.timeutil import PARIS, ensure_utc, to_display


def daily_instants(settings: Settings, now: datetime, days: int = 2) -> list[datetime]:
    """Future daily scan instants, in UTC.

    Times are read in ``Europe/Paris`` and converted, so "08:00" stays 08:00
    locally across a DST change even though its UTC hour moves.
    """
    out: list[datetime] = []
    moment = ensure_utc(now)
    local_now = to_display(moment, PARIS)
    for day_offset in range(days + 1):
        day = (local_now + timedelta(days=day_offset)).date()
        for entry in settings.scan_time_list:
            hour_str, _, minute_str = entry.partition(":")
            try:
                hour, minute = int(hour_str), int(minute_str or 0)
            except ValueError:
                continue
            run_at = ensure_utc(datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS))
            if run_at > moment:
                out.append(run_at)
    return sorted(out)


def milestone_instants(
    settings: Settings, now: datetime, events: list[CanonicalEvent]
) -> list[tuple[str, datetime]]:
    """``(event internal id, instant)`` pairs still in the future."""
    out: list[tuple[str, datetime]] = []
    moment = ensure_utc(now)
    for event in events:
        start = ensure_utc(event.start_time_utc)
        for hours in settings.milestone_hours:
            run_at = start - timedelta(hours=hours)
            if moment < run_at < start:
                out.append((event.internal_id, run_at))
    return sorted(out, key=lambda pair: pair[1])


def should_rescore(previous_odds: float, current_odds: float, threshold: float = 0.02) -> bool:
    """Whether a price move is large enough to justify an out-of-band rescore."""
    if previous_odds <= 0:
        return True
    return abs(current_odds - previous_odds) / previous_odds >= threshold
